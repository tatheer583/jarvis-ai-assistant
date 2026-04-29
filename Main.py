from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from time import sleep

from dotenv import dotenv_values

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parent / "Data"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "jarvis.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("Jarvis.Main")

from Backend.Automation import Automation
from Backend.BrowserAutomation import close_browser, kill_orphaned_chromedriver
from Backend.Chatbot import ChatBot
from Backend.LanguageManager import detect_mode_switch, set_mode
from Backend.Model import FirstlayerDMM
from Backend.RealtimeSearchEngine import RealtimeSearchEngine
from Backend.SpeechToText import SpeechRecognition, CloseDriver as close_stt_driver
from Backend.TextToSpeech import TextToSpeech, TextToSpeechAsync, is_speaking, stop_speaking
from Backend.RemoteAccess import start_remote_server_thread, REMOTE_PORT, REMOTE_HOST
from Frontend.GUI import (
    AnswerModifier,
    GetAssistantStatus,
    GetMicrophoneStatus,
    GraphicalUserInterface,
    QueryModifier,
    SetAssistantStatus,
    SetMicrophoneStatus,
    TempDirectoryPath,
    appendTextToScreen,
    showTextToScreen,
)

import time as _time

_shutdown_event = threading.Event()
_execution_lock = threading.Lock()
_chatlog_lock = threading.Lock()
COMMAND_COOLDOWN_SECONDS = 0.8
AUTOMATION_TIMEOUT_SECONDS = 30
_last_command_time: float = 0

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
CHAT_LOG_PATH = BASE_DIR / "Data" / "ChatLog.json"
IMAGE_SIGNAL_PATHS = [
    BASE_DIR / "Frontend" / "Files" / "ImageGeneration.data",
    BASE_DIR / "Frontend" / "Files" / "ImageGenration.data",
]

env_vars = dotenv_values(str(ENV_PATH))
Username = env_vars.get("Username", os.environ.get("USERNAME", "User"))
Assistantname = env_vars.get("AssistantName", "Jarvis")
DefaultMessage = (
    f"{Username}: Hello {Assistantname}, how are you?\n"
    f"{Assistantname}: Welcome {Username}. I am doing well. How may I help you?"
)
subprocesses: list[subprocess.Popen[bytes]] = []
Functions = ["open", "close", "play", "system", "content", "google search", "youtube search", "send message", "whatsapp"]


def ShowDefaultChatIfNoChat() -> None:
    CHAT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CHAT_LOG_PATH.exists():
        CHAT_LOG_PATH.write_text("[]", encoding="utf-8")

    chat_log_text = CHAT_LOG_PATH.read_text(encoding="utf-8").strip()
    if len(chat_log_text) < 5:
        Path(TempDirectoryPath("Database.data")).write_text("", encoding="utf-8")
        Path(TempDirectoryPath("Responses.data")).write_text(DefaultMessage, encoding="utf-8")


def ReadChatLogJson() -> list[dict[str, str]]:
    with _chatlog_lock:
        try:
            with open(CHAT_LOG_PATH, "r", encoding="utf-8") as file:
                chatlog_data = json.load(file)
            if isinstance(chatlog_data, list):
                return chatlog_data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    return []


def ChatLogIntegration() -> None:
    json_data = ReadChatLogJson()
    formatted_chatlog = []

    for entry in json_data:
        role = entry.get("role", "").lower()
        content = str(entry.get("content", "")).strip()
        if not content:
            continue

        if role == "user":
            formatted_chatlog.append(f"{Username}: {content}")
        elif role == "assistant":
            formatted_chatlog.append(f"{Assistantname}: {content}")

    formatted_text = AnswerModifier("\n".join(formatted_chatlog)) or DefaultMessage
    Path(TempDirectoryPath("Database.data")).write_text(
        formatted_text,
        encoding="utf-8",
    )


def RefreshChatDisplay() -> None:
    ChatLogIntegration()
    ShowChatOnGUI()


def _record_chat_message(role: str, content: str) -> None:
    cleaned = str(content).strip()
    if not cleaned:
        return

    with _chatlog_lock:
        try:
            with open(CHAT_LOG_PATH, "r", encoding="utf-8") as f:
                chat_log = json.load(f)
            if not isinstance(chat_log, list):
                chat_log = []
        except (FileNotFoundError, json.JSONDecodeError):
            chat_log = []
        chat_log.append({"role": role, "content": cleaned})
        CHAT_LOG_PATH.write_text(json.dumps(chat_log[-100:], indent=2), encoding="utf-8")


def _record_local_exchange(user_message: str, assistant_message: str) -> None:
    _record_chat_message("user", user_message)
    _record_chat_message("assistant", assistant_message)
    RefreshChatDisplay()



def ShowChatOnGUI() -> None:
    database_path = Path(TempDirectoryPath("Database.data"))
    response_path = Path(TempDirectoryPath("Responses.data"))

    if not database_path.exists():
        return

    data = database_path.read_text(encoding="utf-8").strip()
    if data:
        response_path.write_text(data, encoding="utf-8")


def InitialExecution() -> None:
    SetMicrophoneStatus("False")
    SetAssistantStatus("Available...")
    showTextToScreen("")
    ShowDefaultChatIfNoChat()
    RefreshChatDisplay()


def _extract_task_query(command: str) -> str:
    parts = command.split(maxsplit=1)
    if len(parts) <= 1:
        return ""

    raw = parts[1].strip()
    bracket_match = re.fullmatch(r"\((.*)\)", raw)
    return bracket_match.group(1).strip() if bracket_match else raw


def _start_image_generation(query: str) -> None:
    clean_query = query.replace("generate image", "", 1).strip() or query.strip()
    if not clean_query:
        return

    # Clean up finished subprocesses
    subprocesses[:] = [p for p in subprocesses if p.poll() is None]

    payload = f"{clean_query},True"
    for signal_path in IMAGE_SIGNAL_PATHS:
        try:
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text(payload, encoding="utf-8")
        except Exception as error:
            log.error("Failed to write image signal file %s: %s", signal_path, error)

    try:
        process = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "Backend" / "ImageGenration.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            shell=False,
        )
        subprocesses.append(process)
    except Exception as error:
        log.error("Error starting ImageGeneration: %s", error)


def _show_live_user_message(query: str) -> None:
    appendTextToScreen(f"{Username}: {query}")


def _speak_and_display_answer(answer: str, blocking: bool = False) -> None:
    if is_speaking():
        stop_speaking()
        sleep(0.1)
    SetAssistantStatus("Answering...")
    RefreshChatDisplay()
    if blocking:
        TextToSpeech(answer)
    else:
        TextToSpeechAsync(answer)


def MainExecution() -> bool:
    global _last_command_time

    # -- Concurrency guard: one command at a time --
    if not _execution_lock.acquire(blocking=False):
        log.debug("MainExecution skipped -- already executing")
        return False

    try:
        # -- Cooldown: prevent command spam --
        now_ts = _time.time()
        if now_ts - _last_command_time < COMMAND_COOLDOWN_SECONDS:
            log.debug("Cooldown active, skipping")
            return False

        task_execution = False
        image_execution = False
        image_generation_query = ""
        automation_result = None

        SetAssistantStatus("Listening...")
        try:
            query = SpeechRecognition()
        except Exception as e:
            log.error("SpeechRecognition error: %s: %s", type(e).__name__, e)
            SetAssistantStatus("Available...")
            return False
        if not query:
            log.debug("SpeechRecognition returned empty")
            SetAssistantStatus("Available...")
            return False

        _last_command_time = _time.time()
        _show_live_user_message(query)

        new_mode = detect_mode_switch(query)
        if new_mode is not None:
            set_mode(new_mode)
            if new_mode == "urdu":
                answer = "Urdu mode activated. I will now listen and speak in Urdu."
            else:
                answer = "English mode activated. I will now listen and speak in English."
            _record_local_exchange(query, answer)
            _speak_and_display_answer(answer)
            return True

        SetAssistantStatus("Thinking...")
        decision = FirstlayerDMM(query)

        log.info("Decision: %s", decision)

        if not decision:
            answer = ChatBot(QueryModifier(query))
            RefreshChatDisplay()
            _speak_and_display_answer(answer)
            return True

        general_detected = any(item.startswith("general") for item in decision)
        realtime_detected = any(item.startswith("realtime") for item in decision)

        merged_query = " and ".join(
            _extract_task_query(item)
            for item in decision
            if item.startswith(("general", "realtime"))
        ).strip()

        for current_query in decision:
            if current_query.startswith("generate image"):
                image_generation_query = current_query
                image_execution = True

        for current_query in decision:
            if not task_execution and any(current_query.startswith(func) for func in Functions):
                try:
                    automation_result = asyncio.run(
                        asyncio.wait_for(
                            Automation(decision),
                            timeout=AUTOMATION_TIMEOUT_SECONDS,
                        )
                    )
                    task_execution = bool(automation_result and automation_result.success)
                    if automation_result is not None:
                        log.info(
                            "Automation result: success=%s, partial_failure=%s, message=%s",
                            automation_result.success,
                            automation_result.data.get("partial_failure") if automation_result.data else False,
                            automation_result.message,
                        )
                except asyncio.TimeoutError:
                    log.error("Automation timed out after %ds", AUTOMATION_TIMEOUT_SECONDS)
                except Exception as error:
                    log.error("Automation error: %s", error)

        if image_execution:
            _start_image_generation(image_generation_query)

        if realtime_detected:
            SetAssistantStatus("Searching...")
            answer = RealtimeSearchEngine(QueryModifier(merged_query or query))
            RefreshChatDisplay()
            _speak_and_display_answer(answer)
            return True

        if general_detected:
            for current_query in decision:
                if current_query.startswith("general"):
                    SetAssistantStatus("Thinking...")
                    query_final = _extract_task_query(current_query) or query
                    answer = ChatBot(QueryModifier(query_final))
                    RefreshChatDisplay()
                    _speak_and_display_answer(answer)
                    return True

        for current_query in decision:
            if current_query.startswith("exit"):
                answer = "Okay, Bye!"
                _record_local_exchange(query, answer)
                _speak_and_display_answer(answer, blocking=True)
                log.info("Exit command received, shutting down.")
                _shutdown()
                return True

        if image_execution and task_execution:
            if automation_result:
                if automation_result.data and automation_result.data.get("partial_failure"):
                    answer = (
                        f"{automation_result.message} I also started generating the image for you."
                    )
                else:
                    answer = f"{automation_result.message} I also started generating the image for you."
            else:
                answer = "Done. I also started generating the image for you."
            _record_local_exchange(query, answer)
            _speak_and_display_answer(answer)
            return True

        if image_execution:
            answer = "I started generating the image for you."
            _record_local_exchange(query, answer)
            _speak_and_display_answer(answer)
            return True

        if automation_result is not None and not task_execution:
            if automation_result.data and automation_result.data.get("partial_failure"):
                answer = (
                    f"I completed some parts of the task, but some actions failed: {automation_result.message}"
                )
            else:
                answer = automation_result.message or "I attempted the task but could not complete it."
            _record_local_exchange(query, answer)
            _speak_and_display_answer(answer)
            return True

        if task_execution:
            if automation_result and automation_result.data and automation_result.data.get("partial_failure"):
                answer = (
                    f"I completed most of the task, but there were partial failures: {automation_result.message}"
                )
            else:
                answer = automation_result.message if automation_result else "Done."
            _record_local_exchange(query, answer)
            _speak_and_display_answer(answer)
            return True

        return task_execution or image_execution
    finally:
        _execution_lock.release()


def _shutdown() -> None:
    """Clean up all resources and exit."""
    log.info("Initiating clean shutdown...")
    _shutdown_event.set()

    stop_speaking()

    close_stt_driver()
    close_browser()

    for proc in subprocesses:
        try:
            proc.kill()
        except Exception:
            pass
    subprocesses.clear()

    log.info("Shutdown complete.")
    os._exit(0)


def FirstThread() -> None:
    while not _shutdown_event.is_set():
        try:
            current_status = GetMicrophoneStatus()

            if current_status == "True":
                if is_speaking():
                    sleep(0.15)
                    continue
                log.debug("Mic is ON, calling MainExecution")
                result = MainExecution()
                if not result:
                    sleep(0.5)
                else:
                    sleep(0.2)
            else:
                ai_status = GetAssistantStatus()
                if "Available..." not in ai_status:
                    SetAssistantStatus("Available...")
                sleep(0.5)
        except Exception as e:
            log.error("Main loop error: %s: %s", type(e).__name__, e)
            SetAssistantStatus("Available...")
            sleep(3)


def SecondThread() -> None:
    GraphicalUserInterface()


if __name__ == "__main__":
    log.info("Starting %s...", Assistantname)

    kill_orphaned_chromedriver()
    InitialExecution()

    start_remote_server_thread()
    log.info("Remote access server started on http://%s:%d", REMOTE_HOST, REMOTE_PORT)

    thread = threading.Thread(target=FirstThread, daemon=True)
    thread.start()
    SecondThread()

