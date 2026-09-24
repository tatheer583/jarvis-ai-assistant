"""Local JSON-line transport for the Tauri shell. No sockets or HTTP server."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from Backend.Services import Services
from Backend.Tasks import CancellationToken
from Backend.Events import EventBus
from Backend.ReplyStream import spoken_boundary
from Backend.Commands import parse_command
from Backend.Config import Config, PROJECT_DIR
from Backend.VoiceInput import VoiceInput, microphones
from Backend.VoiceOutput import VoiceOutput, installed_voices

log = logging.getLogger('Jarvis.Engine')

class EngineService:
    def __init__(self, config, emit, *, start_workers=True, services=None, voice_factory=VoiceInput, speaker_factory=VoiceOutput):
        self.config, self.emit = config, emit
        events = EventBus()
        # Reply deltas pass through cancellation checks before UI or speech.
        self.services = services or Services(config, events=events)
        self.assistant = self.services.assistant
        self.closed = threading.Event()
        self.busy = threading.Event()
        self.tasks = queue.Queue(maxsize=4)
        self.state_lock = threading.RLock()
        self.status = 'Ready to activate.'
        self.speaker = speaker_factory(config, self.set_status)
        self.voice = voice_factory(config, on_text=lambda text: self.submit(text, source='voice'),
            on_status=self.set_status, on_level=lambda value: self.emit('level', value),
            on_enabled=lambda enabled: self.emit('listening', enabled),
            suppressed=lambda: self.busy.is_set() or self.speaker.speaking.is_set(),
            followup=self.assistant.awaiting_reply)
        self._connected = False
        self._active_token = None
        self._generation = 0
        self._reply_task = None
        self._reply_text = ""
        self._spoken_prefix = 0
        self._progress_at = 0.0
        self._command_started = 0.0
        self._first_reply_at = None
        self.assistant.events.subscribe(self._on_event)
        self._native_requests = {}
        self._scan = None
        self._setup = None
        self._setup_process = None
        self._worker = threading.Thread(target=self._commands, daemon=True, name='JarvisCommands')
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True, name='JarvisMonitor')
        if start_workers:
            self._worker.start()
            self._monitor.start()

    def _on_event(self, event):
        if event.name != "reply_delta":
            self.emit(event.name, event.data)
            return
        with self.state_lock:
            token, task = self._active_token, self.assistant.current_task
            if (token is None or token.event.is_set() or task is None
                    or event.data["task_id"] != task.id or self.closed.is_set()):
                return
            self._reply_task = task.id
            self._reply_text += event.data["text"]
            now = time.monotonic()
            if self._first_reply_at is None and self._reply_text.strip():
                self._first_reply_at = now
            if now - self._progress_at >= 0.08:
                self.emit("reply_progress", {"task_id": task.id, "content": self._reply_text})
                self._progress_at = now
            if not self._spoken_prefix and self.config.settings.voice_provider == "windows":
                boundary = spoken_boundary(self._reply_text)
                if 0 < boundary <= 600:
                    # Start the first sentence now; queue the remainder on success.
                    # The optional personal voice worker remains one request per reply.
                    if self.speaker.say(self._reply_text[:boundary].strip(), append=True):
                        self._spoken_prefix = boundary

    def _speak_result(self, result, token):
        with self.state_lock:
            if token.event.is_set() or result.action in {"grid", "mouse", "keys"}:
                return
            if (result.success and result.action == "chat" and self._spoken_prefix
                    and self._reply_text.strip() == result.message.strip()):
                remainder = self._reply_text[self._spoken_prefix:].strip()
                available = max(0, 600 - self._spoken_prefix)
                if len(remainder) > available:
                    remainder = remainder[:available].rsplit(" ", 1)[0] + ". The full reply is in the chat."
                if remainder:
                    self.speaker.say(remainder, append=True)
            else:
                self.speaker.say(result.message)

    def set_status(self, message):
        self.status = str(message)
        self.emit('status', self.status)

    def snapshot(self):
        import psutil
        cfg = self.config.settings
        return {
            'settings': asdict(cfg), 'status': self.status, 'listening': self.voice.enabled.is_set(),
            'busy': self.busy.is_set(), 'speaking': self.speaker.speaking.is_set(),
            'speech_ready': (Path(cfg.whisper_path) / 'model.bin').is_file(),
            'chat_ready': self.assistant.brain.ready(), 'index_count': self.assistant.index.count(),
            'indexing': self.assistant.index.scanning, **self.services.memory(),
            'security': self.services.security.snapshot(),
            'current_task': self.assistant.current_task.to_dict() if self.assistant.current_task else None,
            'provider': {'name': 'local', 'online': False},
            'data_directory': str(self.config.directory), 'memory_percent': psutil.virtual_memory().percent,
        }

    def handle(self, request):
        validate_request(request)
        op = request.get('op')
        if op == 'connect':
            pid = request.get('shell_pid')
            if isinstance(pid, int):
                self.assistant.desktop.excluded_pids = {pid}
            if not self._connected:
                self._connected = True
                self.refresh_index()
                if self.config.settings.listen_on_startup and not request.get('no_listen', False):
                    self.voice.set_enabled(True)
                    self.speaker.say('Jarvis is ready. Say Jarvis, followed by your command.')
            return self.snapshot()
        if op == 'snapshot':
            return self.snapshot()
        if op == 'command':
            text = request.get('text', '')
            if not isinstance(text, str) or not 0 < len(text.strip()) <= 12000:
                raise ValueError('Enter a command of up to 12,000 characters.')
            return {'accepted': self.submit(text)}
        if op == 'listen':
            enabled = request.get('enabled')
            if type(enabled) is not bool:
                raise ValueError('Listening must be on or off.')
            self.speaker.stop()
            self.voice.set_enabled(enabled, once=bool(request.get('once', False)))
            if not enabled:
                self.set_status('Microphone paused.')
            return {'listening': enabled}
        if op in {'stop', 'emergency'}:
            self.stop(pause=op == 'emergency')
            return {'stopped': True}
        if op == 'settings':
            values = request.get('values', {})
            if not isinstance(values, dict):
                raise ValueError('Settings must be an object.')
            listening = self.voice.enabled.is_set()
            saved = self.services.update_settings(values)
            self.voice.set_enabled(False)
            if listening:
                self.voice.set_enabled(True)
            if 'search_roots' in values:
                self.refresh_index()
            return saved
        if op == 'devices':
            return {'microphones': microphones(), 'voices': installed_voices()}
        if op == 'files':
            return self.services.files(request.get('query', ''), request.get('kind', ''))
        if op == 'index':
            self.services.call('files.index', self.refresh_index)
            return {'started': True}
        if op == 'windows':
            return self.services.windows()
        if op == 'voice_test':
            self.speaker.say('Hello. I am Jarvis. Your desktop is at your command.', force=True)
            return {'started': True}
        if op == 'download_models':
            self.services.call('models.download', self.download_models)
            return {'started': True}
        if op == 'autostart_authorize':
            import uuid
            def authorize():
                ticket = uuid.uuid4().hex
                with self.state_lock:
                    self._native_requests = {k: v for k, v in self._native_requests.items() if v[0] > time.monotonic()}
                    self._native_requests[ticket] = (time.monotonic() + 10, request['enabled'])
                return {'ticket': ticket}
            return self.services.call('system.autostart', authorize)
        if op == 'autostart_result':
            with self.state_lock:
                pending = self._native_requests.pop(request['ticket'], None)
            if pending is None or pending[0] <= time.monotonic():
                raise ValueError('Native authorization expired or already consumed.')
            self.services.audit.record(tool='system.autostart', risk='high', source='typed',
                outcome='succeeded' if request['success'] else 'failed')
            return {'recorded': True}
        if op == 'quit':
            self.close()
            return {'closed': True}
        raise ValueError('Unknown desktop request.')

    def submit(self, text, source='typed'):
        if self.closed.is_set():
            return False
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 12000:
            return False
        text = text.strip()
        if parse_command(text).action == 'stop_speaking':
            self.stop()
            return True
        with self.state_lock:
            if self.busy.is_set():
                if source != 'voice':
                    self.set_status('A command is in progress. Press Stop to cancel it first.')
                return False
            self.busy.set()
            self.emit('busy', True)
            token = CancellationToken()
            self.tasks.put_nowait((text, source, token, self._generation))
        return True

    def stop(self, *, pause=False):
        # Cancel queued/dequeued work before doing anything that can block.
        with self.state_lock:
            self._generation += 1
            if self._active_token:
                self._active_token.cancel()
            while True:
                try:
                    _, _, token, _ = self.tasks.get_nowait()
                    token.cancel()
                except queue.Empty:
                    break
            if self._active_token is None:
                self.busy.clear()
        self.services.stop()
        self.speaker.stop()
        if pause:
            self.voice.set_enabled(False)
        self.emit('reply_progress', {'task_id': self._reply_task, 'content': ''})
        self.emit('result', {'success': True, 'action': 'grid', 'message': 'Stop requested.', 'data': {'grid': None}})
        self.emit('busy', self.busy.is_set())
        self.set_status('Stop requested. Microphone paused.' if pause else 'Stop requested.')

    def _commands(self):
        while not self.closed.is_set():
            try:
                text, source, token, generation = self.tasks.get(timeout=0.2)
            except queue.Empty:
                continue
            with self.state_lock:
                if generation != self._generation or token.event.is_set():
                    continue
                self._active_token = token
                self._reply_task = None
                self._reply_text = ""
                self._spoken_prefix = 0
                self._progress_at = 0.0
                self._command_started = time.monotonic()
                self._first_reply_at = None
                self.speaker.stop()
            self.emit('message', {'role': 'user', 'content': text})
            self.set_status('Working on your command…')
            try:
                result = self.services.execute(text, source=source, token=token)
                self.emit("response_timing", {
                    "first_text_ms": round((self._first_reply_at - self._command_started) * 1000) if self._first_reply_at else None,
                    "duration_ms": round((time.monotonic() - self._command_started) * 1000),
                    "action": result.action, "success": result.success,
                })
                self.emit('message', {'role': 'assistant', 'content': result.message})
                self.emit('result', result.to_dict())
                if result.action in {'reindex', 'file_action'} and result.success:
                    self.refresh_index()
                if result.action == 'pause_listening':
                    self.voice.set_enabled(False)
                if result.action == 'exit':
                    self.emit('quit', True)
                # Grid actions stay quiet so follow-up clicks are fast.
                self._speak_result(result, token)
                self.emit('activity', self.services.memory())
            except Exception as exc:
                self.speaker.stop()
                log.exception('Command failed')
                self.emit('message', {'role': 'assistant', 'content': f'I could not complete that command: {exc}'})
            finally:
                with self.state_lock:
                    self._active_token = None
                    self.busy.clear()
                self.emit('busy', False)
                self.set_status(f'Listening for {self.config.settings.wake_word}…' if self.voice.enabled.is_set() else 'Ready. Microphone paused.')

    def _monitor_loop(self):
        import psutil
        last_report = 0
        while not self.closed.wait(0.2):
            self.assistant.desktop.remember_foreground()
            if time.monotonic() - last_report < 1.5:
                continue
            last_report = time.monotonic()
            try:
                self.emit('metrics', {'memory_percent': psutil.virtual_memory().percent,
                    'cpu_percent': psutil.cpu_percent(), 'speaking': self.speaker.speaking.is_set()})
                for reminder in self.assistant.store.take_due_reminders():
                    text = 'Reminder: ' + reminder['text']
                    self.assistant.store.add_message('assistant', text)
                    self.emit('message', {'role': 'assistant', 'content': text})
                    self.emit('notification', text)
                    if not self.busy.is_set():
                        self.speaker.say(text)
            except Exception:
                log.exception('Background service error')

    def refresh_index(self):
        if self._scan and self._scan.is_alive():
            return
        def scan():
            try:
                self.emit('index', {'indexing': True})
                count = self.assistant.index.scan(self.config.settings.search_roots, self.closed,
                    progress=lambda n: self.emit('index', {'index_count': n, 'indexing': True}))
                self.emit('index', {'index_count': count, 'indexing': False})
            except Exception as exc:
                self.emit('index', {'indexing': False, 'error': str(exc)})
        self._scan = threading.Thread(target=scan, daemon=True, name='JarvisFiles')
        self._scan.start()

    def download_models(self):
        if self._setup and self._setup.is_alive():
            raise ValueError('Model setup is already running.')
        def setup():
            command = [sys.executable, '--download-models'] if getattr(sys, 'frozen', False) else [sys.executable, '-u', str(PROJECT_DIR / 'Main.py'), '--download-models']
            try:
                self._setup_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                for line in self._setup_process.stdout:
                    self.emit('setup', {'message': line.strip(), 'running': True})
                code = self._setup_process.wait()
                self.emit('setup', {'message': 'Local models are ready.' if code == 0 else 'Setup did not finish. Retry to resume the download.', 'running': False, 'success': code == 0})
            except Exception as exc:
                self.emit('setup', {'message': str(exc), 'running': False, 'success': False})
            finally:
                self._setup_process = None
        self._setup = threading.Thread(target=setup, daemon=True)
        self._setup.start()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        self.voice.close()
        self.speaker.close()
        self.stop(pause=True)
        if self._setup_process and self._setup_process.poll() is None:
            self._setup_process.terminate()
        if self._worker.is_alive():
            self._worker.join(timeout=2)
        if self._scan and self._scan.is_alive():
            self._scan.join(timeout=2)

def serve(config, *, no_listen=False):
    # Frozen Python can ignore PYTHONUTF8. Rust always sends/reads UTF-8 JSON.
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, 'reconfigure', None)
        if reconfigure:
            reconfigure(encoding='utf-8', errors='strict')
    if getattr(sys.stderr, 'reconfigure', None):
        sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
    lock = threading.Lock()
    transport = sys.stdout
    # Python library prints go to the log pipe; stdout is reserved for structured events.
    sys.stdout = sys.stderr
    def emit(event, data):
        with lock:
            try:
                transport.write(json.dumps({'event': event, 'data': data}, ensure_ascii=False) + '\n')
                transport.flush()
            except (BrokenPipeError, OSError):
                pass
    if no_listen:
        config.settings.listen_on_startup = False
    service = EngineService(config, emit)
    executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix='JarvisRequest')
    slots = threading.BoundedSemaphore(16)
    def respond(request):
        try:
            data = service.handle(request)
            if 'id' in request:
                emit('response', {'id': request['id'], 'value': data})
        except Exception as exc:
            if 'id' in request:
                emit('response', {'id': request['id'], 'error': str(exc)})
            else:
                emit('error', str(exc))
    emit('ready', {'edition': 'Jarvis Desktop', 'transport': 'stdio'})
    try:
        for line in sys.stdin:
            if len(line) > 200000:
                emit('error', 'Local request exceeds 200 KB.')
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    continue
                if request.get('op') == 'quit':
                    break
                if request.get('op') in {'emergency', 'stop'}:
                    respond(request)
                elif slots.acquire(blocking=False):
                    future = executor.submit(respond, request)
                    future.add_done_callback(lambda _: slots.release())
                elif 'id' in request:
                    emit('response', {'id': request['id'], 'error': 'Local request queue is full.'})
            except ValueError:
                emit('error', 'Invalid local request.')
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        service.close()
    return 0

# The renderer can supply data, never identity, permissions, callbacks or code.
REQUEST_FIELDS = {
    'connect': {'shell_pid': int, 'no_listen': bool}, 'snapshot': {},
    'command': {'text': str}, 'listen': {'enabled': bool, 'once': bool},
    'stop': {}, 'emergency': {}, 'settings': {'values': dict}, 'devices': {},
    'files': {'query': str, 'kind': str}, 'index': {}, 'windows': {}, 'voice_test': {},
    'download_models': {}, 'quit': {}, 'autostart_authorize': {'enabled': bool},
    'autostart_result': {'ticket': str, 'success': bool},
}
REQUIRED_FIELDS = {'command': {'text'}, 'listen': {'enabled'}, 'settings': {'values'},
                   'autostart_authorize': {'enabled'}, 'autostart_result': {'ticket', 'success'}}

def validate_request(request):
    if not isinstance(request, dict) or not isinstance(request.get('op'), str) or request['op'] not in REQUEST_FIELDS:
        raise ValueError('Unknown desktop request.')
    schema = REQUEST_FIELDS[request['op']]
    if set(request) - {'op', 'id'} - schema.keys() or REQUIRED_FIELDS.get(request['op'], set()) - request.keys():
        raise ValueError('Unexpected or missing request fields.')
    if 'id' in request and (type(request['id']) is not int or not 0 <= request['id'] <= 2**53 - 1):
        raise ValueError('Invalid request ID.')
    for key, kind in schema.items():
        if key in request and type(request[key]) is not kind:
            raise ValueError('Invalid request field type.')
        if key in request and isinstance(request[key], str) and (len(request[key]) > (12000 if key == 'text' else 500) or '\x00' in request[key]):
            raise ValueError('Request field exceeds its limit.')
