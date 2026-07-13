import asyncio
import logging
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import edge_tts
import pygame
import requests
from dotenv import dotenv_values

log = logging.getLogger("Jarvis.TTS")

# ---------------------------------------------------------------------------
# Global interruption controls
# ---------------------------------------------------------------------------
_stop_event = threading.Event()
_tts_process: subprocess.Popen | None = None
_tts_thread: threading.Thread | None = None

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "Data"
TEMP_DIR = BASE_DIR / "Frontend" / "Files"
SPEECH_FILE_PATH = DATA_DIR / "speech.mp3"

DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
env_vars = dotenv_values(str(ENV_PATH))
TTSProvider = (env_vars.get("TTSProvider") or "auto").strip().lower()
AssistantVoice = (env_vars.get("AssistantVoice") or "en-US-AriaNeural").strip()
AssistantVoiceID = (
    env_vars.get("AssistantVoiceID")
    or env_vars.get("AssistantVoiceId")
    or env_vars.get("ElevenLabsVoiceID")
    or ""
).strip()
ElevenLabsAPIKey = (env_vars.get("ElevenLabsAPIKey") or "").strip()
ElevenLabsModelID = (env_vars.get("ElevenLabsModelID") or "eleven_multilingual_v2").strip()

LONG_TEXT_SENTENCE_LIMIT = 4
LONG_TEXT_CHARACTER_LIMIT = 250

LONG_TEXT_RESPONSES = [
    "The rest is available on the chat screen, sir.",
    "Please check the chat screen for the remaining details, sir.",
    "I have spoken the main part. The rest is on the chat screen, sir.",
    "The remaining answer is on the chat screen for you, sir.",
    "Please see the chat screen for the complete response, sir.",
]
WINDOWS_TTS_PROVIDERS = {"windows", "native", "sapi"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def SetAssistantStatus(status: str) -> None:
    for _ in range(3):
        try:
            with open(TEMP_DIR / "Status.data", "w", encoding="utf-8") as file:
                file.write(status)
            return
        except PermissionError:
            time.sleep(0.05)


def _ensure_mixer_initialized() -> None:
    if not pygame.mixer.get_init():
        pygame.mixer.init()


def _cleanup_audio() -> None:
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            try:
                pygame.mixer.music.unload()
            except (AttributeError, pygame.error):
                pass
    except Exception:
        pass


def _console_fallback(text: str) -> None:
    print(text)


def _speak_with_windows_tts(text: str) -> bool:
    global _tts_process
    if not sys.platform.startswith("win"):
        return False

    escaped_text = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Rate = 1; "
        "$speaker.Volume = 100; "
        f"$speaker.Speak('{escaped_text}')"
    )
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
    )
    _tts_process = proc

    while proc.poll() is None:
        if _stop_event.is_set():
            log.info("Speech interrupted (Windows TTS)")
            proc.kill()
            proc.wait()
            _tts_process = None
            return False
        time.sleep(0.05)

    _tts_process = None
    return proc.returncode == 0


def _should_use_elevenlabs() -> bool:
    if TTSProvider in WINDOWS_TTS_PROVIDERS:
        return False
    if TTSProvider == "elevenlabs":
        return bool(ElevenLabsAPIKey and AssistantVoiceID)
    if TTSProvider == "edge":
        return False
    return bool(ElevenLabsAPIKey and AssistantVoiceID)


def _shorten_text_for_voice(text: str) -> str:
    cleaned_text = " ".join(str(text).split()).strip()
    if not cleaned_text:
        return ""

    sentences = [sentence.strip() for sentence in cleaned_text.split(".") if sentence.strip()]
    if len(sentences) > LONG_TEXT_SENTENCE_LIMIT and len(cleaned_text) >= LONG_TEXT_CHARACTER_LIMIT:
        spoken_preview = ". ".join(sentences[:2]).strip()
        if spoken_preview and not spoken_preview.endswith("."):
            spoken_preview += "."
        return f"{spoken_preview} {random.choice(LONG_TEXT_RESPONSES)}".strip()

    return cleaned_text


async def TextToAudioFile(text: str) -> None:
    if SPEECH_FILE_PATH.exists():
        SPEECH_FILE_PATH.unlink()

    communicate = edge_tts.Communicate(
        text=text,
        voice=AssistantVoice,
        pitch="+5Hz",
        rate="+13%",
    )
    await communicate.save(str(SPEECH_FILE_PATH))


def TextToAudioFileElevenLabs(text: str) -> None:
    if SPEECH_FILE_PATH.exists():
        SPEECH_FILE_PATH.unlink()

    response = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{AssistantVoiceID}",
        headers={
            "xi-api-key": ElevenLabsAPIKey,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        json={
            "text": text,
            "model_id": ElevenLabsModelID,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    SPEECH_FILE_PATH.write_bytes(response.content)


def _play_audio_file(func=lambda r=None: True) -> bool:
    _ensure_mixer_initialized()
    pygame.mixer.music.load(str(SPEECH_FILE_PATH))
    pygame.mixer.music.play()

    started = False
    for _ in range(20):
        if _stop_event.is_set():
            pygame.mixer.music.stop()
            log.info("Speech interrupted (audio playback)")
            return False
        if pygame.mixer.music.get_busy():
            started = True
            break
        time.sleep(0.05)

    if not started:
        raise RuntimeError("Audio playback did not start.")

    clock = pygame.time.Clock()
    while pygame.mixer.music.get_busy():
        if _stop_event.is_set():
            pygame.mixer.music.stop()
            log.info("Speech interrupted (audio playback)")
            return False
        if func(False) is False:
            pygame.mixer.music.stop()
            break
        clock.tick(20)

    return True


def TTS(text: str, func=lambda r=None: True) -> bool:
    cleaned_text = _shorten_text_for_voice(text)
    if not cleaned_text:
        return False

    try:
        SetAssistantStatus("Speaking...")

        if _stop_event.is_set():
            return False

        if TTSProvider in WINDOWS_TTS_PROVIDERS:
            return _speak_with_windows_tts(cleaned_text)

        if _stop_event.is_set():
            return False

        if _should_use_elevenlabs():
            TextToAudioFileElevenLabs(cleaned_text)
        else:
            asyncio.run(TextToAudioFile(cleaned_text))

        if _stop_event.is_set():
            return False

        return _play_audio_file(func)
    except Exception as error:
        if _stop_event.is_set():
            return False
        log.warning("TTS error: %s, trying Windows fallback", error)
        try:
            if _speak_with_windows_tts(cleaned_text):
                return True
        except Exception as windows_error:
            log.error("Windows TTS fallback also failed: %s", windows_error)

        _console_fallback(cleaned_text)
        return True
    finally:
        SetAssistantStatus("Idle")
        _cleanup_audio()


def stop_speaking() -> None:
    """Interrupt any ongoing speech immediately."""
    _stop_event.set()
    global _tts_process
    if _tts_process is not None:
        try:
            _tts_process.kill()
        except Exception:
            pass
    try:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    except Exception:
        pass
    log.debug("stop_speaking() called -- speech interrupted")


def is_speaking() -> bool:
    """Check if TTS is currently active."""
    if _tts_thread is not None and _tts_thread.is_alive():
        return True
    return False


def TextToSpeech(text: str, func=lambda r=None: True) -> bool:
    _stop_event.clear()
    return TTS(text, func)


def TextToSpeechAsync(text: str, func=lambda r=None: True) -> threading.Thread:
    """Run TTS in a background thread so the caller is not blocked."""
    global _tts_thread
    _stop_event.clear()
    t = threading.Thread(target=TTS, args=(text, func), daemon=True)
    _tts_thread = t
    t.start()
    return t


if __name__ == "__main__":
    while True:
        user_text = input("Enter the text: ").strip()
        if not user_text:
            continue
        TextToSpeech(user_text)

