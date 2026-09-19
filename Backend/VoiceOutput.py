"""Offline Windows speech and an optional local reference-voice worker."""
from __future__ import annotations
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

log = logging.getLogger("Jarvis.Speech")


class TTSEngine(Protocol):
    """Non-blocking application-facing speech contract."""
    def speak(self, text: str) -> bool: ...
    def stop(self) -> None: ...
    def is_speaking(self) -> bool: ...
    def set_voice(self, engine: str, voice_id: str = "") -> None: ...
    def set_speed(self, speed: int) -> None: ...
    def set_volume(self, volume: int) -> None: ...


def startup_greeting(settings, now=None):
    import datetime
    hour = (now or datetime.datetime.now()).hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {settings.user_name}. {settings.assistant_name} is ready to help."


def terminate_worker(process):
    """Also stop a Windows venv redirector's child, which owns audio playback."""
    if process is None or process.poll() is not None:
        return
    import psutil
    try:
        children = psutil.Process(process.pid).children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    try:
        process.terminate()
    except ProcessLookupError:
        pass

def installed_voices() -> list[dict]:
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            return [{"id": token.Id, "name": token.GetDescription(), "language": token.GetAttribute("Language")}
                    for token in voice.GetVoices()]
        finally:
            voice = None
            pythoncom.CoUninitialize()
    except Exception as exc:
        log.warning("Could not list installed voices: %s", exc)
        return []

class VoiceOutput:
    def __init__(self, config, on_status=lambda text: None):
        self.config = config
        self.on_status = on_status
        self.speaking = threading.Event()
        self.cancelled = threading.Event()
        self.closed = threading.Event()
        self._queue = queue.Queue()
        self._process = None
        self._lock = threading.RLock()
        self._generation = 0
        self._responses = None
        self._worker_key = None
        self._last_used = 0.0
        self.model_state = "not_loaded"
        self._thread = threading.Thread(target=self._run, name="JarvisSpeech", daemon=True)
        self._thread.start()

    def say(self, text: str, *, force=False, append=False):
        with self._lock:
            if self.closed.is_set() or (not self.config.settings.speech_enabled and not force):
                return False
            if not append and (self.speaking.is_set() or not self._queue.empty()):
                self.stop()
            self._queue.put((self._generation, text))
            return True

    def stop(self):
        with self._lock:
            self._generation += 1
            self.cancelled.set()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            process = self._process
            if process is not None and process.poll() is None:
                terminate_worker(process)
            self.model_state = "not_loaded"

    def speak(self, text):
        return self.say(text)

    def is_speaking(self):
        return self.speaking.is_set()

    def set_voice(self, engine, voice_id=""):
        self.config.update({"voice_provider": engine, "voice_id": voice_id})
        self.stop()

    def set_speed(self, speed):
        self.config.update({"voice_rate": speed})

    def set_volume(self, volume):
        self.config.update({"voice_volume": volume})

    def reload(self):
        self.stop()
        return self.voice_status()

    def voice_status(self):
        from Backend.PersonalVoice import status
        result = status(self.config)
        result["model_state"] = self.model_state
        return result

    def _run(self):
        while not self.closed.is_set():
            try:
                generation, text = self._queue.get(timeout=0.2)
            except queue.Empty:
                if self._process is not None and time.monotonic() - self._last_used > 60:
                    self.stop()
                continue
            with self._lock:
                if generation != self._generation or self.closed.is_set():
                    continue
                self.cancelled.clear()
                self.speaking.set()
            try:
                # Keep spoken answers manageable; full output stays in chat.
                spoken = text if len(text) < 650 else text[:600].rsplit(" ", 1)[0] + ". The full reply is in the chat."
                if self.config.settings.voice_provider == "pocket":
                    try:
                        self._pocket(spoken)
                    except Exception:
                        self.model_state = "unavailable"
                        if not self.cancelled.is_set() and not self.closed.is_set():
                            self.on_status("Personal voice unavailable; using the system voice. Check the local model and reference.")
                            self._windows(spoken)
                else:
                    self._windows(spoken)
            except Exception as exc:
                log.warning("Speech output failed: %s", type(exc).__name__)
                self.on_status("Speech output unavailable. Check your output device and voice settings.")
            finally:
                # Let speaker echo settle before the microphone resumes.
                time.sleep(0.25)
                self.speaking.clear()

    def _windows(self, text):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            cfg = self.config.settings
            speaker.Rate, speaker.Volume = cfg.voice_rate, cfg.voice_volume
            for voice in speaker.GetVoices():
                if cfg.voice_id and voice.Id == cfg.voice_id:
                    speaker.Voice = voice
                    break
            with self._lock:
                if self.cancelled.is_set() or self.closed.is_set():
                    return
                speaker.Speak(text, 1 | 16)  # async, literal text (not XML)
            while not speaker.WaitUntilDone(50):
                if self.cancelled.is_set() or self.closed.is_set():
                    speaker.Speak("", 2)
                    break
        finally:
            speaker = None
            voice = None
            pythoncom.CoUninitialize()

    def _pocket(self, text):
        from Backend.PersonalVoice import worker_python, validate_reference
        import psutil
        cfg = self.config.settings
        if not cfg.voice_consent:
            raise RuntimeError("Voice synthesis consent is required")
        reference = Path(self.config.settings.voice_reference)
        validate_reference(reference)
        if any("\u0600" <= ch <= "\u06ff" for ch in text):
            raise RuntimeError("The personal voice model currently supports English, not Urdu. Choose a Windows Urdu voice for Urdu output.")
        payload = json.dumps({"text": text, "reference": str(reference), "directory": str(self.config.directory),
                              "model_config": cfg.voice_model_config, "speed": cfg.voice_rate, "volume": cfg.voice_volume})
        worker = Path(__file__).resolve().parent.parent / "scripts/voice_worker.py"
        python = worker_python(self.config)
        key = (str(python), cfg.voice_model_config, str(reference), reference.stat().st_mtime_ns)
        with self._lock:
            if self.cancelled.is_set() or self.closed.is_set():
                return
            process = self._process
            if process is None or process.poll() is not None or self._worker_key != key:
                if process is not None and process.poll() is None:
                    terminate_worker(process)
                if psutil.virtual_memory().available < 1536 * 1024**2:
                    raise RuntimeError("Insufficient free RAM for personal speech")
                process = subprocess.Popen([str(python), "-u", "-X", "utf8", str(worker)], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self._process = process
                self._worker_key = key
                responses = queue.Queue()
                self._responses = responses
                def read_responses():
                    try:
                        for line in process.stdout:
                            responses.put(json.loads(line))
                    except (ValueError, OSError):
                        responses.put({"ok": False})
                    finally:
                        responses.put({"ok": False})
                        process.stdout.close()
                threading.Thread(target=read_responses, daemon=True, name="PersonalVoiceReplies").start()
            self.model_state = "loading"
            process.stdin.write(payload + "\n")
            process.stdin.flush()
        try:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if self.cancelled.is_set() or self.closed.is_set():
                    return
                worker_process = psutil.Process(process.pid)
                memory = sum(p.memory_info().rss for p in [worker_process, *worker_process.children(recursive=True)])
                if memory > 2304 * 1024**2:
                    raise RuntimeError("Personal voice exceeded its memory budget")
                try:
                    reply = self._responses.get(timeout=0.05)
                except queue.Empty:
                    continue
                if not reply.get("ok"):
                    raise RuntimeError("Local personal voice worker failed")
                self.model_state = "loaded"
                return
            raise RuntimeError("Personal voice generation timed out")
        except Exception:
            if process.poll() is None:
                terminate_worker(process)
            raise
        finally:
            self._last_used = time.monotonic()
            if process.poll() is not None:
                process.stdin.close()

    def close(self):
        self.closed.set()
        self.stop()
        self._thread.join(timeout=2)
