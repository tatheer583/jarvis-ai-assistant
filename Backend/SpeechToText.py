import atexit
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import mtranslate as mt
from dotenv import dotenv_values
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from Backend.LanguageManager import is_urdu_mode, get_recognition_language

log = logging.getLogger("Jarvis.STT")

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "Data"
TEMP_DIR = BASE_DIR / "Frontend" / "Files"

DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
env_vars = dotenv_values(str(ENV_PATH))
InputLanguage = (env_vars.get("InputLanguage") or "en").strip()
VoiceInputFallback = (env_vars.get("VoiceInputFallback") or "text").strip().lower()
TEXT_INPUT_PATH = TEMP_DIR / "TextInput.data"

FIRST_RESULT_TIMEOUT_SECONDS = 10
LISTENING_TIMEOUT_SECONDS = 20
TEXT_INPUT_TIMEOUT_SECONDS = 30
SILENCE_AFTER_FINAL_SECONDS = 1.2
SILENCE_INTERIM_ONLY_SECONDS = 1.8
POLL_INTERVAL_SECONDS = 0.12

MAX_RECOVERY_ATTEMPTS = 3
DRIVER_RETRY_COOLDOWN = 5.0
MAX_POLL_ERRORS_BEFORE_RESET = 8
TRANSIENT_SPEECH_ERRORS = frozenset({
    "no-speech", "aborted", "audio-capture",
})

driver: Optional[ChromeDriver] = None
driver_error: str | None = None
_driver_error_time: float = 0
voice_page_loaded = False
_session_command_count = 0
_translation_cache: dict[str, str] = {}
MAX_TRANSLATION_CACHE = 500

# ---------------------------------------------------------------------------
# HTML for speech recognition (uses Web Speech API in Chrome)
# ---------------------------------------------------------------------------
HTML_CODE = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Speech Recognition</title>
</head>
<body>
    <button id="start" onclick="startRecognition()">Start Recognition</button>
    <button id="end" onclick="stopRecognition()">Stop Recognition</button>
    <p id="output"></p>
    <script>
        const output = document.getElementById('output');
        let recognition;
        window.finalTranscript = '';
        window.interimTranscript = '';
        window.lastUpdateTime = 0;
        window.recognitionError = '';
        window.manuallyStopped = false;
        window.isRecognitionActive = false;

        function startRecognition() {{
            recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
            recognition.lang = window.recognitionLang || '{InputLanguage}';
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.maxAlternatives = 1;

            window.finalTranscript = '';
            window.interimTranscript = '';
            window.lastUpdateTime = 0;
            window.recognitionError = '';
            window.manuallyStopped = false;
            window.isRecognitionActive = true;
            output.textContent = '';

            recognition.onresult = function(event) {{
                let interimTranscript = '';

                for (let i = event.resultIndex; i < event.results.length; i++) {{
                    const transcript = event.results[i][0].transcript.trim();
                    if (!transcript) continue;

                    if (event.results[i].isFinal) {{
                        window.finalTranscript = `${{window.finalTranscript}} ${{transcript}}`.trim();
                    }} else {{
                        interimTranscript = `${{interimTranscript}} ${{transcript}}`.trim();
                    }}
                }}

                window.interimTranscript = interimTranscript;
                output.textContent = `${{window.finalTranscript}} ${{window.interimTranscript}}`.trim();
                window.lastUpdateTime = Date.now();
            }};

            recognition.onerror = function(event) {{
                window.recognitionError = event.error || 'unknown';
                window.isRecognitionActive = false;
            }};

            recognition.onend = function() {{
                window.isRecognitionActive = false;
                if (!window.manuallyStopped) {{
                    try {{
                        window.isRecognitionActive = true;
                        recognition.start();
                    }} catch (error) {{}}
                }}
            }};
            recognition.start();
        }}

        function stopRecognition() {{
            window.manuallyStopped = true;
            window.isRecognitionActive = false;
            if (recognition) {{
                try {{
                    recognition.stop();
                }} catch (error) {{}}
            }}
        }}
    </script>
</body>
</html>"""

# Write the HTML file only if content changed or missing.
VOICE_HTML_PATH = DATA_DIR / "voice.html"
_existing_html = ""
if VOICE_HTML_PATH.exists():
    try:
        _existing_html = VOICE_HTML_PATH.read_text(encoding="utf-8")
    except Exception:
        pass
if _existing_html != HTML_CODE:
    VOICE_HTML_PATH.write_text(HTML_CODE, encoding="utf-8")

VOICE_HTML_LINK = VOICE_HTML_PATH.resolve().as_uri()

# ---------------------------------------------------------------------------
# Chrome WebDriver setup
# ---------------------------------------------------------------------------
chrome_options = Options()
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
chrome_options.add_argument(f"user-agent={user_agent}")
chrome_options.add_argument("--use-fake-ui-for-media-stream")
chrome_options.add_argument("--start-minimized")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--disable-extensions")
chrome_options.add_argument("--disable-background-networking")
chrome_options.add_argument("--disable-sync")
chrome_options.add_argument("--disable-translate")
chrome_options.add_experimental_option(
    "prefs",
    {
        "profile.default_content_setting_values.media_stream_mic": 1,
        "profile.default_content_setting_values.media_stream_camera": 1,
    },
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def SetAssistantStatus(status: str) -> None:
    with open(TEMP_DIR / "Status.data", "w", encoding="utf-8") as f:
        f.write(status)


def _consume_text_input() -> str:
    try:
        text = TEXT_INPUT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""

    if text:
        TEXT_INPUT_PATH.write_text("", encoding="utf-8")
    return text


_cached_stt_driver_path: Optional[str] = None


def _create_driver() -> ChromeDriver:
    global _cached_stt_driver_path
    if _cached_stt_driver_path is None:
        _cached_stt_driver_path = ChromeDriverManager().install()
    service = Service(_cached_stt_driver_path)
    return ChromeDriver(service=service, options=chrome_options)


def _is_driver_alive() -> bool:
    if driver is None:
        return False
    try:
        driver.execute_script("return 1")
        return True
    except Exception:
        return False


def _force_reset_driver() -> None:
    global driver, voice_page_loaded, driver_error
    log.info("Force-resetting STT Chrome driver")
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
    driver = None
    voice_page_loaded = False
    driver_error = None


def GetDriver() -> Optional[ChromeDriver]:
    global driver, driver_error, _driver_error_time

    if driver is not None:
        if _is_driver_alive():
            return driver
        log.warning("STT driver found dead, resetting")
        _force_reset_driver()

    if driver_error is not None:
        if time.time() - _driver_error_time < DRIVER_RETRY_COOLDOWN:
            return None
        log.info("Retrying Chrome startup after previous failure")
        driver_error = None

    try:
        log.info("Starting Chrome for speech recognition")
        driver = _create_driver()
        log.info("Speech recognition Chrome started successfully")
    except Exception as error:
        driver_error = str(error)
        _driver_error_time = time.time()
        log.error("Failed to start Chrome for STT: %s", error)
    return driver


def EnsureVoicePageLoaded() -> bool:
    global voice_page_loaded
    browser = GetDriver()
    if browser is None:
        return False
    try:
        if voice_page_loaded:
            browser.execute_script("return document.readyState")
            return True
        browser.get(VOICE_HTML_LINK)
        browser.find_element(by=By.ID, value="start")
        voice_page_loaded = True
        return True
    except Exception as exc:
        log.warning("Voice page check failed, resetting driver: %s", exc)
        _force_reset_driver()
        return False


def CloseDriver() -> None:
    global driver, voice_page_loaded
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
        driver = None
        voice_page_loaded = False


atexit.register(CloseDriver)


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
    cached = _translation_cache.get(text)
    if cached is not None:
        return cached
    english_translation = mt.translate(text, "en", "auto")
    result = english_translation.capitalize()
    if len(_translation_cache) >= MAX_TRANSLATION_CACHE:
        _translation_cache.clear()
    _translation_cache[text] = result
    return result


def _read_recognition_state(browser):
    return browser.execute_script(
        """
        return {
            text: (document.getElementById('output')?.textContent || '').trim(),
            finalText: (window.finalTranscript || '').trim(),
            interimText: (window.interimTranscript || '').trim(),
            error: window.recognitionError || '',
            isActive: !!window.isRecognitionActive
        };
        """
    )


def _fallback_text_input() -> str:
    if VoiceInputFallback not in {"text", "console", "true", "yes", "1"}:
        return ""
    print("Voice recognition is unavailable. Using text input fallback.")
    SetAssistantStatus("Voice unavailable. Type below and press Send.")

    typed = _consume_text_input()
    if not typed and sys.stdin and sys.stdin.isatty():
        prompt = "Jarvis fallback input> "
        try:
            typed = input(prompt).strip()
        except EOFError:
            typed = ""

    started_at = time.time()
    while not typed and time.time() - started_at < TEXT_INPUT_TIMEOUT_SECONDS:
        typed = _consume_text_input()
        if typed:
            break
        time.sleep(0.2)

    if not typed:
        SetAssistantStatus("Available...")
        return ""

    if is_urdu_mode():
        SetAssistantStatus("Translating...")
        typed = UniversalTranslator(typed)

    result = QueryModifier(typed)
    SetAssistantStatus("Idle")
    return result


# ---------------------------------------------------------------------------
# Core recognition loop (single attempt)
# ---------------------------------------------------------------------------
def _do_recognition(browser) -> str | None:
    """Run one recognition cycle.

    Returns:
        str  -- recognized text (may be empty if user said nothing)
        None -- recoverable failure; caller should reset driver and retry
    """
    lang = get_recognition_language()
    try:
        browser.execute_script(f"window.recognitionLang = '{lang}'")
        browser.find_element(by=By.ID, value="start").click()
    except Exception as exc:
        log.warning("Could not start recognition: %s", exc)
        return None

    SetAssistantStatus("Listening...")
    last_text = ""
    last_final = ""
    last_interim = ""
    last_activity_at = time.time()
    started_at = time.time()
    got_any_speech = False
    consecutive_errors = 0

    while time.time() - started_at < LISTENING_TIMEOUT_SECONDS:
        typed = _consume_text_input()
        if typed:
            log.info("Typed input arrived during listen: %s", typed[:80])
            try:
                browser.find_element(by=By.ID, value="end").click()
            except Exception:
                pass
            if is_urdu_mode():
                typed = UniversalTranslator(typed)
            return QueryModifier(typed)

        try:
            state = _read_recognition_state(browser)
            consecutive_errors = 0
        except WebDriverException as exc:
            consecutive_errors += 1
            if consecutive_errors >= MAX_POLL_ERRORS_BEFORE_RESET:
                log.error("STT polling failed %d times (driver dead): %s",
                          consecutive_errors, exc)
                return None
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors >= MAX_POLL_ERRORS_BEFORE_RESET:
                log.error("STT polling failed %d times: %s",
                          consecutive_errors, exc)
                return None
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        text = state.get("text", "")
        final_text = state.get("finalText", "")
        interim_text = state.get("interimText", "")
        recognition_error = state.get("error", "")

        if recognition_error:
            if recognition_error in TRANSIENT_SPEECH_ERRORS:
                log.info("Transient speech error '%s', restarting recognition",
                         recognition_error)
                try:
                    browser.find_element(by=By.ID, value="end").click()
                    time.sleep(0.2)
                    browser.execute_script(
                        "window.recognitionError = '';"
                        "window.manuallyStopped = false;"
                    )
                    browser.find_element(by=By.ID, value="start").click()
                except Exception:
                    return None
                last_activity_at = time.time()
                continue
            else:
                log.warning("Fatal speech error '%s', signalling reset",
                            recognition_error)
                try:
                    browser.find_element(by=By.ID, value="end").click()
                except Exception:
                    pass
                return None

        activity_changed = (final_text != last_final or interim_text != last_interim)
        if activity_changed:
            last_final = final_text
            last_interim = interim_text
            last_activity_at = time.time()

        if text and text != last_text:
            last_text = text
            got_any_speech = True
            SetAssistantStatus("Recognizing...")

        if not got_any_speech and time.time() - started_at >= FIRST_RESULT_TIMEOUT_SECONDS:
            break

        if got_any_speech and not interim_text:
            silence_duration = time.time() - last_activity_at
            threshold = (SILENCE_AFTER_FINAL_SECONDS if final_text
                         else SILENCE_INTERIM_ONLY_SECONDS)

            if silence_duration >= threshold:
                best_text = (final_text.strip() if final_text.strip()
                             else last_text.strip())
                log.info("Speech stable for %.2fs, accepting: %s",
                         silence_duration, best_text[:80])
                try:
                    browser.find_element(by=By.ID, value="end").click()
                except Exception:
                    pass
                if is_urdu_mode():
                    SetAssistantStatus("Translating...")
                    best_text = UniversalTranslator(best_text)
                return QueryModifier(best_text)

        time.sleep(POLL_INTERVAL_SECONDS)

    try:
        browser.find_element(by=By.ID, value="end").click()
    except Exception:
        pass

    best_text = last_final.strip() if last_final.strip() else last_text.strip()
    if best_text:
        log.info("Listen timed out, returning: %s", best_text[:80])
        if is_urdu_mode():
            SetAssistantStatus("Translating...")
            best_text = UniversalTranslator(best_text)
        return QueryModifier(best_text)

    return ""


# ---------------------------------------------------------------------------
# Public API -- self-healing wrapper with recovery loop
# ---------------------------------------------------------------------------
def SpeechRecognition() -> str:
    global _session_command_count

    typed = _consume_text_input()
    if typed:
        log.info("Using typed input (skipping voice): %s", typed[:80])
        if is_urdu_mode():
            SetAssistantStatus("Translating...")
            typed = UniversalTranslator(typed)
        return QueryModifier(typed)

    for attempt in range(1, MAX_RECOVERY_ATTEMPTS + 1):
        browser = GetDriver()
        if browser is None:
            if attempt < MAX_RECOVERY_ATTEMPTS:
                log.info("Driver unavailable, waiting before retry %d/%d",
                         attempt, MAX_RECOVERY_ATTEMPTS)
                time.sleep(DRIVER_RETRY_COOLDOWN)
                continue
            break

        if not EnsureVoicePageLoaded():
            if attempt < MAX_RECOVERY_ATTEMPTS:
                log.info("Voice page failed, resetting for retry %d/%d",
                         attempt, MAX_RECOVERY_ATTEMPTS)
                _force_reset_driver()
                time.sleep(1)
                continue
            break

        result = _do_recognition(browser)

        if result is not None:
            if result:
                _session_command_count += 1
                log.info("Voice command #%d accepted", _session_command_count)
            SetAssistantStatus("Idle")
            return result

        log.warning("Recognition attempt %d/%d failed, resetting driver",
                    attempt, MAX_RECOVERY_ATTEMPTS)
        _force_reset_driver()
        if attempt < MAX_RECOVERY_ATTEMPTS:
            time.sleep(1)

    log.error("All %d STT recovery attempts failed, using text fallback",
              MAX_RECOVERY_ATTEMPTS)
    SetAssistantStatus("Idle")
    return _fallback_text_input()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Speech Recognition started. Speak into your microphone...")
    while True:
        text = SpeechRecognition()
        if text:
            print(f"Recognized: {text}")

