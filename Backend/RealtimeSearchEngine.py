import datetime
import logging
import time
from json import load, dump
from pathlib import Path

from ddgs import DDGS
from dotenv import dotenv_values
from groq import Groq

from Backend.Chatbot import ChatBot

log = logging.getLogger("Jarvis.Search")

# ---------------------------------------------------------------------------
# Path setup -- resolve project root so paths work regardless of cwd
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
CHAT_LOG_PATH = BASE_DIR / "Data" / "ChatLog.json"

# ---------------------------------------------------------------------------
# Environment & API client
# ---------------------------------------------------------------------------
env_vars = dotenv_values(str(ENV_PATH))

Username = env_vars.get("Username", "User")
AssistantName = env_vars.get("AssistantName", "Jarvis")
GroqAPIKey = env_vars.get("GroqAPIKey", "")

try:
    client = Groq(api_key=GroqAPIKey) if GroqAPIKey else None
except Exception as e:
    log.warning("Failed to initialize Groq client for search: %s", e)
    client = None

# ---------------------------------------------------------------------------
# System prompt -- strict instructions so the LLM always uses search data
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = f"""Hello, I am {Username}.

You are {AssistantName}, an advanced AI assistant with REAL-TIME web search capability.

CRITICAL RULES:
1. You WILL receive live web search results. Extract the FACTS and numbers from them.
2. NEVER say "I don't have real-time information" or "check this website" -- just give the answer directly.
3. Give the DIRECT answer FIRST in 1-2 sentences with the actual data/numbers/facts.
4. Do NOT list websites or tell the user to "check" somewhere. YOU already have the data -- just state it.
5. Do NOT repeat URLs or source links unless the user specifically asks for sources.
6. Keep answers SHORT -- 2-4 sentences maximum for simple questions.
7. For complex topics, use a brief summary (max 5-6 sentences).
8. NEVER start with "According to the search results provided" -- just state the facts naturally.
9. If the search results contain a specific number, price, date, or statistic -- include it in your answer.
"""

SYSTEM_CHATBOT = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "Hello! How can I assist you today?"},
]

# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------
CHAT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

messages: list[dict] = []

if CHAT_LOG_PATH.exists():
    try:
        with open(CHAT_LOG_PATH, "r", encoding="utf-8") as f:
            data = load(f)
            if isinstance(data, list):
                messages = data
    except Exception:
        messages = []
else:
    with open(CHAT_LOG_PATH, "w", encoding="utf-8") as f:
        dump([], f)


def _save_chat_log() -> None:
    with open(CHAT_LOG_PATH, "w", encoding="utf-8") as f:
        dump(messages[-100:], f, indent=2)


# ---------------------------------------------------------------------------
# Helper: clean up answer
# ---------------------------------------------------------------------------
def AnswerModifier(answer: str) -> str:
    lines = answer.split("\n")
    non_empty = [line for line in lines if line.strip()]
    return "\n".join(non_empty)


# ---------------------------------------------------------------------------
# Web Search with retries
# ---------------------------------------------------------------------------
def WebSearch(query: str, num_results: int = 5, retries: int = 2) -> list[dict[str, str]] | None:
    """Search the web via DuckDuckGo with automatic retries."""
    for attempt in range(retries + 1):
        try:
            results = list(DDGS().text(query, max_results=num_results))
            if not results:
                if attempt < retries:
                    time.sleep(1)
                    continue
                return None

            normalized_results: list[dict[str, str]] = []
            for item in results:
                normalized_results.append(
                    {
                        "title": str(item.get("title", "")).strip(),
                        "body": str(item.get("body", "")).strip(),
                        "href": str(item.get("href", "")).strip(),
                    }
                )
            return normalized_results
        except Exception as e:
            if attempt < retries:
                time.sleep(1)
                continue
            return None
    return None


def _search_context(query: str, results: list[dict[str, str]]) -> str:
    lines = [f"[LIVE SEARCH DATA for '{query}']:\n"]
    for idx, item in enumerate(results, 1):
        title = item.get("title", "")
        body = item.get("body", "")
        lines.append(f"{idx}. {title}: {body}\n")
    return "\n".join(lines)


def _fallback_search_answer(query: str, results: list[dict[str, str]] | None) -> str:
    if not results:
        return ChatBot(query)

    snippets = [item.get("body", "").strip() for item in results if item.get("body", "").strip()]
    titles = [item.get("title", "").strip() for item in results if item.get("title", "").strip()]
    combined = " ".join(snippets[:3]).strip()

    if combined:
        return AnswerModifier(combined)
    if titles:
        return AnswerModifier(". ".join(titles[:3]))
    return ChatBot(query)


# ---------------------------------------------------------------------------
# Real-time information
# ---------------------------------------------------------------------------
def Information() -> str:
    now = datetime.datetime.now()
    return (
        f"Current real-time information:\n"
        f"Day: {now.strftime('%A')}\n"
        f"Date: {now.strftime('%d %B %Y')}\n"
        f"Time: {now.strftime('%H:%M:%S')}\n"
    )


def _direct_realtime_answer(query: str) -> str | None:
    lowered = query.lower()
    now = datetime.datetime.now()

    if "time" in lowered:
        return f"The current time is {now.strftime('%I:%M %p')}."
    if "date" in lowered or "day" in lowered:
        return f"Today is {now.strftime('%A, %d %B %Y')}."
    return None


# ---------------------------------------------------------------------------
# Core: Realtime Search Engine
# ---------------------------------------------------------------------------
def RealtimeSearchEngine(query: str) -> str:
    """Answer a query using live web search results + Groq LLM."""
    global messages

    # Reload chat history to stay in sync.
    if CHAT_LOG_PATH.exists():
        try:
            with open(CHAT_LOG_PATH, "r", encoding="utf-8") as f:
                data = load(f)
                if isinstance(data, list):
                    messages = data
        except Exception:
            pass

    # 1. Gather context: real-time info + web search results.
    realtime_info = Information()
    direct_answer = _direct_realtime_answer(query)
    if direct_answer is not None:
        messages.append({"role": "user", "content": query})
        messages.append({"role": "assistant", "content": direct_answer})
        _save_chat_log()
        return direct_answer

    log.info("Searching the web for: %s", query)
    search_results = WebSearch(query)

    if search_results:
        log.info("Search complete -- found %d results", len(search_results))
        context_message = (
            f"{realtime_info}\n{_search_context(query, search_results)}\n\n"
            "Extract the key facts, numbers, and data from the search results above and give a direct, short answer."
        )
    else:
        log.info("Search returned no results -- using AI knowledge")
        context_message = f"{realtime_info}\n(Web search returned no results. Answer from your general knowledge.)"

    # 2. Build conversation for the LLM.
    conversation = (
        SYSTEM_CHATBOT
        + [{"role": "system", "content": context_message}]
        + messages[-20:]
        + [{"role": "user", "content": query}]
    )

    # 3. Call Groq API.
    answer = ""
    if client is not None:
        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=conversation,  # type: ignore
                max_tokens=512,
                temperature=0.5,
                top_p=1,
                stream=False,
            )

            if hasattr(completion, "choices") and completion.choices:
                msg = completion.choices[0].message
                if hasattr(msg, "content") and msg.content:
                    answer = msg.content
        except Exception as e:
            log.warning("Realtime Groq call failed, using fallback: %s", e)

    if not answer:
        answer = _fallback_search_answer(query, search_results)

    answer = answer.replace("</s>", "")
    answer = AnswerModifier(answer)

    # 4. Save to chat history.
    messages.append({"role": "user", "content": query})
    messages.append({"role": "assistant", "content": answer})
    _save_chat_log()

    return answer


# ---------------------------------------------------------------------------
# Standalone entry point for testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print(f"=== {AssistantName} Realtime Search Engine ===")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("Goodbye!")
            break

        response = RealtimeSearchEngine(user_input)
        print(f"\n{AssistantName}: {response}\n")
