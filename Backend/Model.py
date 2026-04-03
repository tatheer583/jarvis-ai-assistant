import logging
import re
import time
from pathlib import Path

import cohere
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
env_vars = dotenv_values(str(ENV_PATH))

log = logging.getLogger("Jarvis.Model")

CohereAPIKey = env_vars.get("CohereAPIKey", "")
COHERE_TIMEOUT = 20
DMM_STREAM_TIMEOUT = 15

try:
    co = cohere.Client(api_key=CohereAPIKey, timeout=COHERE_TIMEOUT) if CohereAPIKey else None
except Exception as e:
    log.warning("Failed to initialize Cohere client: %s", e)
    co = None
 
# Define a list of recognized function keywords for task categorization:
funcs = [
    "exit", "general", "realtime", "open", "close", "play",
    "generate image", "system", "content", "google search",
    "youtube search", "reminder", "send message", "whatsapp"
]

# Preamble that guides the AI model on how to categorize queries.
preamble = """
You are an advanced Decision-Making Model that classifies user queries into specific task categories.
Your job is NOT to answer the query. Your job is only to determine what type of query the user is giving.
You must return the query in one of the following formats.
GENERAL RULES:
* Do NOT answer the query.
* Only classify the query.
* Always return the classification in the exact format described below.
* Keep the original user query inside parentheses.
---
1. GENERAL KNOWLEDGE
Respond with:
general (query)
Use this if the query can be answered by a language model and does not require real-time information.
Examples:
"What is quantum computing?"
"Explain machine learning"
---
2. REALTIME INFORMATION
Respond with:
realtime (query)
Use this if the query requires up-to-date or live data.
Examples:
"What is the weather today?"
"Who won the match today?"
---
3. OPEN APPLICATION OR WEBSITE
Respond with:
open (application or website name)
Examples:
"open youtube"
"open facebook"
"open telegram"
"open chrome"
---
4. CLOSE APPLICATION
Respond with:
close (application name)
Examples:
"close chrome"
"close telegram"
"close notepad"
---
5. PLAY MUSIC
Respond with:
play (song name)
Examples:
"play let her go"
"play afsana by ys"
---
6. IMAGE GENERATION
Respond with:
generate image (image prompt)
Example:
"generate image of a futuristic city at night"
---
7. REMINDERS
Respond with:
reminder (datetime with message)
Example:
"set reminder at 9 pm to study"
---
8. SYSTEM CONTROL
Respond with:
system (task name)
Tasks may include:
mute
unmute
volume up
volume down
shutdown
restart
sleep
---
9. CONTENT GENERATION
Respond with:
content (topic)
Examples:
"write an email for job application"
"write code for a python calculator"
---
10. GOOGLE SEARCH
Respond with:
google search (topic)
Example:
"search google for artificial intelligence news"
---
11. YOUTUBE SEARCH
Respond with:
youtube search (topic)
Example:
"search youtube for python tutorial"
---
12. WHATSAPP / SEND MESSAGE
Respond with:
send message (contact_name) (message text)
Use this when the user wants to send a message to someone on WhatsApp or any messaging platform.
Examples:
"send a message to imran that tomorrow we will go to bazar" → send message imran tomorrow we will go to bazar
"whatsapp ali hello how are you" → send message ali hello how are you
"tell imran on whatsapp that meeting is at 5pm" → send message imran meeting is at 5pm
"message ahmed that I will be late" → send message ahmed I will be late
---
13. MULTIPLE TASKS
If the user asks multiple commands, return them separated by commas.
Example:
User query:
"open youtube and telegram"
Response:
open youtube, open telegram

User query:
"open whatsapp and send message to imran that we will go to bazar tomorrow"
Response:
open whatsapp, send message imran we will go to bazar tomorrow
---
14. EXIT COMMAND
If the user wants to end the conversation, respond with:
exit
Examples:
"bye jarvis"
"goodbye"
"stop"
---
15. UNKNOWN QUERY
If you cannot classify the query, respond with:
general (query)
---
Always follow these rules strictly.
"""


# Define a chat history with predefined user-chatbot interactions for context.
ChatHistory = [
    cohere.UserMessage(message="how are you?"),
    cohere.ChatbotMessage(message="general how are you?"),
    cohere.UserMessage(message="do you like pizza?"),
    cohere.ChatbotMessage(message="general do you like pizza?"),
    cohere.UserMessage(message="open chrome and tell me about imran khan."),
    cohere.ChatbotMessage(message="open chrome, general tell me about imran khan."),
    cohere.UserMessage(message="open chrome and firefox"),
    cohere.ChatbotMessage(message="open chrome, open firefox"),
    cohere.UserMessage(message="what is today's date and by the way remind me i have a dancing performance on 5th aug at 11pm"),
    cohere.ChatbotMessage(message="general what is today's date, reminder 11:00pm 5th aug dancing performance"),
    cohere.UserMessage(message="Chat with me."),
    cohere.ChatbotMessage(message="general chat with me."),
    cohere.UserMessage(message="send a message to imran that tomorrow we will go to bazar"),
    cohere.ChatbotMessage(message="send message imran tomorrow we will go to bazar"),
    cohere.UserMessage(message="open whatsapp and tell ahmed meeting is at 5pm"),
    cohere.ChatbotMessage(message="open whatsapp, send message ahmed meeting is at 5pm"),
    cohere.UserMessage(message="message ali that I will be late today"),
    cohere.ChatbotMessage(message="send message ali I will be late today"),
]

MAX_DMM_HISTORY = 50
REALTIME_HINTS = (
    "today",
    "current",
    "latest",
    "live",
    "weather",
    "news",
    "score",
    "stock",
    "price",
    "traffic",
    "time",
    "date",
)
SYSTEM_COMMANDS = {"mute", "unmute", "volume up", "volume down", "shutdown", "restart", "sleep"}


def _normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.strip().split())


def _split_commands(prompt: str) -> list[str]:
    normalized = _normalize_prompt(prompt)
    if not normalized:
        return []

    lowered = normalized.lower()
    command_indicators = (
        "open ",
        "close ",
        "play ",
        "send ",
        "message ",
        "whatsapp ",
        "youtube search",
        "google search",
        "generate image",
        "create image",
        "make image",
        "draw image",
        "system ",
        "launch ",
        "start ",
    )
    if not any(indicator in lowered for indicator in command_indicators):
        return [normalized]

    chunks = re.split(r"\s*(?:,| and then | then | and )\s*", normalized, flags=re.IGNORECASE)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def _is_realtime_query(query: str) -> bool:
    lowered = query.lower()
    return any(hint in lowered for hint in REALTIME_HINTS)


def _classify_single_command(command: str) -> str:
    lowered = command.lower().strip()
    if not lowered:
        return "general (empty)"

    if lowered in {"bye", "goodbye", "stop", "exit", "quit", "bye jarvis"}:
        return "exit"

    if lowered.startswith(("open ", "launch ", "start ")):
        target = command.split(maxsplit=1)[1].strip()
        return f"open {target}"

    if lowered.startswith(("close ", "stop app ")):
        target = command.split(maxsplit=1)[1].strip()
        return f"close {target}"

    if lowered.startswith("play "):
        return f"play {command.split(maxsplit=1)[1].strip()}"

    if lowered.startswith(("generate image", "create image", "make image", "draw image")):
        cleaned = re.sub(r"^(generate|create|make|draw)\s+image\s*(of|for)?\s*", "", command, flags=re.IGNORECASE).strip()
        return f"generate image {cleaned or command}"

    if lowered.startswith(("google search ", "search google for ")):
        cleaned = re.sub(r"^(google search|search google for)\s*", "", command, flags=re.IGNORECASE).strip()
        return f"google search {cleaned}"

    if lowered.startswith(("youtube search ", "search youtube for ")):
        cleaned = re.sub(r"^(youtube search|search youtube for)\s*", "", command, flags=re.IGNORECASE).strip()
        return f"youtube search {cleaned}"

    if lowered.startswith(("write ", "draft ", "create content ", "content ")):
        cleaned = re.sub(r"^(write|draft|create content|content)\s*", "", command, flags=re.IGNORECASE).strip()
        return f"content {cleaned or command}"

    message_match = re.match(
        r"^(?:send (?:a )?message to|message|whatsapp|tell)\s+([^\s]+)\s+(?:on whatsapp\s+)?(?:that\s+)?(.+)$",
        command,
        flags=re.IGNORECASE,
    )
    if message_match:
        contact = message_match.group(1).strip()
        message = message_match.group(2).strip()
        return f"send message {contact} {message}"

    if lowered.startswith("send message "):
        parts = command[13:].strip().split(maxsplit=1)
        if len(parts) == 2:
            return f"send message {parts[0]} {parts[1]}"

    for system_command in sorted(SYSTEM_COMMANDS, key=len, reverse=True):
        if lowered == system_command or lowered.startswith(f"system {system_command}"):
            return f"system {system_command}"

    if _is_realtime_query(lowered):
        return f"realtime ({command})"

    return f"general ({command})"


def _fallback_dmm(prompt: str) -> list[str]:
    tasks = [_classify_single_command(command) for command in _split_commands(prompt)]
    if not tasks:
        return [f"general ({prompt})"]
    return tasks


def _is_direct_command(tasks: list[str]) -> bool:
    """Return True if local classification produced only actionable commands
    (no 'general' or 'realtime' that would benefit from AI classification)."""
    return bool(tasks) and all(
        not t.startswith(("general ", "realtime ")) for t in tasks
    )


def FirstlayerDMM(prompt: str = "test") -> list[str]:
    # --- FAST PATH: try local classifier first ---
    # If the query is clearly a direct command (open, close, play, system, etc.)
    # the local classifier resolves it in <1ms -- no need for a network call.
    local_result = _fallback_dmm(prompt)
    if _is_direct_command(local_result):
        log.info("Fast-path DMM (local): %s", local_result)
        return local_result

    # --- SLOW PATH: ambiguous query, use Cohere for better classification ---
    if co is None:
        log.info("Cohere not available, using local result: %s", local_result)
        return local_result

    started = time.time()
    try:
        stream = co.chat_stream(
            model="command-r-08-2024",
            message=prompt,
            temperature=0.2,
            chat_history=ChatHistory,
            prompt_truncation="AUTO",
            connectors=[],
            preamble=preamble,
        )

        response_text = ""
        for event in stream:
            if time.time() - started > DMM_STREAM_TIMEOUT:
                log.warning("DMM streaming timed out after %ds, using local", DMM_STREAM_TIMEOUT)
                return local_result
            if event.event_type == "text-generation":
                response_text += event.text

        elapsed = time.time() - started
        log.info("DMM classified in %.1fs: %s", elapsed, response_text[:120])

        response_text = response_text.replace("\n", "")
        parts = [part.strip() for part in response_text.split(",")]

        filtered: list[str] = []
        for task in parts:
            for func in funcs:
                if task.startswith(func):
                    filtered.append(task)

        return filtered or local_result
    except Exception as e:
        elapsed = time.time() - started
        log.warning("Cohere DMM failed after %.1fs (%s), using local", elapsed, e)
        return local_result


if __name__ == "__main__":
    while True:
        print(FirstlayerDMM(input(">>> ")))
