from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionResult:
    """Structured result returned by every executable action in Jarvis.

    Use the factory helpers ``ActionResult.ok()`` and ``ActionResult.fail()``
    for convenience.  The instance is immutable once created.
    """

    success: bool
    action: str
    message: str
    data: dict[str, Any] | None = field(default=None)
    error: str | None = field(default=None)

    # -- Factories ----------------------------------------------------------

    @staticmethod
    def ok(action: str, message: str, **data: Any) -> ActionResult:
        return ActionResult(
            success=True, action=action, message=message,
            data=data if data else None,
        )

    @staticmethod
    def fail(action: str, message: str, *, error: str | None = None) -> ActionResult:
        return ActionResult(
            success=False, action=action, message=message, error=error,
        )

    @staticmethod
    def not_implemented(action: str) -> ActionResult:
        return ActionResult(
            success=False, action=action,
            message=f"The '{action}' feature is not implemented yet.",
            error="not_implemented",
        )

    # -- Helpers ------------------------------------------------------------

    def __bool__(self) -> bool:
        return self.success

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON responses (used by RemoteAccess)."""
        d: dict[str, Any] = {
            "success": self.success,
            "action": self.action,
            "message": self.message,
        }
        if self.data:
            d["data"] = self.data
        if self.error:
            d["error"] = self.error
        return d
