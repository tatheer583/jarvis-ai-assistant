import asyncio
import logging
import os
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import keyboard
import pywhatkit
import requests
from AppOpener import close, open as app_open
from bs4 import BeautifulSoup
from dotenv import dotenv_values
from groq import Groq
from pywhatkit.misc import playonyt, search

from Backend.ActionResult import ActionResult
from Backend.BrowserAutomation import (
    close_browser,
    google_search as _browser_google_search,
    open_website as _browser_open,
    whatsapp_open as _browser_wa_open,
    whatsapp_send_message as _browser_wa_send,
    youtube_play as _browser_yt_play,
    youtube_search as _browser_yt_search,
)

log = logging.getLogger("Jarvis.Automation")

# ---------------------------------------------------------------------------
# Path setup -- resolve project root so paths work regardless of cwd
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DATA_DIR = BASE_DIR / "Data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Environment & API client
# ---------------------------------------------------------------------------
env_vars = dotenv_values(str(ENV_PATH))
Username = env_vars.get("Username", os.environ.get("USERNAME", "User"))
GroqAPIKey = env_vars.get("GroqAPIKey", "")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/100.0.4896.75 Safari/537.36"
)

try:
    client: Groq | None = Groq(api_key=GroqAPIKey) if GroqAPIKey else None
except Exception as e:
    log.warning("Failed to initialize Groq client for automation: %s", e)
    client = None
messages: list[dict[str, str]] = []
MAX_CONTENT_HISTORY = 100
SYSTEM_CHATBOT = [
    {
        "role": "system",
        "content": (
            f"Hello, I am {Username}. "
            "You are a content writer. Write clear, polished, and professional content."
        ),
    }
]


# ---------------------------------------------------------------------------
# Known websites -- direct URL map for sites AppOpener can't handle
# ---------------------------------------------------------------------------
KNOWN_WEBSITES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "github": "https://github.com",
    "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "google maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "spotify": "https://open.spotify.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "chatgpt": "https://chat.openai.com",
    "wikipedia": "https://www.wikipedia.org",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "telegram web": "https://web.telegram.org",
}


# ---------------------------------------------------------------------------
# System command definitions
# ---------------------------------------------------------------------------
VOLUME_COMMANDS: dict[str, str] = {
    "mute": "volume mute",
    "unmute": "volume mute",
    "volume up": "volume up",
    "volume down": "volume down",
}

DANGEROUS_COMMANDS = frozenset({"shutdown", "restart"})
SHUTDOWN_DELAY_SECONDS = 10
MAX_CONCURRENT_TASKS = 3
TASK_TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# WhatsApp messaging
# ---------------------------------------------------------------------------
def SendWhatsAppMessage(command: str) -> ActionResult:
    """Parse and send a WhatsApp message.

    Expected format from DMM: ``send message <contact_name> <message>``
    """
    try:
        payload = command.strip()
        if payload.lower().startswith("send message "):
            payload = payload[13:].strip()

        parts = payload.split(maxsplit=1)
        if len(parts) != 2:
            return ActionResult.fail(
                "send_whatsapp",
                f"Could not parse contact and message from: {command}",
                error="invalid_format",
            )

        contact_name, message = parts[0].strip(), parts[1].strip()
        return SendWhatsAppByName(contact_name, message)
    except Exception as error:
        log.error("WhatsApp message error: %s", error)
        return ActionResult.fail(
            "send_whatsapp", f"WhatsApp failed: {error}", error=str(error),
        )


def SendWhatsAppByName(contact_name: str, message: str) -> ActionResult:
    """Open WhatsApp Web, find the contact, and send the message."""
    try:
        success = _browser_wa_send(contact_name, message)
        if success:
            return ActionResult.ok(
                "send_whatsapp",
                f"Message sent to '{contact_name}' successfully.",
                contact=contact_name,
            )
        return ActionResult.fail(
            "send_whatsapp",
            f"Failed to send message to '{contact_name}'.",
            error="selenium_send_failed",
        )
    except Exception as error:
        log.warning("WhatsApp Selenium failed, opening browser fallback: %s", error)
        webbrowser.open("https://web.whatsapp.com")
        return ActionResult.fail(
            "send_whatsapp",
            f"Could not auto-send to '{contact_name}'. Opened WhatsApp Web for manual use.",
            error=str(error),
        )


# ---------------------------------------------------------------------------
# Google / YouTube helpers
# ---------------------------------------------------------------------------
def GoogleSearch(topic: str) -> ActionResult:
    """Search Google via Selenium (falls back to pywhatkit / webbrowser)."""
    try:
        if _browser_google_search(topic):
            return ActionResult.ok("google_search", f"Searched Google for '{topic}'.", query=topic)
    except Exception as error:
        log.warning("Google Selenium failed, falling back: %s", error)

    try:
        search(topic)
    except Exception:
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(topic)}")

    return ActionResult.ok(
        "google_search", f"Opened Google search for '{topic}'.", query=topic, fallback=True,
    )


def YouTubeSearch(topic: str) -> ActionResult:
    """Search YouTube via Selenium (falls back to webbrowser)."""
    try:
        if _browser_yt_search(topic):
            return ActionResult.ok("youtube_search", f"Searched YouTube for '{topic}'.", query=topic)
    except Exception as error:
        log.warning("YouTube Selenium failed, falling back: %s", error)

    webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(topic)}")
    return ActionResult.ok(
        "youtube_search", f"Opened YouTube search for '{topic}'.", query=topic, fallback=True,
    )


def PlayYoutube(query: str) -> ActionResult:
    """Search YouTube and auto-play the first result via Selenium."""
    try:
        if _browser_yt_play(query):
            return ActionResult.ok("play_youtube", f"Playing '{query}' on YouTube.", query=query)
    except Exception as error:
        log.warning("YouTube Selenium play failed, falling back: %s", error)

    try:
        playonyt(query)
        return ActionResult.ok(
            "play_youtube", f"Playing '{query}' on YouTube.", query=query, fallback=True,
        )
    except Exception as error:
        log.error("YouTube play failed completely: %s", error)
        return ActionResult.fail(
            "play_youtube", f"Could not play '{query}' on YouTube.", error=str(error),
        )


# ---------------------------------------------------------------------------
# Content writer (Groq AI)
# ---------------------------------------------------------------------------
def _open_notepad(file_path: Path) -> None:
    try:
        proc = subprocess.Popen(["notepad.exe", str(file_path)])
        proc.detach = True  # type: ignore[attr-defined]
    except Exception as error:
        log.warning("Could not open notepad: %s", error)


def _content_writer_ai(prompt: str) -> str:
    """Generate content via Groq LLM with a local fallback."""
    answer = ""
    if client is not None:
        try:
            conversation = SYSTEM_CHATBOT + messages[-20:] + [{"role": "user", "content": prompt}]
            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=conversation,  # type: ignore[arg-type]
                max_tokens=1024,
                temperature=0.7,
                top_p=1,
                stream=False,
            )

            if hasattr(completion, "choices") and completion.choices:
                msg = completion.choices[0].message
                if hasattr(msg, "content") and msg.content:
                    answer = msg.content
        except Exception as error:
            log.warning("Content generation via Groq failed: %s", error)

    if not answer:
        topic = prompt.strip().rstrip(".")
        heading = topic[:1].upper() + topic[1:] if topic else "Content"
        answer = (
            f"{heading}\n\n"
            f"This draft was prepared by {Username}'s Jarvis assistant in local fallback mode. "
            f"It provides a clean starting point that you can refine further.\n\n"
            f"Main points:\n"
            f"- Purpose: address the request about {topic or 'the requested topic'} clearly.\n"
            f"- Tone: professional, polite, and easy to understand.\n"
            f"- Next step: review, personalize details, and finalize the message."
        )

    answer = answer.replace("</s>", "").strip()
    messages.append({"role": "user", "content": prompt})
    messages.append({"role": "assistant", "content": answer})
    if len(messages) > MAX_CONTENT_HISTORY:
        del messages[:-MAX_CONTENT_HISTORY]
    return answer


def _safe_topic_filename(topic: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in topic.lower())
    return cleaned.strip("_") or "content"


def Content(topic: str) -> ActionResult:
    """Generate a content file and open it in Notepad."""
    try:
        content_text = _content_writer_ai(topic)
        file_path = DATA_DIR / f"{_safe_topic_filename(topic)}.txt"
        file_path.write_text(content_text, encoding="utf-8")
        _open_notepad(file_path)
        return ActionResult.ok(
            "content",
            f"Content about '{topic}' saved and opened in Notepad.",
            file=str(file_path),
        )
    except Exception as error:
        log.error("Content generation failed: %s", error)
        return ActionResult.fail(
            "content", f"Failed to generate content about '{topic}'.", error=str(error),
        )


# ---------------------------------------------------------------------------
# Internal web helpers (kept for potential future use)
# ---------------------------------------------------------------------------
def _extract_links(html: str | None) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for link in soup.find_all("a", href=True):
        href = link.get("href")
        if isinstance(href, str) and href.startswith("http"):
            links.append(href)
    return links


def _search_google(query: str, session: requests.Session) -> str | None:
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    if response.status_code == 200:
        return response.text
    log.warning("Google scrape returned status %d", response.status_code)
    return None


# ---------------------------------------------------------------------------
# App open / close
# ---------------------------------------------------------------------------
INTERACTIVE_SITES = frozenset({
    "whatsapp", "whatsapp web",
})


def OpenApp(app: str) -> ActionResult:
    """Open an application or website by name."""
    app_lower = app.strip().lower()

    # 1. Known website
    if app_lower in KNOWN_WEBSITES:
        url = KNOWN_WEBSITES[app_lower]
        log.info("Opening known website: %s -> %s", app_lower, url)

        if app_lower in INTERACTIVE_SITES:
            try:
                if _browser_open(url):
                    return ActionResult.ok("open_app", f"Opened {app_lower}.", target=app_lower)
            except Exception as error:
                log.warning("Selenium failed for %s, falling back: %s", app_lower, error)

        webbrowser.open(url)
        return ActionResult.ok(
            "open_app", f"Opened {app_lower}.", target=app_lower,
        )

    # 2. URL-like string -> lightweight browser open
    if "." in app_lower and " " not in app_lower:
        url = app_lower if app_lower.startswith("http") else f"https://{app_lower}"
        log.info("Opening URL: %s", url)
        webbrowser.open(url)
        return ActionResult.ok(
            "open_app", f"Opened {url}.", target=url,
        )

    # 3. Desktop app via AppOpener
    try:
        app_open(app, match_closest=True, output=True, throw_error=True)
        return ActionResult.ok("open_app", f"Opened '{app}'.", target=app)
    except Exception as error:
        log.warning("AppOpener failed for '%s': %s", app, error)

    # 4. Final fallback: Google search
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(app)}")
    return ActionResult.fail(
        "open_app",
        f"Could not find '{app}' as an app. Opened a Google search instead.",
        error="app_not_found",
    )


def CloseApp(app: str) -> ActionResult:
    """Close an application by name."""
    try:
        close(app, match_closest=True, output=True, throw_error=True)
        return ActionResult.ok("close_app", f"Closed '{app}'.", target=app)
    except Exception as error:
        log.warning("Failed to close '%s': %s", app, error)
        return ActionResult.fail(
            "close_app", f"Could not close '{app}'.", error=str(error),
        )


# ---------------------------------------------------------------------------
# System controls
# ---------------------------------------------------------------------------
def System(command: str, *, confirmed: bool = False) -> ActionResult:
    """Execute a system-level command (volume, power, lock).

    Dangerous commands (shutdown, restart) require ``confirmed=True``.
    Safe commands (volume, lock, sleep) execute immediately.
    """
    normalized = command.strip().lower()

    # --- Volume controls (always safe) ---
    hotkey = VOLUME_COMMANDS.get(normalized)
    if hotkey is not None:
        try:
            keyboard.press_and_release(hotkey)
            return ActionResult.ok("system", f"System: {normalized}.", command=normalized)
        except Exception as error:
            log.error("Volume command '%s' failed: %s", normalized, error)
            return ActionResult.fail(
                "system", f"Failed to execute '{normalized}'.", error=str(error),
            )

    # --- Lock screen (safe) ---
    if normalized in ("lock", "lock screen"):
        try:
            subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                check=True, timeout=5,
            )
            return ActionResult.ok("system", "Screen locked.", command="lock")
        except Exception as error:
            log.error("Lock screen failed: %s", error)
            return ActionResult.fail(
                "system", "Failed to lock the screen.", error=str(error),
            )

    # --- Sleep (moderate, no confirmation needed) ---
    if normalized == "sleep":
        try:
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
                check=True, timeout=5,
            )
            return ActionResult.ok("system", "Computer entering sleep mode.", command="sleep")
        except Exception as error:
            log.error("Sleep command failed: %s", error)
            return ActionResult.fail(
                "system", "Failed to put the computer to sleep.", error=str(error),
            )

    # --- Dangerous: shutdown / restart (confirmation required) ---
    if normalized in DANGEROUS_COMMANDS:
        if not confirmed:
            return ActionResult.fail(
                "system",
                f"'{normalized.title()}' requires confirmation. Please confirm to proceed.",
                error="confirmation_required",
            )
        flag = "/s" if normalized == "shutdown" else "/r"
        try:
            subprocess.run(
                ["shutdown", flag, "/t", str(SHUTDOWN_DELAY_SECONDS)],
                check=True, timeout=5,
            )
            return ActionResult.ok(
                "system",
                f"System will {normalized} in {SHUTDOWN_DELAY_SECONDS} seconds. "
                f"Run 'shutdown /a' to cancel.",
                command=normalized, delay=SHUTDOWN_DELAY_SECONDS,
            )
        except Exception as error:
            log.error("System %s failed: %s", normalized, error)
            return ActionResult.fail(
                "system", f"Failed to {normalized}.", error=str(error),
            )

    # --- Unrecognized ---
    return ActionResult.fail(
        "system", f"Unknown system command: '{command}'.", error="unknown_command",
    )


def CancelShutdown() -> ActionResult:
    """Cancel a pending shutdown or restart."""
    try:
        subprocess.run(["shutdown", "/a"], check=True, timeout=5)
        return ActionResult.ok("system", "Pending shutdown/restart cancelled.", command="cancel")
    except Exception as error:
        log.error("Cancel shutdown failed: %s", error)
        return ActionResult.fail(
            "system",
            "No pending shutdown to cancel or cancellation failed.",
            error=str(error),
        )


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------
async def TranslateAndExecute(commands: list[str]) -> list[ActionResult]:
    """Dispatch classified command strings to the appropriate handlers.

    Returns a list of ActionResult objects, one per executed command.
    Commands prefixed with ``general`` or ``realtime`` are skipped here
    because they are handled by the assistant logic layer in Main.py.
    """
    sem = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
    pending: list[Any] = []
    seen: set[str] = set()

    for command in commands:
        current = command.strip()
        normalized = current.lower()

        if normalized in seen:
            log.info("Skipping duplicate command: %s", normalized)
            continue
        seen.add(normalized)
        log.info("Routing command: %s", normalized)

        if normalized.startswith("open "):
            if normalized in ("open it", "open file"):
                continue
            pending.append(asyncio.to_thread(OpenApp, current[5:].strip()))

        elif normalized.startswith("send message "):
            payload = current[13:].strip()
            parts = payload.split(maxsplit=1)
            if len(parts) == 2:
                pending.append(
                    asyncio.to_thread(SendWhatsAppByName, parts[0].strip(), parts[1].strip())
                )
            else:
                log.warning("Could not parse contact/message from: %s", payload)

        elif normalized.startswith("whatsapp "):
            payload = current[9:].strip()
            parts = payload.split(maxsplit=1)
            if len(parts) == 2:
                pending.append(
                    asyncio.to_thread(SendWhatsAppByName, parts[0].strip(), parts[1].strip())
                )
            else:
                pending.append(asyncio.to_thread(OpenApp, "whatsapp"))

        elif normalized.startswith("close "):
            pending.append(asyncio.to_thread(CloseApp, current[6:].strip()))

        elif normalized.startswith("play "):
            pending.append(asyncio.to_thread(PlayYoutube, current[5:].strip()))

        elif normalized.startswith("content "):
            pending.append(asyncio.to_thread(Content, current[8:].strip()))

        elif normalized.startswith("google search "):
            pending.append(asyncio.to_thread(GoogleSearch, current[14:].strip()))

        elif normalized.startswith("youtube search "):
            pending.append(asyncio.to_thread(YouTubeSearch, current[15:].strip()))

        elif normalized.startswith("system "):
            pending.append(asyncio.to_thread(System, current[7:].strip()))

        elif normalized.startswith(("general ", "realtime ")):
            continue

        else:
            log.info("No handler registered for command: %s", current)

    if not pending:
        return []

    log.info("Dispatching %d command(s)", len(pending))

    async def _guarded(coro):
        async with sem:
            return await asyncio.wait_for(coro, timeout=TASK_TIMEOUT_SECONDS)

    raw_results = await asyncio.gather(
        *[_guarded(c) for c in pending], return_exceptions=True,
    )

    results: list[ActionResult] = []
    for result in raw_results:
        if isinstance(result, asyncio.TimeoutError):
            log.error("Command timed out after %ds", TASK_TIMEOUT_SECONDS)
            results.append(
                ActionResult.fail("automation", "Task timed out.", error="timeout")
            )
        elif isinstance(result, ActionResult):
            results.append(result)
        elif isinstance(result, Exception):
            log.error("Command execution raised an exception: %s", result)
            results.append(
                ActionResult.fail("automation", str(result), error=type(result).__name__)
            )
        else:
            results.append(ActionResult.ok("automation", "Command executed."))

    return results


async def Automation(commands: list[str]) -> ActionResult:
    """Execute all classified commands and return an aggregated result."""
    results = await TranslateAndExecute(commands)

    if not results:
        return ActionResult.ok("automation", "No actionable commands to execute.")

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]

    if failures and not successes:
        combined = "; ".join(r.message for r in failures)
        return ActionResult.fail("automation", combined)

    if failures:
        combined = "; ".join(r.message for r in successes + failures)
        return ActionResult(
            success=True, action="automation", message=combined,
            data={"partial_failure": True, "total": len(results), "failed": len(failures)},
        )

    combined = "; ".join(r.message for r in successes)
    return ActionResult.ok("automation", combined, total=len(successes))


# ---------------------------------------------------------------------------
# Standalone testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys as _sys

    test_commands = _sys.argv[1:] or ["general hello"]
    print(f"Running automation with: {test_commands}")
    result = asyncio.run(Automation(test_commands))
    print(f"Result: {result}")
