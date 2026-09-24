"""Task contracts and cooperative cancellation; no generated-code execution."""
from dataclasses import dataclass, field, asdict
from enum import Enum
import threading
import time
import uuid

class Cancelled(RuntimeError):
    pass

class TaskTimeout(RuntimeError):
    pass

class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting_confirmation"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

class CancellationToken:
    def __init__(self, timeout=None):
        self.event = threading.Event()
        self.deadline = time.monotonic() + timeout if timeout is not None else None

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set():
            raise Cancelled("Stop requested. Any completed actions remain applied.")
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TaskTimeout("Deadline exceeded. Check the action result before retrying.")

@dataclass
class TaskStep:
    tool: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: TaskState = TaskState.QUEUED
    verification: str = "not_checked"
    error: str | None = None

@dataclass
class Task:
    source: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: TaskState = TaskState.QUEUED
    steps: list[TaskStep] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def to_dict(self):
        # No request text, paths or result content.
        return asdict(self)

from contextvars import ContextVar
from contextlib import contextmanager
_current_token = ContextVar("jarvis_cancellation", default=None)

def checkpoint():
    token = _current_token.get()
    if token is not None:
        token.check()

@contextmanager
def cancellation_scope(token):
    marker = _current_token.set(token)
    try:
        yield
    finally:
        _current_token.reset(marker)

def is_cancelled():
    token = _current_token.get()
    return token is not None and token.event.is_set()
