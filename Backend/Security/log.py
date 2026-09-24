"""Local security event logging — no frames, no biometrics."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("Jarvis.Security")

_lock = threading.Lock()


def ensure_security_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def log_security_event(
    log_path: Path,
    *,
    event: str,
    state_from: str | None = None,
    state_to: str | None = None,
    reason: str = "",
    **extra: object,
) -> None:
    """Append one JSON line. Never include images or embedding payloads."""
    blocked = {"frame", "image", "embedding", "template", "pixels", "raw"}
    clean_extra = {k: v for k, v in extra.items() if k.lower() not in blocked}
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "state_from": state_from,
        "state_to": state_to,
        "reason": reason,
        **clean_extra,
    }
    ensure_security_dir(log_path)
    line = json.dumps(record, ensure_ascii=False)
    with _lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    log.info("security event: %s", line)
