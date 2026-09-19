"""Thread-safe ChatLog.json read/write helpers shared by Main, Chatbot, and Search."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

log = logging.getLogger("Jarvis.ChatLog")

BASE_DIR = Path(__file__).resolve().parent.parent
CHAT_LOG_PATH = BASE_DIR / "Data" / "ChatLog.json"
MAX_MESSAGES = 100

_lock = threading.Lock()


def _ensure_file() -> None:
    CHAT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CHAT_LOG_PATH.exists():
        CHAT_LOG_PATH.write_text("[]", encoding="utf-8")


def read_chat_log() -> list[dict]:
    with _lock:
        _ensure_file()
        try:
            with open(CHAT_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (FileNotFoundError, json.JSONDecodeError) as e:
            log.warning("ChatLog read failed, resetting: %s", e)
        return []


def write_chat_log(messages: list[dict]) -> list[dict]:
    trimmed = messages[-MAX_MESSAGES:]
    with _lock:
        _ensure_file()
        CHAT_LOG_PATH.write_text(
            json.dumps(trimmed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return trimmed


def append_messages(*entries: dict) -> list[dict]:
    """Append one or more {role, content} dicts and persist."""
    cleaned: list[dict] = []
    for entry in entries:
        role = str(entry.get("role", "")).strip()
        content = str(entry.get("content", "")).strip()
        if role and content:
            cleaned.append({"role": role, "content": content})
    if not cleaned:
        return read_chat_log()

    with _lock:
        _ensure_file()
        try:
            with open(CHAT_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except (FileNotFoundError, json.JSONDecodeError):
            data = []
        data.extend(cleaned)
        trimmed = data[-MAX_MESSAGES:]
        CHAT_LOG_PATH.write_text(
            json.dumps(trimmed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return trimmed
