"""Compatibility functions use the same permission/confirmation path as the UI."""
import asyncio
from Backend.ActionResult import ActionResult
from Backend.Config import Config
from Backend.Services import Services

DANGEROUS_COMMANDS = frozenset({"shutdown", "restart", "sleep", "lock"})
_services = None

def _service():
    global _services
    if _services is None:
        _services = Services(Config())
    return _services

def OpenApp(app):
    return _service().execute("open " + app, source="compatibility")

def CloseApp(app):
    return _service().execute("close " + app, source="compatibility")

def System(command, *, confirmed=False):
    service = _service()
    if confirmed:
        pending = service.assistant.pending
        if not pending or pending.get("action") != "system" or pending.get("target") != command:
            return ActionResult.fail("confirm", "Request this action first, then confirm the pending operation.")
        return service.execute("yes", source="compatibility")
    return service.execute("system " + command, source="compatibility")

def CancelShutdown():
    return System("cancel shutdown")

async def Automation(commands):
    service = _service()
    results = []
    for command in commands:
        if command.startswith(("general ", "realtime ")):
            continue
        result = await asyncio.to_thread(service.execute, command, source="compatibility")
        results.append(result)
        if service.assistant.pending or result.error in {"cancelled", "permission_denied", "audit_unavailable"}:
            break
    return ActionResult(all(r.success for r in results), "automation",
                        "\n".join(r.message for r in results) or "No commands to execute.")

async def TranslateAndExecute(commands):
    return [await Automation(commands)]
