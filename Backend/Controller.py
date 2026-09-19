"""Qt signals adapt the same local service used by Tauri."""
from PyQt5.QtCore import QObject, pyqtSignal
from Backend.EngineService import EngineService

class Controller(QObject):
    message = pyqtSignal(str, str)
    result = pyqtSignal(object)
    status = pyqtSignal(str)
    level = pyqtSignal(int)
    busy_changed = pyqtSignal(bool)
    mic_changed = pyqtSignal(bool)
    index_changed = pyqtSignal(str)
    notification = pyqtSignal(str)
    quit_requested = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.runtime = EngineService(config, self._event)
        self.config = config
        self.assistant = self.runtime.assistant
        self.services = self.runtime.services
        self.speaker = self.runtime.speaker
        self.voice = self.runtime.voice
        self.busy = self.runtime.busy
        self.closed = self.runtime.closed
        self.runtime.handle({"op": "connect"})

    def _event(self, name, data):
        if name == "message":
            self.message.emit(data["role"], data["content"])
        elif name == "result":
            from Backend.ActionResult import ActionResult
            self.result.emit(ActionResult(data["success"], data["action"], data["message"], data.get("data"), data.get("error")))
        elif name == "status":
            self.status.emit(str(data))
        elif name == "level":
            self.level.emit(int(data))
        elif name == "busy":
            self.busy_changed.emit(bool(data))
        elif name == "listening":
            self.mic_changed.emit(bool(data))
        elif name == "notification":
            self.notification.emit(str(data))
        elif name == "index":
            text = "Indexing your folders..." if data.get("indexing") else f"{data.get('index_count', 0):,} files and folders indexed"
            self.index_changed.emit(text)
        elif name == "quit":
            self.quit_requested.emit()

    def submit(self, text, source="qt"):
        return self.runtime.submit(text, source)

    def refresh_index(self):
        self.runtime.refresh_index()

    def stop(self):
        self.runtime.stop(pause=True)

    def close(self):
        self.runtime.close()
