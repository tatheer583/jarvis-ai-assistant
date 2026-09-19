"""Provider contracts. Production registers only the existing local model."""
from typing import Protocol
from Backend.LocalBrain import LocalBrain, ModelUnavailable
from Backend.Tasks import checkpoint, Cancelled, TaskTimeout

class AIProvider(Protocol):
    name: str
    online: bool
    def ready(self) -> bool: ...
    def reply(self, text: str, history: list[dict] | None = None, *, on_delta=None) -> str: ...
    def stop(self) -> None: ...

class LocalProvider:
    name = "local"
    online = False

    def __init__(self, config):
        self.brain = LocalBrain(config)

    def ready(self):
        return self.brain.ready()

    def reply(self, text, history=None, *, on_delta=None):
        return self.brain.reply(text, history, on_delta=on_delta)

    def stop(self):
        self.brain.stop()

class AIOrchestrator:
    def __init__(self, local, *, online=None, online_enabled=False, events=None):
        self.local, self.online = local, online
        self.online_enabled, self.events = online_enabled, events
        self.active_provider = "local"

    def ready(self):
        return self.local.ready()

    def _announce(self, name, reason=None):
        self.active_provider = name
        if self.events:
            self.events.emit("provider", {"name": name, "online": name == "online", "reason": reason})

    def reply(self, text, history=None, *, on_delta=None):
        checkpoint()
        if self.online_enabled and self.online is not None:
            try:
                if self.online.ready():
                    self._announce("online")
                    answer = self.online.reply(text, history)
                    checkpoint()
                    if not isinstance(answer, str) or not answer.strip():
                        raise ModelUnavailable("Provider returned no text")
                    # Online providers stay buffered until success, so fallback cannot
                    # mix a partial online answer into the local response.
                    if on_delta:
                        on_delta(answer)
                    return answer
            except (Cancelled, TaskTimeout):
                raise
            except Exception:
                # Exceptions may include credentials; never relay their text to logs or UI.
                self._announce("local", "online_unavailable")
        checkpoint()
        self._announce("local")
        answer = (self.local.reply(text, history, on_delta=on_delta) if on_delta
                  else self.local.reply(text, history))
        checkpoint()
        return answer

    def stop(self):
        self.local.stop()
        if self.online is not None:
            self.online.stop()
