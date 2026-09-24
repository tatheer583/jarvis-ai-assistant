"""Shared assistant status file IPC (Frontend/Files/Status.data)."""

from __future__ import annotations

import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATUS_PATH = BASE_DIR / "Frontend" / "Files" / "Status.data"


def SetAssistantStatus(status: str) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        try:
            STATUS_PATH.write_text(str(status), encoding="utf-8")
            return
        except PermissionError:
            time.sleep(0.05)
        except Exception:
            return


def GetAssistantStatus() -> str:
    try:
        return STATUS_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "Available..."
