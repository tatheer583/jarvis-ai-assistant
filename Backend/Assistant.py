"""One local command engine shared by the desktop UI, voice, and CLI."""
from __future__ import annotations
import datetime as dt
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

from Backend.ActionResult import ActionResult
from Backend.Commands import Command, parse_commands, reminder_details
from Backend.Config import Config
from Backend.Desktop import Desktop
from Backend.FileIndex import FileIndex
from Backend.FileActions import FileActions
from Backend.LocalBrain import LocalBrain, ModelUnavailable
from Backend.Store import Store
from Backend.Events import EventBus
from Backend.Audit import AuditLog
from Backend.Permissions import SecurityManager, ExecutionContext, Risk, PermissionDenied
from Backend.Tasks import Task, TaskState, CancellationToken, cancellation_scope
from Backend.Tools import builtin_registry, ToolExecutor
from Backend.AIProviders import AIOrchestrator, LocalProvider

log = logging.getLogger("Jarvis")
HELP = """Try these commands:
• Open downloads / open notepad / open file budget.xlsx
• Find PDF invoice / find folder project / open C:\\Users\\...
• Close notepad / close budget.xlsx / list windows
• Search for Python tutorials / search YouTube for relaxing music
• Remind me in 10 minutes to drink water / list reminders
• Take a note buy milk / show notes
• Type Hello, how are you?
• Press control S / copy / paste / undo / select all
• Click / right click / move mouse right 100 / scroll down
• Show grid / zoom five / click five / hide grid
• Click the Save button / focus Chrome / maximize notepad
• Create folder Projects in documents / copy file PATH to downloads
• Recycle file PATH (asks for confirmation)
• Mute / unmute / set volume to 40 percent / next track
• Take a screenshot / system status / what time is it?
• English mode / Urdu mode / stop speaking / quit Jarvis
Say “Jarvis” before a command in hands-free mode, or use Listen once.
When results appear, say “open the first one” or choose a number."""

class Assistant:
    def __init__(self, config: Config, *, desktop=None, brain=None, events=None, audit=None):
        self.config = config
        self.store = Store(config.database)
        self.index = FileIndex(self.store)
        self.files = FileActions(config, self.index)
        self.desktop = desktop or Desktop()
        self.events = events or EventBus()
        self.audit = audit or AuditLog(config.directory, config.settings.audit_retention_days)
        self.security = SecurityManager()
        self.session_id = uuid.uuid4().hex
        self.brain = brain or AIOrchestrator(LocalProvider(config), events=self.events)
        self.registry = builtin_registry(self._execute)
        self.executor = ToolExecutor(self.registry, self.security, self.audit, self.events)
        self.current_task = None
        self._stream_chat = False
        self._token = None
        self._context = ExecutionContext(self.session_id, legacy_local=True)
        self._confirmed = False
        self.pending: dict | None = None
        self._lock = threading.Lock()
        self._migrate_history()

    def _migrate_history(self):
        from Backend.Config import PROJECT_DIR, data_directory
        if self.config.directory != data_directory() or self.store.history(1):
            return
        old = PROJECT_DIR / "Data/ChatLog.json"
        try:
            data = json.loads(old.read_text(encoding="utf-8"))
            for message in data[-100:]:
                if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
                    self.store.add_message(message["role"], str(message.get("content", "")))
        except (OSError, ValueError, TypeError):
            pass

    def awaiting_reply(self) -> bool:
        return self.pending is not None and time.monotonic() < self.pending["expires"]

    @property
    def pending(self):
        return self.security.pending

    @pending.setter
    def pending(self, value):
        self.security.pending = value

    def stop(self):
        # No audit, model lock or transport I/O on this cancellation path.
        token = self._token
        if token is not None:
            token.cancel()
        self.security.clear()
        self.desktop.grid_region = None
        self.brain.stop()

    def _invoke(self, command, history):
        return self.executor.execute(command, self._context, self._token, self.current_task, history)

    def handle(self, text: str, *, source="typed", token=None, context=None, commands_override=None) -> ActionResult:
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 12000 or "\x00" in text:
            return ActionResult.fail("validation", "Enter a command of up to 12,000 characters.")
        if not self._lock.acquire(False):
            return ActionResult.fail("busy", "I am still finishing your previous request.")
        self._context = context or ExecutionContext(self.session_id, source=source, legacy_local=True)
        self._token = token or CancellationToken()
        task = self.current_task = Task(self._context.source)
        task.state = TaskState.RUNNING
        private = self.security.decide("memory.read", Risk.MEDIUM, self._context, legacy_allowed=True).allowed
        try:
            with cancellation_scope(self._token):
                history = self.store.history(6) if private else []
                if private:
                    self.store.add_message("user", text)
                commands = commands_override if commands_override is not None else parse_commands(text)
                self._stream_chat = len(commands) == 1 and commands[0].action == "chat"
                if self.pending and not self.awaiting_reply():
                    self.pending = None
                if commands[0].action not in {"confirm", "cancel", "choose"}:
                    self.pending = None
                if len(commands) > 1 and any((c.action == "system" and c.target in {"shutdown", "restart", "sleep", "lock"}) or (c.action == "file_action" and c.options.get("operation") == "recycle") for c in commands):
                    result = ActionResult.fail("confirm", "Please give power or recycle actions as a separate command.")
                else:
                    results = []
                    for command in commands:
                        result = self._invoke(command, history)
                        results.append(result)
                        if self.pending or result.action == "exit" or result.error in {"cancelled", "timeout", "permission_denied", "audit_unavailable"}:
                            break
                    result = results[0] if len(results) == 1 else ActionResult(
                        all(r.success for r in results), "batch", "\n".join(r.message for r in results),
                        {"results": [r.to_dict() for r in results]},
                        next((r.error for r in results if r.error), None))
                if private:
                    self.store.add_message("assistant", result.message)
                task.state = (TaskState.CANCELLED if self._token.event.is_set() else
                              TaskState.WAITING if self.pending else
                              TaskState.SUCCEEDED if result.success else TaskState.FAILED)
                return result
        finally:
            if task.state == TaskState.RUNNING:
                task.state = TaskState.FAILED
            task.finished = time.time()
            self.events.emit("task", task.to_dict())
            self._token = None
            self._lock.release()

    def _choices(self, items: list[dict], action: str) -> ActionResult:
        self.pending = {"kind": "choice", "items": items, "action": action, "session_id": self._context.session_id, "principal_id": self._context.principal.id, "expires": time.monotonic() + 90}
        listing = "\n".join(f"{i}. {item['name']}" for i, item in enumerate(items, 1))
        return ActionResult.ok("choices", "Choose a result by number:\n" + listing, choices=items)

    def _execute(self, cmd: Command, history: list[dict]) -> ActionResult:
        action, target = cmd.action, cmd.target
        if action == "help":
            return ActionResult.ok(action, HELP)
        if action == "cancel":
            self.pending = None
            return ActionResult.ok(action, "Cancelled.")
        if action == "confirm":
            if not self.pending or self.pending["kind"] != "confirmation":
                return ActionResult.fail(action, "There is no pending action to confirm.")
            pending = self.security.consume(self._context)
            if pending.get("stamp") is not None and pending["stamp"] != self._file_stamp(pending["target"]):
                return ActionResult.fail("confirm", "The file changed after confirmation was requested. Ask to open it again.")
            self._confirmed = True
            try:
                if pending["action"] == "file_action":
                    info = pending["file"]
                    command = Command("file_action", info["source"], {"operation": info["operation"], "destination": info.get("destination", "")})
                elif pending["action"] == "open":
                    command = Command("open", pending["target"], {"kind": "file"})
                else:
                    command = Command("system", pending["target"])
                return self._invoke(command, history)
            finally:
                self._confirmed = False
        if action == "choose":
            if not self.pending or self.pending["kind"] != "choice":
                return ActionResult.fail(action, "Search for a file or window first, then choose a result.")
            if self.pending.get("session_id") != self._context.session_id or self.pending.get("principal_id") != self._context.principal.id:
                raise PermissionDenied("choice_session_mismatch")
            number = cmd.options["index"] - 1
            items = self.pending["items"]
            if not 0 <= number < len(items):
                return ActionResult.fail(action, f"Choose a number from 1 to {len(items)}.")
            item, next_action = items[number], self.pending["action"]
            self.pending = None
            resolved = "window" if next_action.startswith("window:") else next_action
            definition = self.registry.get(resolved)
            self.security.require(resolved, definition.risk, self._context, legacy_allowed=True)
            if next_action.startswith("window:"):
                return self.desktop.window_action(item["hwnd"], next_action.split(":", 1)[1])
            return self.desktop.close_window(item["hwnd"]) if next_action == "close" else self._open_file(item["path"])
        if action in {"open", "find"}:
            if action == "open":
                alias = self.config.settings.aliases.get(target.casefold())
                if alias:
                    return self._open_file(alias)
                if not cmd.options.get("kind"):
                    result = self.desktop.open_app(target)
                    if result is not None:
                        return result
            hits = self.index.search(target, kind=cmd.options.get("kind", ""))
            # Remove deleted results without reading file contents.
            hits = [hit for hit in hits if Path(hit["path"]).exists()]
            if not hits:
                return ActionResult.fail(action, f"I could not find '{target}'. Use Files to refresh the index or add its folder. You can also give the full path.")
            if action == "open" and len(hits) == 1 and hits[0]["score"] >= 0.9:
                return self._open_file(hits[0]["path"])
            return self._choices(hits, "open")
        if action == "close":
            hits = self.desktop.matching_windows(target)
            if not hits:
                return ActionResult.fail(action, f"I could not find an open window matching '{target}'. Say list windows.")
            if len(hits) == 1:
                return self.desktop.close_window(hits[0]["hwnd"])
            return self._choices(hits, "close")
        if action == "windows":
            items = self.desktop.windows()
            return self._choices(items[:8], "window:focus") if items else ActionResult.ok(action, "No other application windows were found.")
        if action == "system":
            if target in {"shutdown", "restart", "sleep", "lock"} and not self._confirmed:
                self.security.challenge({"action": "system", "target": target}, self._context)
                return ActionResult.ok("confirmation", f"Confirm {target}? Say yes or no within 30 seconds.", confirmation=True)
            return self.desktop.system(target, confirmed=True) if self._confirmed else self.desktop.system(target)
        if action == "window":
            hits = self.desktop.matching_windows(target)
            operation = cmd.options["operation"]
            if not hits:
                return ActionResult.fail(action, f"No matching window: {target}.")
            if len(hits) == 1:
                return self.desktop.window_action(hits[0]["hwnd"], operation)
            return self._choices(hits[:8], "window:" + operation)
        if action == "keys":
            return self.desktop.keyboard(target, cmd.options.get("count", 1))
        if action == "mouse":
            return self.desktop.mouse(target, **cmd.options)
        if action == "grid":
            return self.desktop.grid(target, **cmd.options)
        if action == "volume":
            return self.desktop.set_volume(int(target))
        if action == "click_control":
            return self.desktop.click_control(target)
        if action == "file_action":
            result = self.files.execute(cmd.options["operation"], target, cmd.options.get("destination", ""), confirmed=self._confirmed)
            confirmation = (result.data or {}).get("file_confirmation")
            if confirmation:
                self.security.challenge({"action": action, "file": confirmation, "target": confirmation["source"], "stamp": self._file_stamp(confirmation["source"])}, self._context)
            return result
        if action == "pause_listening":
            return ActionResult.ok(action, "Microphone paused. Use Activate or Control Alt J to listen again.")
        if action == "interface":
            return ActionResult.ok(action, "Jarvis " + target + ".", interface=target)
        if action == "web":
            return self.desktop.web_search(target, cmd.options.get("engine", self.config.settings.web_search_engine))
        if action == "type":
            return self.desktop.type_text(target)
        if action == "reminder":
            try:
                note, due = reminder_details(target)
            except ValueError as exc:
                return ActionResult.fail(action, str(exc))
            reminder_id = self.store.add_reminder(note, due.timestamp())
            return ActionResult.ok(action, f"Reminder {reminder_id}: {note}, on {due.strftime('%d %b at %I:%M %p')}. Jarvis will notify you while it is running.")
        if action == "list_reminders":
            items = self.store.reminders()
            text = "\n".join(f"{r['id']}. {r['text']} — {dt.datetime.fromtimestamp(r['due']).strftime('%d %b, %I:%M %p')}" for r in items)
            return ActionResult.ok(action, text or "You have no pending reminders.")
        if action == "cancel_reminder":
            removed = self.store.cancel_reminder(int(target))
            return ActionResult(removed, action, "Reminder cancelled." if removed else "That reminder was not found.")
        if action == "note":
            number = self.store.add_note(target)
            return ActionResult.ok(action, f"Saved note {number}: {target}")
        if action == "list_notes":
            return ActionResult.ok(action, "\n".join(f"{n['id']}. {n['content']}" for n in self.store.notes()) or "You have no saved notes.")
        if action == "time":
            return ActionResult.ok(action, dt.datetime.now().strftime("The time is %I:%M %p."))
        if action == "date":
            return ActionResult.ok(action, dt.datetime.now().strftime("Today is %A, %d %B %Y."))
        if action == "language":
            self.config.update({"language": target})
            return ActionResult.ok(action, {"en": "English mode enabled.", "ur": "Urdu listening enabled. Spoken Urdu replies require an installed Urdu Windows voice.", "auto": "Automatic English and Urdu recognition enabled."}[target])
        if action == "status":
            import psutil
            memory = psutil.virtual_memory()
            battery = psutil.sensors_battery()
            message = f"Memory: {memory.percent}% used. Indexed files and folders: {self.index.count():,}. Local chat model: {'ready' if self.brain.ready() else 'not installed'}."
            if battery:
                message += f" Battery: {battery.percent:.0f}%."
            return ActionResult.ok(action, message)
        if action == "screenshot":
            from PIL import ImageGrab
            folder = self.config.directory / "Screenshots"
            folder.mkdir(exist_ok=True)
            path = folder / (dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".png")
            ImageGrab.grab(all_screens=True).save(path)
            return ActionResult.ok(action, f"Screenshot saved: {path}", path=str(path))
        if action == "content":
            answer = self.brain.reply("Draft the following text. Return just the draft:\n" + target, history)
            folder = self.config.directory / "Documents"
            folder.mkdir(exist_ok=True)
            title = re.sub(r"[^\w -]", "", target)[:55].strip() or "Draft"
            path = folder / (title + "-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".txt")
            path.write_text(answer, encoding="utf-8")
            return ActionResult.ok(action, answer + f"\n\nSaved to {path}", path=str(path))
        if action == "chat":
            try:
                if self._stream_chat and isinstance(self.brain, AIOrchestrator):
                    def on_delta(piece):
                        from Backend.Tasks import checkpoint
                        checkpoint()
                        self.events.emit("reply_delta", {"task_id": self.current_task.id, "text": piece})
                    return ActionResult.ok(action, self.brain.reply(target, history, on_delta=on_delta))
                return ActionResult.ok(action, self.brain.reply(target, history))
            except ModelUnavailable as exc:
                return ActionResult.fail(action, str(exc), error="model_missing")
        if action == "message":
            return ActionResult.fail(action, "Automatic messaging is not enabled in the local edition. Say open WhatsApp to use WhatsApp Web.")
        if action == "image":
            return ActionResult.fail(action, "Local image generation needs a separate image model and more memory. It is not installed in this edition.")
        if action in {"reindex", "stop_speaking", "exit"}:
            return ActionResult.ok(action, {"reindex": "Refreshing your file index.", "stop_speaking": "Stopped.", "exit": "Goodbye."}[action])
        return ActionResult.fail(action, "I do not recognize that command. Say help to see examples.")

    def _open_file(self, path: str) -> ActionResult:
        # Recognized apps launch normally; a found script/executable needs an explicit second turn.
        if not self._confirmed and Path(path).suffix.lower() in {".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".reg", ".scr", ".lnk"}:
            self.security.challenge({"action": "open", "target": path, "stamp": self._file_stamp(path)}, self._context)
            return ActionResult.ok("confirmation", f"Run {Path(path).name}? Say yes or no within 30 seconds.", confirmation=True)
        return self.desktop.open_path(path)

    @staticmethod
    def _file_stamp(path):
        stat = Path(path).stat()
        return (stat.st_ino, stat.st_size, stat.st_mtime_ns)
