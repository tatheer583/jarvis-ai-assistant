"""Shared text cleanup helpers for chat, search, STT, and GUI."""

from __future__ import annotations


def AnswerModifier(answer: str) -> str:
    """Drop empty lines from model answers."""
    lines = str(answer).split("\n")
    return "\n".join(line for line in lines if line.strip())


def QueryModifier(query: str) -> str:
    """Light cleanup only — preserve original casing/script for the LLM."""
    cleaned = " ".join(str(query).split()).strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        lowered = cleaned.lower()
        question_starters = (
            "how ", "what ", "why ", "when ", "where ", "who ", "which ",
            "is ", "are ", "can ", "could ", "would ", "should ", "do ", "does ", "did ",
            "kya ", "kyun ", "kab ", "kahan ", "kaun ",
        )
        cleaned += "?" if any(lowered.startswith(w) for w in question_starters) else "."
    return cleaned
