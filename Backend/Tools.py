"""Explicit tools around existing command handlers. No dynamic plugin/code loading."""
from dataclasses import dataclass
from typing import Callable
from Backend.ActionResult import ActionResult
from Backend.Commands import Command, SYSTEM
from Backend.Permissions import Risk, PermissionDenied
from Backend.Tasks import TaskStep, TaskState, Cancelled, TaskTimeout
from Backend.Audit import AuditUnavailable

@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    risk: Risk
    validate: Callable
    execute: Callable
    public: bool = False
    legacy_allowed: bool = False
    retry_safe: bool = False

class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, definition):
        if definition.name in self._tools:
            raise ValueError("Duplicate tool name")
        self._tools[definition.name] = definition

    def get(self, name):
        try:
            return self._tools[name]
        except KeyError:
            raise ValueError("Unknown tool") from None

    def describe(self):
        return [{"name": t.name, "description": t.description, "risk": t.risk.name.lower(),
                 "retry_safe": t.retry_safe, "output": "ActionResult"} for t in self._tools.values()]

# Risk is conservative for raw controls: a click/keystroke can operate any active app.
DEFINITIONS = {
    "help": (Risk.LOW, "Show available commands"), "time": (Risk.LOW, "Read local time"),
    "date": (Risk.LOW, "Read local date"), "cancel": (Risk.LOW, "Cancel pending confirmation"),
    "stop_speaking": (Risk.LOW, "Interrupt speech"), "exit": (Risk.LOW, "Exit Jarvis"),
    "confirm": (Risk.HIGH, "Confirm the exact pending action"),
    "choose": (Risk.HIGH, "Select a resolved file or window"),
    "open": (Risk.HIGH, "Open a resolved application or path"), "find": (Risk.MEDIUM, "Search local filenames"),
    "close": (Risk.MEDIUM, "Request a window to close"), "windows": (Risk.MEDIUM, "List windows"),
    "system": (Risk.HIGH, "Power and media operations"), "window": (Risk.MEDIUM, "Arrange a window"),
    "keys": (Risk.HIGH, "Send a validated shortcut"), "mouse": (Risk.HIGH, "Move or click the pointer"),
    "grid": (Risk.HIGH, "Operate the pointer grid"), "volume": (Risk.LOW, "Set audio volume"),
    "click_control": (Risk.HIGH, "Click a named accessible control"),
    "file_action": (Risk.HIGH, "Create, copy, move, rename or recycle a local item"),
    "pause_listening": (Risk.LOW, "Pause microphone"), "interface": (Risk.LOW, "Show or hide Jarvis"),
    "web": (Risk.MEDIUM, "Open a web search URL"), "type": (Risk.HIGH, "Dictate into the selected app"),
    "reminder": (Risk.MEDIUM, "Create a reminder"), "list_reminders": (Risk.MEDIUM, "Read reminders"),
    "cancel_reminder": (Risk.MEDIUM, "Cancel a reminder"), "note": (Risk.MEDIUM, "Save a note"),
    "list_notes": (Risk.MEDIUM, "Read notes"), "language": (Risk.MEDIUM, "Change speech language"),
    "status": (Risk.LOW, "Read local system status"), "screenshot": (Risk.HIGH, "Capture displays"),
    "content": (Risk.MEDIUM, "Draft local text"), "chat": (Risk.MEDIUM, "Chat using local history"),
    "message": (Risk.HIGH, "Messaging unavailable"), "image": (Risk.MEDIUM, "Image generation unavailable"),
    "reindex": (Risk.MEDIUM, "Refresh filename index"),
}
OPTIONS = {
    "open": {"kind": str}, "find": {"kind": str}, "choose": {"index": int},
    "window": {"operation": str}, "keys": {"count": int},
    "mouse": {"amount": int, "direction": str, "x": int, "y": int},
    "grid": {"cell": int}, "file_action": {"operation": str, "destination": str},
    "web": {"engine": str},
}
REQUIRED = {"choose": {"index"}, "window": {"operation"}, "file_action": {"operation"}}
PUBLIC = {"help", "time", "date", "cancel", "stop_speaking", "pause_listening", "exit"}

def validate_command(command):
    if not isinstance(command, Command) or command.action not in DEFINITIONS:
        raise ValueError("Unknown command")
    if not isinstance(command.target, str) or len(command.target) > 12000 or "\x00" in command.target:
        raise ValueError("Invalid command target")
    if not isinstance(command.options, dict):
        raise ValueError("Invalid command options")
    allowed = OPTIONS.get(command.action, {})
    if set(command.options) - set(allowed) or REQUIRED.get(command.action, set()) - set(command.options):
        raise ValueError("Invalid or missing tool parameters")
    for key, value in command.options.items():
        if type(value) is not allowed[key]:
            raise ValueError("Invalid parameter type")
    action, target, options = command.action, command.target, command.options
    if action == "keys":
        from Backend.InputControls import key_codes
        key_codes(target)
        if not 1 <= options.get("count", 1) <= 20:
            raise ValueError("Repeat keys between 1 and 20 times")
    if action == "system" and target not in SYSTEM:
        raise ValueError("Unknown system action")
    if action == "file_action" and options["operation"] not in {"create_file", "create_folder", "copy", "move", "rename", "recycle"}:
        raise ValueError("Unknown file action")
    if action == "window" and options["operation"] not in {"focus", "minimize", "maximize", "restore", "snap left", "snap right"}:
        raise ValueError("Unknown window action")
    if action == "volume" and (not target.isdigit() or not 0 <= int(target) <= 100):
        raise ValueError("Volume must be between 0 and 100")
    if action == "choose" and options["index"] < 1:
        raise ValueError("Choose a positive result number")
    if action == "grid" and (target not in {"show", "hide", "zoom", "click", "double click", "right click"} or
                            (target not in {"show", "hide"} and not 1 <= options.get("cell", 0) <= 9)):
        raise ValueError("Invalid grid operation")
    if action == "mouse":
        if target not in {"move", "position", "center", "scroll", "click", "left click", "right click", "double click", "middle click"}:
            raise ValueError("Invalid mouse operation")
        if target in {"move", "scroll"} and (options.get("direction") not in {"up", "down", "left", "right"} or
            not 1 <= options.get("amount", 100 if target == "move" else 3) <= (2000 if target == "move" else 30)):
            raise ValueError("Invalid mouse distance or direction")
        if target == "position" and not {"x", "y"} <= options.keys():
            raise ValueError("Mouse position needs x and y")
    if action == "language" and target not in {"en", "ur", "auto"}:
        raise ValueError("Unknown language")
    if action == "interface" and target not in {"show", "hide"}:
        raise ValueError("Unknown interface action")
    if action == "cancel_reminder" and not target.isdigit():
        raise ValueError("Invalid reminder number")

def effective_risk(command, default):
    if command.action == "system" and command.target not in {"shutdown", "restart", "sleep", "lock"}:
        return Risk.LOW
    if command.action == "file_action" and command.options.get("operation") in {"create_file", "create_folder", "copy", "move", "rename"}:
        return Risk.MEDIUM
    return default

def builtin_registry(handler):
    registry = ToolRegistry()
    for name, (risk, description) in DEFINITIONS.items():
        registry.register(ToolDefinition(name, description, risk, validate_command, handler,
            public=name in PUBLIC, legacy_allowed=True))
    return registry

class ToolExecutor:
    def __init__(self, registry, security, audit, events):
        self.registry, self.security, self.audit, self.events = registry, security, audit, events

    def execute(self, command, context, token, task, history):
        step = TaskStep(command.action if command.action in DEFINITIONS else "unknown_tool")
        task.steps.append(step)
        metadata = dict(task_id=task.id, step_id=step.id, source=context.source, tool=step.tool)
        started = False
        try:
            token.check()
            definition = self.registry.get(command.action)
            definition.validate(command)
            risk = effective_risk(command, definition.risk)
            metadata["risk"] = risk.name.lower()
            decision = self.security.decide(definition.name, risk, context,
                public=definition.public, legacy_allowed=definition.legacy_allowed)
            self.audit.record(**metadata, outcome="allowed" if decision.allowed else "denied", code=decision.code)
            if not decision.allowed:
                raise PermissionDenied(decision.code)
            token.check()
            step.state = TaskState.RUNNING
            self.events.emit("task", task.to_dict())
            started = True
            result = definition.execute(command, history)
            if not isinstance(result, ActionResult):
                raise TypeError("Tool did not return ActionResult")
            token.check()
            step.state = TaskState.WAITING if result.action in {"confirmation", "choices"} else (TaskState.SUCCEEDED if result.success else TaskState.FAILED)
            step.verification = (result.data or {}).get("verification", "request_accepted" if result.success else "failed")
            step.error = result.error
        except (Cancelled, TaskTimeout) as exc:
            step.state = TaskState.CANCELLED if isinstance(exc, Cancelled) else TaskState.FAILED
            step.error = "cancelled" if isinstance(exc, Cancelled) else "timeout"
            result = ActionResult.fail(command.action, str(exc), error=step.error)
        except PermissionDenied:
            step.state, step.error = TaskState.FAILED, "permission_denied"
            result = ActionResult.fail(command.action, "This operation is not authorized.", error=step.error)
        except AuditUnavailable:
            step.state, step.error = TaskState.FAILED, "audit_unavailable"
            message = ("Audit unavailable; an attempted action may have completed. Verify it before retrying."
                       if started else "Audit unavailable; this action was not started.")
            return ActionResult.fail(command.action, message, error=step.error)
        except Exception as exc:
            step.state, step.error = TaskState.FAILED, type(exc).__name__
            result = ActionResult.fail(command.action, "Tool failed: " + str(exc), error=step.error)
        try:
            self.audit.record(**metadata, outcome=step.state.value, verification=step.verification, code=step.error or "")
        except AuditUnavailable:
            step.state, step.error = TaskState.FAILED, "audit_unavailable"
            return ActionResult.fail(command.action, "The result could not be audited. An attempted action may have completed; verify it before retrying.", error=step.error)
        return result
