_current_mode = "english"

URDU_SWITCH_PHRASES = {"urdu mode", "switch to urdu", "urdu mein baat karo"}
ENGLISH_SWITCH_PHRASES = {"english mode", "switch to english", "english mein baat karo"}


def get_mode() -> str:
    return _current_mode


def set_mode(mode: str) -> None:
    global _current_mode
    _current_mode = mode.lower().strip()


def is_urdu_mode() -> bool:
    return _current_mode == "urdu"


def get_recognition_language() -> str:
    return "ur-PK" if _current_mode == "urdu" else "en"


def detect_mode_switch(query: str):
    normalized = query.lower().strip().rstrip(".?!")
    if normalized in URDU_SWITCH_PHRASES or "urdu mode" in normalized:
        return "urdu"
    if normalized in ENGLISH_SWITCH_PHRASES or "english mode" in normalized:
        return "english"
    return None
