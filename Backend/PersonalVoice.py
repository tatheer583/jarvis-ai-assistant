"""Private speech-synthesis references, separate from owner authentication."""
from __future__ import annotations

import os
import tempfile
import threading
import wave
from pathlib import Path

from Backend.Audit import protect_directory


def voice_directory(config):
    return config.directory / "voice"


def prepare_directory(config):
    root = voice_directory(config)
    root.mkdir(parents=True, exist_ok=True)
    protect_directory(root)
    for name in ("recordings", "model", "config"):
        (root / name).mkdir(exist_ok=True)
    return root


def validate_reference(path):
    path = Path(path)
    if str(path).startswith(('\\\\', '//')):
        raise ValueError("Use a recording on this computer, not a network share.")
    if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Choose a local WAV recording smaller than 10 MB.")
    try:
        with wave.open(str(path), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
            if (audio.getcomptype() != "NONE" or audio.getsampwidth() != 2
                    or audio.getnchannels() not in (1, 2) or not 3 <= seconds <= 30):
                raise ValueError("Use a 3–30 second, 16-bit PCM WAV recording.")
    except (wave.Error, EOFError, ZeroDivisionError) as exc:
        raise ValueError("The recording is not a supported PCM WAV file.") from exc
    return path


def import_reference(config, path, *, consent=False):
    if consent is not True:
        raise ValueError("Confirm that this is your voice and that you allow local voice synthesis.")
    source = validate_reference(path)
    root = prepare_directory(config)
    target = root / "recordings" / "reference.wav"
    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".wav", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(source.read_bytes())
    try:
        temporary.replace(target)
        config.update({"voice_reference": str(target), "voice_consent": True})
    finally:
        temporary.unlink(missing_ok=True)


def record_reference(config, cancelled: threading.Event, *, consent=False, progress=lambda _: None):
    if consent is not True:
        raise ValueError("Confirm consent before recording your voice.")
    import numpy as np
    import sounddevice as sd
    root = prepare_directory(config)
    chunks = []
    rate = 16000
    # Small reads keep cancellation bounded; this does not share the STT stream.
    with sd.InputStream(samplerate=rate, channels=1, dtype="int16",
                        device=config.settings.microphone_device) as stream:
        for index in range(80):
            if cancelled.is_set():
                raise InterruptedError("Recording cancelled.")
            chunk, overflowed = stream.read(rate // 10)
            if overflowed:
                raise RuntimeError("Audio was interrupted; please record again.")
            chunks.append(chunk.copy())
            if index % 10 == 0:
                progress(f"Recording your voice: {index // 10 + 1}/8 seconds")
    audio = np.concatenate(chunks).reshape(-1)
    if cancelled.is_set():
        raise InterruptedError("Recording cancelled.")
    if float(np.sqrt(np.mean((audio.astype(np.float32) / 32768) ** 2))) < 0.005:
        raise ValueError("The recording is too quiet. Move closer and try again.")
    with tempfile.NamedTemporaryFile(dir=root / "recordings", suffix=".wav", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(audio.tobytes())
        if cancelled.is_set():
            raise InterruptedError("Recording cancelled.")
        import_reference(config, temporary, consent=True)
    finally:
        temporary.unlink(missing_ok=True)


def delete_reference(config):
    # Delete only our managed recording. Never delete an arbitrary configured path.
    target = voice_directory(config) / "recordings" / "reference.wav"
    target.unlink(missing_ok=True)
    config.update({"voice_reference": "", "voice_consent": False, "voice_provider": "windows"})


def worker_python(config):
    import sys
    if config.settings.voice_python:
        return Path(config.settings.voice_python)
    if not getattr(sys, "frozen", False):
        return Path(sys.executable)
    return Path(os.environ.get("LOCALAPPDATA", "")) / "Jarvis/runtime/Scripts/python.exe"


def status(config):
    cfg = config.settings
    return {"engine": cfg.voice_provider, "consent": cfg.voice_consent,
            "reference_ready": bool(cfg.voice_consent and cfg.voice_reference and Path(cfg.voice_reference).is_file()),
            "runtime_available": worker_python(config).is_file(),
            "model_configured": bool(cfg.voice_model_config and Path(cfg.voice_model_config).is_file()),
            "model_state": "not_loaded", "online": False}
