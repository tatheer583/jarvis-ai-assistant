"""Offline command parsing in English, Roman Urdu and common Urdu phrases."""
from __future__ import annotations
import datetime as dt
import re
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Command:
    action: str
    target: str = ""
    options: dict = field(default_factory=dict)

SYSTEM = {"mute", "unmute", "volume up", "volume down", "shutdown", "restart", "sleep",
          "lock", "cancel shutdown", "play pause", "next track", "previous track", "show desktop"}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
                "twenty": 20, "thirty": 30, "sixty": 60, "ek": 1, "do": 2, "teen": 3, "panch": 5}

def clean(text: str, *, strip_punctuation: bool = True) -> str:
    text = " ".join(text.strip().split())
    text = re.sub(r"^(?:hey\s+)?(?:jarvis|jarvise|jarvice|جاروس|جارویس)[,\s:!]*", "", text, flags=re.I)
    text = re.sub(r"^(?:please|can you|could you|would you|براہ کرم)\s+", "", text, flags=re.I)
    return text.strip().rstrip(".?!۔؟") if strip_punctuation else text.strip()

def parse_command(text: str) -> Command:
    original = clean(text, strip_punctuation=False)
    text = clean(text)
    lower = text.casefold()
    exact = {
        "help": {"help", "what can you do", "show commands", "commands", "مدد"},
        "confirm": {"yes", "yes please", "confirm", "okay", "ok", "haan", "ji", "ہاں", "جی"},
        "cancel": {"no", "cancel", "never mind", "nahi", "نہیں", "منسوخ"},
        "stop_speaking": {"stop", "stop speaking", "be quiet", "chup", "خاموش"},
        "exit": {"exit", "quit", "bye", "goodbye", "quit jarvis", "exit jarvis"},
        "time": {"what time is it", "what is the time", "time", "current time", "tell me the time", "کتنا وقت ہوا ہے"},
        "date": {"date", "what is the date", "what is today's date", "what day is it", "today's date", "آج کیا تاریخ ہے"},
        "list_reminders": {"list reminders", "show reminders", "my reminders", "reminders"},
        "list_notes": {"show notes", "list notes", "my notes"},
        "reindex": {"refresh files", "rescan files", "index files", "refresh index"},
        "windows": {"list windows", "show windows", "what is open", "open windows"},
        "screenshot": {"take screenshot", "take a screenshot", "screenshot"},
        "status": {"status", "system status", "battery", "battery status"},
    }
    if not text:
        return Command("help")
    for action, phrases in exact.items():
        if lower in phrases:
            return Command(action)
    if lower in {"urdu mode", "switch to urdu", "urdu mein baat karo", "اردو موڈ", "اردو میں بات کرو"}:
        return Command("language", "ur")
    if lower in {"english mode", "switch to english", "english mein baat karo"}:
        return Command("language", "en")
    if lower in {"automatic language", "auto language", "bilingual mode"}:
        return Command("language", "auto")
    system = lower.removeprefix("system ").removeprefix("computer ")
    synonyms = {"turn up the volume": "volume up", "increase volume": "volume up", "awaz barhao": "volume up",
                "turn down the volume": "volume down", "decrease volume": "volume down", "awaz kam karo": "volume down",
                "lock screen": "lock", "shut down": "shutdown", "restart computer": "restart",
                "shutdown computer": "shutdown", "computer band karo": "shutdown", "آواز بند کرو": "mute",
                "آواز بڑھاؤ": "volume up", "آواز کم کرو": "volume down"}
    system = synonyms.get(system, system)
    if system in SYSTEM:
        return Command("system", system)
    from Backend.ControlCommands import parse_control
    control = parse_control(text)
    if control is not None:
        return control
    choice = re.fullmatch(r"(?:(?:open|choose|select|number|option)\s+)?(?:the\s+)?(\d+|first|second|third|fourth|fifth|one|two|three|four|five)(?:\s+(?:one|file))?", lower)
    if choice:
        values = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, **NUMBER_WORDS}
        raw = choice[1]
        return Command("choose", options={"index": int(raw) if raw.isdigit() else values[raw]})
    cancel = re.fullmatch(r"cancel reminder (\d+)", lower)
    if cancel:
        return Command("cancel_reminder", cancel[1])
    for pattern, action in [
        (r"^(?:remind me|set (?:a )?reminder|reminder)\s+(.+)$", "reminder"),
        (r"^(?:take (?:a )?note|save (?:a )?note|note|remember that)\s*[: ]\s*(.+)$", "note"),
        (r"^(?:type|dictate|write text)\s+(.+)$", "type"),
        (r"^(?:write|draft|create content|content)\s+(.+)$", "content"),
        (r"^(?:generate|create|make|draw)\s+(?:an? )?image(?: of| for)?\s+(.+)$", "image"),
    ]:
        match = re.match(pattern, original if action in {"note", "type", "content"} else text, re.I)
        if match:
            return Command(action, match[1])
    # Whisper can insert sentence pauses after a provider name. Only normalize
    # the command prefix; preserve the actual query, paths and dictated text.
    for engine in ("youtube", "google"):
        match = re.match(rf"^(?:search\s+(?:on\s+)?{engine}|{engine}\s+search)(?=$|[\s,.:])[\s,.:]*(?:for(?:\s+|$))?(.*)$", text, re.I)
        if match:
            query = match[1].strip()
            return Command("web", query, {"engine": engine}) if query else Command("open", engine)
    match = re.match(r"^play\s+(.+)$", text, re.I)
    if match:
        return Command("web", match[1], {"engine": "youtube"})
    match = re.match(r"^(?:search files(?: for)?|find files?|find|search(?: for)?)\s+(.+)$", text, re.I)
    if match:
        query = match[1]
        kind = re.match(r"^(pdf|document|image|video|audio|spreadsheet|presentation|folder|file)s?\s+(?:named |called |for )?(.+)$", query, re.I)
        if kind:
            return Command("find", kind[2], {"kind": kind[1].lower()})
        if lower.startswith(("find ", "find file", "search files")):
            return Command("find", query)
        return Command("web", query)
    match = re.match(r"^(?:open|launch|start)\s+(?:the |my )?(.+)$", text, re.I)
    if match:
        target = match[1]
        kind = re.match(r"^(file|folder|pdf|document|image|video|audio|spreadsheet|presentation)\s+(?:named |called )?(.+)$", target, re.I)
        return Command("open", kind[2] if kind else target, {"kind": kind[1].lower()} if kind else {})
    match = re.match(r"^(?:close|turn off|stop app|band karo)\s+(.+)$", text, re.I)
    if match:
        return Command("close", re.sub(r"^(?:file|the file)\s+", "", match[1], flags=re.I))
    match = re.match(r"^(.+?)\s+(?:khol(?:o| do)?|open karo|کھولو|کھول دو)$", text, re.I)
    if match:
        return Command("open", match[1])
    match = re.match(r"^(.+?)\s+(?:band karo|band kar do|بند کرو|بند کر دو)$", text, re.I)
    if match:
        return Command("close", match[1])
    match = re.match(r"^(.+?)\s+(?:talash karo|dhoondo|تلاش کرو)$", text, re.I)
    if match:
        return Command("find", match[1])
    if lower.startswith(("send message", "send a message", "whatsapp ", "message ")):
        return Command("message", text)
    return Command("chat", text)

def parse_commands(text: str) -> list[Command]:
    """Keep all text after dictation/note commands literal, including in a batch."""
    literal = {"note", "type", "reminder", "content", "message", "image", "chat", "file_action"}
    initial = parse_command(text)
    if initial.action in literal:
        return [initial]
    raw = clean(text, strip_punctuation=False)
    boundary = re.compile(r"\s+(?:and then|then|and)\s+(?=(?:open|close|launch|start|mute|unmute|volume|search|find|play|lock|shutdown|restart|press|type|click|scroll|minimize|maximize|focus|move|recycle|delete)\b)", re.I)
    commands, start = [], 0
    for match in boundary.finditer(raw):
        command = parse_command(raw[start:match.start()])
        if command.action in literal:
            break
        commands.append(command)
        start = match.end()
    commands.append(parse_command(raw[start:]))
    # Provider context lasts only within adjacent browser actions in this request.
    # "Open YouTube and search for X" must not silently switch to the default site.
    provider = None
    for command in commands:
        if command.action == "open" and not command.options.get("kind") and command.target.casefold() in {"google", "youtube"}:
            provider = command.target.casefold()
        elif command.action == "web":
            provider = command.options.get("engine") or provider
            if provider:
                command.options["engine"] = provider
        else:
            provider = None
    return commands

def reminder_details(payload: str, now: dt.datetime | None = None) -> tuple[str, dt.datetime]:
    now = now or dt.datetime.now()
    text = payload.strip()
    duration = re.search(r"\bin\s+([\d.]+|[a-z]+)\s+(seconds?|minutes?|hours?|days?)\b", text, re.I)
    if duration:
        raw = duration[1].lower()
        try:
            amount = float(raw) if re.fullmatch(r"[\d.]+", raw) else NUMBER_WORDS[raw]
        except (ValueError, KeyError):
            raise ValueError("Use a time like 'in 10 minutes'.")
        seconds = amount * {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[duration[2].lower().rstrip("s")]
        if not 1 <= seconds <= 366 * 86400:
            raise ValueError("Choose a reminder between one second and one year from now.")
        note = (text[:duration.start()] + " " + text[duration.end():]).strip()
        note = re.sub(r"^to\s+", "", note, flags=re.I).strip()
        if not note:
            raise ValueError("Tell me what to remind you about.")
        return note, now + dt.timedelta(seconds=seconds)
    clock = re.search(r"\b(?:at\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text, re.I)
    if clock:
        hour, minute = int(clock[1]), int(clock[2] or 0)
        marker = (clock[3] or "").lower()
        if minute > 59 or hour > (12 if marker else 23) or (marker and hour < 1):
            raise ValueError("That is not a valid time.")
        if marker:
            hour = hour % 12 + (12 if marker == "pm" else 0)
        due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if re.search(r"\btomorrow\b", text, re.I) or due <= now:
            due += dt.timedelta(days=1)
        note = (text[:clock.start()] + " " + text[clock.end():]).strip()
        note = re.sub(r"\b(?:tomorrow|today)\b", "", note, flags=re.I)
        note = re.sub(r"^to\s+", "", note.strip(), flags=re.I).strip()
        if not note:
            raise ValueError("Tell me what to remind you about.")
        return note, due
    raise ValueError("Include a time: 'remind me in 10 minutes to drink water' or 'remind me at 5 pm to call Ali'.")
