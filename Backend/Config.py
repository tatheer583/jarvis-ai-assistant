"""Local settings: no cloud credentials or automatic model downloads."""
from __future__ import annotations
import json
import os
import threading
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1

def data_directory() -> Path:
    override = os.environ.get("JARVIS_DATA_DIR")
    return Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "Jarvis"

@dataclass
class Settings:
    assistant_name: str = "Jarvis"
    owner_email: str = ""
    user_name: str = field(default_factory=lambda: os.environ.get("USERNAME", "User"))
    language: str = "auto"
    wake_word: str = "jarvis"
    require_wake_word: bool = True
    microphone_device: int | None = None
    vad_aggressiveness: int = 2
    minimum_speech_ms: int = 350
    silence_ms: int = 850
    speech_enabled: bool = True
    voice_provider: str = "windows"
    voice_id: str = ""
    voice_rate: int = 0
    voice_volume: int = 90
    voice_reference: str = ""
    voice_consent: bool = False
    voice_model_config: str = ""
    voice_python: str = ""
    voice_startup: bool = True
    whisper_path: str = ""
    llm_path: str = ""
    llm_threads: int = field(default_factory=lambda: max(1, min(4, (os.cpu_count() or 4) // 2)))
    search_roots: list[str] = field(default_factory=lambda: [str(Path.home())])
    aliases: dict[str, str] = field(default_factory=dict)
    close_to_tray: bool = True
    listen_on_startup: bool = True
    start_with_windows: bool = False
    web_search_engine: str = "google"
    audit_retention_days: int = 90

class Config:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or data_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "settings.json"
        self._lock = threading.RLock()
        self.settings = Settings()
        self.last_error = ""
        self._load_failed = False
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("Settings must be an object")
                version = raw.get("_schema_version", 0)
                if type(version) is not int or not 0 <= version <= SCHEMA_VERSION:
                    raise ValueError("Unsupported settings schema")
                known = asdict(self.settings)
                self.update({k: v for k, v in raw.items() if k in known}, persist=False)
            except (ValueError, TypeError, OSError, AttributeError) as exc:
                self._load_failed = True
                self.settings.listen_on_startup = False
                self.last_error = f"Settings could not be loaded; using defaults: {exc}"
        models = self.directory / "models"
        if not self.settings.whisper_path:
            self.settings.whisper_path = str(models / "whisper-base")
        if not self.settings.llm_path:
            self.settings.llm_path = str(models / "qwen2.5-1.5b-instruct-q4_k_m.gguf")

    def update(self, values: dict, *, persist: bool = True) -> None:
        with self._lock:
            if self._load_failed and persist:
                raise ValueError("Repair or restore the existing settings.json before saving.")
            if not isinstance(values, dict):
                raise ValueError("Settings must be an object")
            candidate = asdict(self.settings)
            for key, value in values.items():
                if key not in candidate:
                    raise ValueError(f"Unknown setting: {key}")
                if key == "microphone_device":
                    if value is not None and (type(value) is not int or value < 0):
                        raise ValueError("Invalid microphone device")
                elif type(value) is not type(candidate[key]):
                    raise ValueError(f"Invalid value for {key}")
                candidate[key] = value
            if candidate["language"] not in {"auto", "en", "ur"}:
                raise ValueError("Choose English, Urdu, or automatic language")
            if candidate["voice_provider"] not in {"windows", "pocket"}:
                raise ValueError("Unknown voice provider")
            for key in ("voice_reference", "voice_model_config", "voice_python"):
                value = candidate[key]
                if value and (not Path(value).is_absolute() or "\x00" in value or len(value) > 2048):
                    raise ValueError(f"{key} must be an absolute local path")
            if not 0 <= candidate["vad_aggressiveness"] <= 3:
                raise ValueError("Noise filtering must be between 0 and 3")
            if not -10 <= candidate["voice_rate"] <= 10 or not 0 <= candidate["voice_volume"] <= 100:
                raise ValueError("Invalid voice speed or volume")
            if not 150 <= candidate["minimum_speech_ms"] <= 2000 or not 300 <= candidate["silence_ms"] <= 3000:
                raise ValueError("Invalid speech timing")
            if not 1 <= candidate["llm_threads"] <= 32:
                raise ValueError("Invalid CPU thread count")
            if not all(isinstance(x, str) and x.strip() for x in candidate["search_roots"]):
                raise ValueError("Search folders must be valid paths")
            if not all(isinstance(k, str) and isinstance(v, str) for k, v in candidate["aliases"].items()):
                raise ValueError("Invalid file aliases")
            if not 1 <= candidate["audit_retention_days"] <= 3650:
                raise ValueError("Audit retention must be between 1 and 3650 days")
            for key in ("user_name", "assistant_name", "wake_word"):
                if not candidate[key].strip() or len(candidate[key]) > 100:
                    raise ValueError(f"Invalid value for {key}")
            if len(candidate["owner_email"]) > 160 or (candidate["owner_email"] and ("@" not in candidate["owner_email"] or " " in candidate["owner_email"])):
                raise ValueError("Invalid owner email")
            if candidate["web_search_engine"] not in {"duckduckgo", "google", "youtube"}:
                raise ValueError("Unknown search engine")
            if persist:
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory,
                                                     prefix="settings-", suffix=".tmp", delete=False) as file:
                        temporary = Path(file.name)
                        json.dump({"_schema_version": SCHEMA_VERSION, **candidate}, file, ensure_ascii=False, indent=2)
                        file.flush()
                        os.fsync(file.fileno())
                    temporary.replace(self.path)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            self.settings = Settings(**candidate)

    @property
    def database(self) -> Path:
        return self.directory / "jarvis.sqlite3"
