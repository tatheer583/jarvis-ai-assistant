import os
import sys
import time
import logging
import requests
from pathlib import Path
from dotenv import dotenv_values
import speech_recognition as sr

from Backend.LanguageManager import is_urdu_mode

log = logging.getLogger("Jarvis.STT")

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
TEMP_DIR = BASE_DIR / "Frontend" / "Files"
TEXT_INPUT_PATH = TEMP_DIR / "TextInput.data"

TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
env_vars = dotenv_values(str(ENV_PATH))
GroqAPIKey = env_vars.get("GroqAPIKey", "")

GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def SetAssistantStatus(status: str) -> None:
    for _ in range(3):
        try:
            with open(TEMP_DIR / "Status.data", "w", encoding="utf-8") as f:
                f.write(status)
            return
        except PermissionError:
            time.sleep(0.05)
        except Exception:
            return


def _consume_text_input() -> str:
    try:
        text = TEXT_INPUT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    if text:
        TEXT_INPUT_PATH.write_text("", encoding="utf-8")
    return text


def _translate_urdu_to_english(text: str) -> str:
    if not text:
        return text
    try:
        import urllib.request, urllib.parse, json
        url = "https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(text) + "&langpair=ur|en"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            translated = data.get("responseData", {}).get("translatedText", "")
            if translated and translated.strip():
                log.info("Translated (urdu->en): %s", translated)
                return translated.strip()
        log.warning("mymemory translation returned empty, falling back to original")
    except Exception as e:
        log.warning("Translation failed: %s", e)
    return text


def QueryModifier(query: str) -> str:
    new_query = query.lower().strip()
    if not new_query:
        return new_query
    query_words = new_query.split()
    question_words = [
        "how", "what", "why", "when", "where", "who", "which",
        "is", "are", "can", "could", "would", "should", "do", "does", "did",
    ]
    if any(new_query.startswith(w + " ") for w in question_words):
        if query_words[-1][-1] in ".!?":
            new_query = new_query[:-1] + "?"
        else:
            new_query += "?"
    else:
        if query_words[-1][-1] in ".!?":
            new_query = new_query[:-1] + "."
        else:
            new_query += "."
    return new_query.capitalize()


def UniversalTranslator(text: str) -> str:
    return _translate_urdu_to_english(text)


def SpeechRecognition() -> str:
    typed = _consume_text_input()
    if typed:
        log.info("Using typed input: %s", typed[:80])
        if is_urdu_mode():
            SetAssistantStatus("Translating...")
            typed = UniversalTranslator(typed)
        SetAssistantStatus("Idle")
        return QueryModifier(typed)

    SetAssistantStatus("Listening...")
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = True
    recognizer.energy_threshold = 300
    recognizer.pause_threshold = 0.8

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=15)

        SetAssistantStatus("Recognizing...")

        temp_wav = TEMP_DIR / "temp_audio.wav"
        with open(temp_wav, "wb") as f:
            f.write(audio.get_wav_data())

        text = _transcribe_with_groq(temp_wav)

        try:
            os.remove(temp_wav)
        except Exception:
            pass

        if not text or len(text) < 2:
            SetAssistantStatus("Available...")
            return ""

        log.info("Whisper recognized: %s", text)

        if is_urdu_mode():
            SetAssistantStatus("Translating...")
            text = UniversalTranslator(text)

        SetAssistantStatus("Idle")
        return QueryModifier(text)

    except sr.WaitTimeoutError:
        SetAssistantStatus("Available...")
        return ""
    except Exception as e:
        log.error("Speech recognition error: %s", e)
        SetAssistantStatus("Available...")
        return ""


def _transcribe_with_groq(audio_path: Path) -> str:
    if not GroqAPIKey:
        log.error("Groq API key is missing!")
        return ""

    try:
        with open(audio_path, "rb") as audio_file:
            files = {"file": (audio_path.name, audio_file.read(), "audio/wav")}
            data = {"model": "whisper-large-v3"}
            headers = {"Authorization": f"Bearer {GroqAPIKey}"}
            resp = requests.post(
                GROQ_API_URL, headers=headers, files=files, data=data, timeout=60
            )

        if resp.status_code == 200:
            result = resp.json()
            return result.get("text", "").strip()
        elif resp.status_code == 401:
            log.error("Groq API authentication failed — check your API key")
        elif resp.status_code == 429:
            log.warning("Groq API rate limit hit")
        else:
            log.error("Groq API error %d: %s", resp.status_code, resp.text[:200])

    except requests.exceptions.ConnectionError:
        log.error("Cannot connect to Groq API — check internet connection")
    except requests.exceptions.Timeout:
        log.error("Groq API request timed out")
    except Exception as e:
        log.error("Groq transcription failed: %s", e)

    return ""


def CloseDriver() -> None:
    pass


if __name__ == "__main__":
    print("Jarvis Speech Recognition started. Speak into your microphone...")
    while True:
        text = SpeechRecognition()
        if text:
            print(f"Recognized: {text}")
