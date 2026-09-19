"""Central permissions. Legacy local control is explicitly not authentication."""
from dataclasses import dataclass, field
from enum import IntEnum
import copy
import threading
import time
import uuid

class Risk(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

@dataclass(frozen=True)
class Principal:
    id: str = "local-session"
    authenticated: bool = False
    strong_until: float = 0
    scopes: frozenset[str] = field(default_factory=frozenset)

@dataclass(frozen=True)
class ExecutionContext:
    session_id: str
    source: str = "typed"
    principal: Principal = field(default_factory=Principal)
    legacy_local: bool = False

@dataclass(frozen=True)
class Decision:
    allowed: bool
    code: str
    risk: Risk

class PermissionDenied(RuntimeError):
    pass

class SecurityManager:
    def __init__(self):
        self._pending = None
        self._lock = threading.RLock()

    @property
    def pending(self):
        return self._pending

    @pending.setter
    def pending(self, value):
        with self._lock:
            self._pending = value

    def decide(self, tool, risk, context, *, public=False, legacy_allowed=False):
        if context.legacy_local and legacy_allowed and context.source in {"typed", "voice", "cli", "qt", "compatibility"}:
            return Decision(True, "legacy_local", risk)
        principal = context.principal
        if public and risk == Risk.LOW:
            return Decision(True, "public", risk)
        if not principal.authenticated:
            return Decision(False, "authentication_required", risk)
        if tool not in principal.scopes:
            return Decision(False, "permission_denied", risk)
        if risk == Risk.HIGH and principal.strong_until <= time.monotonic():
            return Decision(False, "strong_authentication_required", risk)
        return Decision(True, "authorized", risk)

    def require(self, tool, risk, context, **kwargs):
        decision = self.decide(tool, risk, context, **kwargs)
        if not decision.allowed:
            raise PermissionDenied(decision.code)
        return decision

    def challenge(self, payload, context, ttl=30):
        with self._lock:
            self._pending = {**copy.deepcopy(payload), "kind": "confirmation",
                             "session_id": context.session_id, "principal_id": context.principal.id,
                             "request_id": uuid.uuid4().hex, "expires": time.monotonic() + ttl}
            return self._pending["request_id"]

    def consume(self, context):
        with self._lock:
            pending = self._pending
            if not pending or pending.get("kind") != "confirmation":
                raise PermissionDenied("no_pending_confirmation")
            if pending.get("session_id") != context.session_id or pending.get("principal_id") != context.principal.id:
                raise PermissionDenied("confirmation_session_mismatch")
            self._pending = None
            if pending["expires"] <= time.monotonic():
                raise PermissionDenied("confirmation_expired")
            return copy.deepcopy(pending)

    def clear(self):
        self.pending = None

    def snapshot(self):
        return {"mode": "legacy_local", "owner_authenticated": False,
                "strong_authentication_available": False,
                "description": "Local control with confirmation. Owner authentication is not configured."}
