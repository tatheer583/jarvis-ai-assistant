"""Local event bus. Subscriber failures cannot stop execution."""
from dataclasses import dataclass
from typing import Any
import logging
import threading

@dataclass(frozen=True)
class Event:
    name: str
    data: Any

class EventBus:
    def __init__(self):
        self._lock = threading.Lock()
        self._listeners = []

    def subscribe(self, callback):
        with self._lock:
            self._listeners.append(callback)
        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def emit(self, name, data):
        with self._lock:
            listeners = list(self._listeners)
        for callback in listeners:
            try:
                callback(Event(name, data))
            except Exception:
                logging.getLogger("Jarvis.Events").warning("Event subscriber failed")
