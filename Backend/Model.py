"""Compatibility entry points for the offline command classifier."""
import re
from Backend.Commands import parse_command, parse_commands

def _is_realtime_query(query: str) -> bool:
    return bool(re.search(r"\b(?:what time is it|current time|weather|latest|today's news|current price|live score)\b", query, re.I))

def _classify_single_command(command: str) -> str:
    cmd = parse_command(command)
    if cmd.action in {"time", "date"} or (cmd.action == "chat" and _is_realtime_query(command)):
        return f"realtime ({command})"
    if cmd.action in {"open", "close", "system", "content", "reminder"}:
        return f"{cmd.action} {cmd.target}"
    if cmd.action == "web":
        engine = cmd.options.get("engine", "")
        if command.casefold().startswith("play "):
            return "play " + cmd.target
        return ("youtube search " if engine == "youtube" else "google search ") + cmd.target
    if cmd.action == "image":
        return "generate image " + cmd.target
    if cmd.action == "message":
        match = re.match(r"^(?:send (?:a )?message to|message|whatsapp)\s+(\S+)\s+(?:that\s+)?(.+)$", command, re.I)
        return f"send message {match[1]} {match[2]}" if match else "general (" + command + ")"
    if cmd.action == "exit":
        return "exit"
    return f"general ({command})"

def _fallback_dmm(prompt: str) -> list[str]:
    # Share the robust clause splitter, then preserve the legacy string API.
    from Backend.Commands import clean
    pieces = re.split(r"\s+(?:and then|then|and)\s+(?=(?:open|close|launch|start|mute|unmute|volume|search|find|play|lock|shutdown|restart)\b)", clean(prompt), flags=re.I)
    if parse_command(prompt).action in {"note", "type", "reminder", "content", "message", "image", "chat"}:
        pieces = [prompt]
    return [_classify_single_command(piece) for piece in pieces]

def FirstlayerDMM(prompt: str = "help") -> list[str]:
    return _fallback_dmm(prompt)
