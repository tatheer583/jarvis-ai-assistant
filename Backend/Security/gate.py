"""Central security decision helpers for command gating.

Expand sensitive prefixes here later without touching every automation path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from Backend.Security.service import PresenceService

# Commands that must be denied when state is UNKNOWN_PERSON / PROTECTED / etc.
SENSITIVE_COMMAND_PREFIXES: tuple[str, ...] = (
    "system ",
    "open ",
    "close ",
    "play ",
    "content ",
    "google search ",
    "youtube search ",
    "send message ",
    "whatsapp ",
    "reminder ",
    "generate image ",
    "image generation ",
)


def is_sensitive_command(command: str | None) -> bool:
    if not command:
        return True  # unknown payload treated as sensitive when gating
    normalized = command.strip().lower()
    return any(normalized.startswith(prefix) for prefix in SENSITIVE_COMMAND_PREFIXES)


def is_command_allowed(service: Any | None, command: str | None = None) -> bool:
    """Return whether Jarvis may execute a command under the current security state."""
    if service is None:
        return True
    checker = getattr(service, "is_command_allowed", None)
    if callable(checker):
        return bool(checker(command))
    allows = getattr(service, "allows_commands", None)
    if callable(allows):
        return bool(allows())
    return True
