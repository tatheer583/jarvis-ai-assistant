"""Read-only setup diagnostics; never opens a microphone or camera."""
from __future__ import annotations
import importlib.util
import os
import platform
import shutil
from pathlib import Path

def diagnose(config):
    from Backend.VoiceOutput import installed_voices
    names = ("PyQt5", "sounddevice", "webrtcvad", "faster_whisper", "llama_cpp", "win32gui", "pycaw")
    modules = {name: importlib.util.find_spec(name) is not None for name in names}
    return {
        "edition": "Jarvis Local Desktop",
        "python": platform.python_version(),
        "data_directory": str(config.directory),
        "cloud_ai": False,
        "modules": modules,
        "speech_model": (Path(config.settings.whisper_path) / "model.bin").is_file(),
        "chat_model": Path(config.settings.llm_path).is_file(),
        "personal_voice_engine": importlib.util.find_spec("pocket_tts") is not None,
        "personal_voice_recording": bool(config.settings.voice_reference and Path(config.settings.voice_reference).is_file()),
        "installed_windows_voices": [v["name"] for v in installed_voices()],
        "free_disk_gb": round(shutil.disk_usage(config.directory).free / 1024**3, 1),
        "microphone_enabled_at_startup": config.settings.listen_on_startup,
    }
