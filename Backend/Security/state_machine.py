"""Explicit table-driven security state machine."""

from __future__ import annotations

from dataclasses import dataclass

from Backend.Security.states import SecurityState

ALLOWED_TRANSITIONS: dict[SecurityState, frozenset[SecurityState]] = {
    SecurityState.STARTING: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.UNKNOWN_PERSON,
        SecurityState.NO_PERSON,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.AUTHORIZED: frozenset({
        SecurityState.NO_PERSON,
        SecurityState.UNKNOWN_PERSON,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.UNKNOWN_PERSON: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.NO_PERSON,
        SecurityState.WARNING,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.NO_PERSON: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.UNKNOWN_PERSON,
        SecurityState.PROTECTION_PENDING,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.PROTECTION_PENDING: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.UNKNOWN_PERSON,
        SecurityState.PROTECTED,
        SecurityState.WARNING,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.WARNING: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.PROTECTED,
        SecurityState.PROTECTION_PENDING,
        SecurityState.NO_PERSON,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.PROTECTED: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.UNKNOWN_PERSON,
        SecurityState.NO_PERSON,
        SecurityState.LOCKED,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.LOCKED: frozenset({
        SecurityState.AUTHORIZED,
        SecurityState.UNKNOWN_PERSON,
        SecurityState.CAMERA_ERROR,
    }),
    SecurityState.CAMERA_ERROR: frozenset({
        SecurityState.STARTING,
        SecurityState.NO_PERSON,
        SecurityState.CAMERA_ERROR,
    }),
}


class InvalidTransition(Exception):
    """Raised when a transition is not in the allow-list."""


@dataclass(frozen=True)
class TransitionResult:
    previous: SecurityState
    current: SecurityState
    reason: str
    changed: bool


class SecurityStateMachine:
    def __init__(self, initial: SecurityState = SecurityState.STARTING) -> None:
        self._state = initial

    @property
    def state(self) -> SecurityState:
        return self._state

    def can_transition(self, target: SecurityState) -> bool:
        if target == self._state:
            return True
        return target in ALLOWED_TRANSITIONS.get(self._state, frozenset())

    def transition(self, target: SecurityState, reason: str = "") -> TransitionResult:
        previous = self._state
        if target == previous:
            return TransitionResult(previous, previous, reason or "noop", False)
        allowed = ALLOWED_TRANSITIONS.get(previous, frozenset())
        if target not in allowed:
            raise InvalidTransition(f"{previous.value} -> {target.value} not allowed")
        self._state = target
        return TransitionResult(previous, target, reason or "transition", True)

    def force(self, target: SecurityState, reason: str = "force") -> TransitionResult:
        """Emergency/test helper — bypasses the table (logged by caller)."""
        previous = self._state
        self._state = target
        return TransitionResult(previous, target, reason, previous != target)
