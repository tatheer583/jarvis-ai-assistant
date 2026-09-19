"""Application boundary shared by desktop IPC, Qt and CLI compatibility callers."""
from dataclasses import asdict
import threading
import uuid
from Backend.Assistant import Assistant
from Backend.Events import EventBus
from Backend.Audit import AuditUnavailable
from Backend.Permissions import ExecutionContext, Risk, PermissionDenied

class Services:
    def __init__(self, config, *, assistant=None, events=None):
        self.config = config
        self.events = events or EventBus()
        self.assistant = assistant or Assistant(config, events=self.events)
        self.security = self.assistant.security
        self.audit = self.assistant.audit
        self._settings_lock = threading.Lock()

    def context(self, source="typed"):
        return ExecutionContext(self.assistant.session_id, source=source, legacy_local=True)

    def call(self, operation, callback, *, context=None):
        # Static scope table: adding an operation requires a deliberate declaration.
        scopes = {
            "memory.read": Risk.MEDIUM, "files.search": Risk.MEDIUM,
            "windows.read": Risk.MEDIUM, "settings.update": Risk.MEDIUM,
            "files.index": Risk.MEDIUM, "models.download": Risk.MEDIUM,
            "system.autostart": Risk.HIGH,
        }
        if operation not in scopes:
            raise PermissionDenied("unknown_service_operation")
        context = context or self.context()
        decision = self.security.decide(operation, scopes[operation], context, legacy_allowed=True)
        metadata = {"task_id": uuid.uuid4().hex, "source": context.source, "tool": operation,
                    "risk": scopes[operation].name.lower()}
        self.audit.record(**metadata, outcome="allowed" if decision.allowed else "denied", code=decision.code)
        if not decision.allowed:
            raise PermissionDenied(decision.code)
        try:
            result = callback()
        except Exception as exc:
            self.audit.record(**metadata, outcome="failed", code=type(exc).__name__)
            raise
        try:
            self.audit.record(**metadata, outcome="succeeded")
        except AuditUnavailable as exc:
            raise AuditUnavailable("The operation may have completed, but its result could not be audited. Verify before retrying.") from exc
        return result

    def execute(self, text, *, source="typed", token=None, context=None):
        return self.assistant.handle(text, source=source, token=token, context=context)

    def execute_command(self, command, *, source="compatibility"):
        return self.assistant.handle(command.target or command.action, source=source, commands_override=[command])

    def memory(self, *, context=None):
        return self.call("memory.read", lambda: {
            "history": self.assistant.store.history(80), "notes": self.assistant.store.notes(),
            "reminders": self.assistant.store.reminders()}, context=context)

    def files(self, query, kind="", *, context=None):
        return self.call("files.search", lambda: self.assistant.index.search(query, kind=kind, limit=60), context=context)

    def windows(self, *, context=None):
        return self.call("windows.read", self.assistant.desktop.windows, context=context)

    def update_settings(self, values):
        with self._settings_lock:
            def update():
                self.config.update(values)
                self.audit.retention_days = self.config.settings.audit_retention_days
                return asdict(self.config.settings)
            return self.call("settings.update", update)

    def stop(self):
        self.assistant.stop()
