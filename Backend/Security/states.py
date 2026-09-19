"""Security states for the presence state machine."""

from __future__ import annotations

from enum import Enum


class SecurityState(str, Enum):
    STARTING = "STARTING"
    NO_PERSON = "NO_PERSON"
    ABSENT = "NO_PERSON"  # legacy alias
    UNKNOWN_PERSON = "UNKNOWN_PERSON"
    AUTHORIZED = "AUTHORIZED"
    PROTECTION_PENDING = "PROTECTION_PENDING"
    PROTECTED = "PROTECTED"
    PROTECTING = "PROTECTED"  # legacy alias (no Windows lock in this phase)
    WARNING = "WARNING"  # reserved for later escalation
    LOCKED = "LOCKED"  # reserved; Windows lock is NOT implemented here
    CAMERA_ERROR = "CAMERA_ERROR"
    ERROR = "CAMERA_ERROR"  # legacy alias
