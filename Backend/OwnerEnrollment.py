"""Local owner enrollment: salted PIN plus real webcam/microphone capture."""
from __future__ import annotations
import base64, hashlib, json, secrets, wave
from pathlib import Path
from typing import Callable
from Backend.Config import Config
from Backend.Security.config import load_security_config

Progress = Callable[[str], None]
ITERATIONS = 310_000

def _dir(config: Config) -> Path:
    path = config.directory / "owner-security"; path.mkdir(parents=True, exist_ok=True); return path
def _pin(config: Config) -> Path: return _dir(config) / "pin.json"
def pin_configured(config: Config) -> bool: return _pin(config).is_file()
def set_pin(config: Config, value: str) -> None:
    if not isinstance(value, str) or not 4 <= len(value) <= 128: raise ValueError("PIN/password must contain 4 to 128 characters")
    salt = secrets.token_bytes(16); digest = hashlib.pbkdf2_hmac("sha256", value.encode(), salt, ITERATIONS)
    path = _pin(config); tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"algorithm":"pbkdf2_sha256","iterations":ITERATIONS,"salt":base64.b64encode(salt).decode(),"digest":base64.b64encode(digest).decode()}), encoding="utf-8"); tmp.replace(path)
def verify_pin(config: Config, value: str) -> bool:
    try:
        data=json.loads(_pin(config).read_text(encoding="utf-8")); actual=hashlib.pbkdf2_hmac("sha256", str(value).encode(), base64.b64decode(data["salt"]), int(data["iterations"]))
        return secrets.compare_digest(actual, base64.b64decode(data["digest"]))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError): return False
def delete_pin(config: Config) -> bool:
    path=_pin(config)
    if not path.exists(): return False
    path.unlink(); return True
def voice_samples(config: Config) -> list[str]: return sorted(str(p) for p in (_dir(config)/"voice").glob("sample-*.wav"))
def record_voice_samples(config: Config, *, samples: int=3, seconds: int=4, device: int|None=None, progress: Progress|None=None) -> list[str]:
    if not 2 <= samples <= 8 or not 2 <= seconds <= 10: raise ValueError("Voice enrollment supports 2-8 samples of 2-10 seconds")
    try:
        import numpy as np, sounddevice as sd
    except ImportError as exc: raise RuntimeError("Local microphone enrollment needs sounddevice and numpy") from exc
    folder=_dir(config)/"voice"; folder.mkdir(exist_ok=True); paths=[]; rate=16000
    for i in range(samples):
        if progress: progress(f"Recording voice sample {i+1}/{samples}…")
        recording=sd.rec(int(seconds*rate), samplerate=rate, channels=1, dtype="float32", device=device); sd.wait()
        if float(np.max(np.abs(recording))) < .01: raise RuntimeError("Microphone captured silence; please try again")
        path=folder/f"sample-{i+1}.wav"; pcm=(np.clip(np.asarray(recording).reshape(-1),-1,1)*32767).astype(np.int16)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate); output.writeframes(pcm.tobytes())
        paths.append(str(path))
    config.update({"voice_reference": paths[0]});
    if progress: progress("Voice enrollment completed successfully.")
    return paths
def face_status(config: Config) -> tuple[bool,str]:
    path=load_security_config().owner_template_path
    if path.is_file(): return True, "Face enrolled locally"
    try: import cv2  # noqa: F401
    except ImportError: return False, "Face enrollment unavailable: install optional OpenCV"
    return False, "Face not enrolled"
def enroll_face_camera(config: Config, *, samples: int=8, camera: int|None=None, replace: bool=True, progress: Progress|None=None) -> str:
    from Backend.Security.enrollment import enroll_owner_from_camera
    return str(enroll_owner_from_camera(samples=samples, camera_index=camera, replace=replace, progress=progress))
def enroll_face_images(config: Config, paths: list[str], *, replace: bool=True, progress: Progress|None=None) -> str:
    from Backend.Security.enrollment import enroll_owner_from_images
    return str(enroll_owner_from_images([Path(p) for p in paths], replace=replace, progress=progress))
def delete_face(config: Config) -> bool:
    from Backend.Security.enrollment import reset_owner_enrollment
    return reset_owner_enrollment()
def delete_voice(config: Config) -> int:
    removed=0
    for path in (_dir(config)/"voice").glob("sample-*.wav"): path.unlink(missing_ok=True); removed+=1
    if config.settings.voice_reference: config.update({"voice_reference":""})
    return removed
def status(config: Config) -> dict:
    face, face_message=face_status(config); voices=voice_samples(config)
    try:
        import sounddevice as sd; mic=bool(sd.query_devices()); mic_message="Microphone available" if mic else "No microphone detected"
    except Exception: mic=False; mic_message="Microphone enrollment unavailable: install sounddevice"
    pin=pin_configured(config); overall=bool(face and voices and pin)
    return {"face_enrolled":face,"face_message":face_message,"camera_available":"OpenCV" not in face_message,"voice_enrolled":bool(voices),"voice_samples":len(voices),"microphone_available":mic,"microphone_message":mic_message,"pin_configured":pin,"overall":overall,"overall_message":"Owner authentication configured" if overall else "Owner authentication not configured","owner_name":config.settings.user_name,"assistant_name":config.settings.assistant_name,"owner_email":config.settings.owner_email}
