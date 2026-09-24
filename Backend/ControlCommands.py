"""Deterministic voice grammar for Windows input; no model generates executable code."""
import re
from Backend.Commands import Command

SHORTCUTS = {
    "copy": "ctrl c", "copy that": "ctrl c", "paste": "ctrl v", "paste that": "ctrl v",
    "cut": "ctrl x", "undo": "ctrl z", "redo": "ctrl y", "select all": "ctrl a",
    "save": "ctrl s", "save file": "ctrl s", "save as": "ctrl shift s",
    "new tab": "ctrl t", "close tab": "ctrl w", "reopen tab": "ctrl shift t",
    "next tab": "ctrl tab", "previous tab": "ctrl shift tab", "refresh page": "ctrl r",
    "address bar": "ctrl l", "go back": "alt left", "go forward": "alt right",
    "zoom in": "ctrl plus", "zoom out": "ctrl minus", "reset zoom": "ctrl 0",
    "page down": "pagedown", "page up": "pageup", "go to top": "ctrl home",
    "go to bottom": "ctrl end", "switch window": "alt tab", "switch app": "alt tab",
    "task view": "win tab", "start menu": "win", "open start menu": "win",
    "new folder": "ctrl shift n", "rename selected": "f2", "find on page": "ctrl f",
    "enter": "enter", "escape": "escape", "tab": "tab", "backspace": "backspace",
}

def parse_control(text):
    lower = text.casefold().strip().rstrip('.?!')
    if lower in SHORTCUTS:
        return Command('keys', SHORTCUTS[lower])
    if lower in {'pause listening', 'stop listening', 'microphone off', 'deactivate jarvis'}:
        return Command('pause_listening')
    if lower in {'show jarvis', 'show assistant', 'hide jarvis', 'hide assistant'}:
        return Command('interface', 'hide' if lower.startswith('hide') else 'show')
    if lower in {'show grid', 'mouse grid', 'show mouse grid', 'hide grid', 'cancel grid'}:
        return Command('grid', 'hide' if lower.startswith(('hide', 'cancel')) else 'show')
    match = re.fullmatch(r'(zoom|click|double click|right click)\s+(?:grid\s+)?([1-9]|one|two|three|four|five|six|seven|eight|nine)', lower)
    if match:
        numbers = dict(zip('one two three four five six seven eight nine'.split(), range(1, 10)))
        return Command('grid', match[1], {'cell': int(match[2]) if match[2].isdigit() else numbers[match[2]]})
    if lower in {'click', 'left click', 'double click', 'right click', 'middle click'}:
        return Command('mouse', lower)
    match = re.fullmatch(r'(?:move (?:the )?(?:mouse|pointer)|mouse)\s+(up|down|left|right)\s*(\d+)?(?:\s+pixels?)?', lower)
    if match:
        return Command('mouse', 'move', {'direction': match[1], 'amount': int(match[2] or 100)})
    match = re.fullmatch(r'(?:move (?:the )?(?:mouse|pointer) to|mouse to)\s+(-?\d+)\s*[, ]\s*(-?\d+)', lower)
    if match:
        return Command('mouse', 'position', {'x': int(match[1]), 'y': int(match[2])})
    if lower in {'center mouse', 'centre mouse', 'center pointer'}:
        return Command('mouse', 'center')
    match = re.fullmatch(r'scroll\s+(up|down|left|right)(?:\s+(\d+)(?:\s+(?:steps?|times?))?)?', lower)
    if match:
        return Command('mouse', 'scroll', {'direction': match[1], 'amount': int(match[2] or 3)})
    match = re.fullmatch(r'(?:press|hold shortcut)\s+(.+?)(?:\s+(\d+)\s+times)?', lower)
    if match:
        return Command('keys', match[1], {'count': int(match[2] or 1)})
    match = re.fullmatch(r'(?:set )?volume(?: to)?\s+(\d{1,3})(?:\s*(?:percent|%))?', lower)
    if match:
        return Command('volume', match[1])
    match = re.fullmatch(r'(minimize|maximize|restore|focus|switch to|snap left|snap right)(?:\s+(?:the\s+)?(.+))?', text, re.I)
    if match:
        operation = match[1].lower()
        return Command('window', match[2] or 'current window', {'operation': 'focus' if operation == 'switch to' else operation})
    match = re.fullmatch(r'click\s+(?:the\s+)?(?:button\s+)?(.+?)(?:\s+button)?', text, re.I)
    if match:
        return Command('click_control', match[1])
    match = re.fullmatch(r'(?:create|make)\s+(?:a\s+)?(folder|file)\s+(?:named\s+)?(.+?)(?:\s+in\s+(.+))?', text, re.I)
    if match:
        return Command('file_action', match[2].strip('"'), {'operation': 'create_' + match[1].lower(), 'destination': (match[3] or 'desktop').strip('"')})
    match = re.fullmatch(r'(copy|move|rename)\s+(?:file|folder)\s+(.+?)\s+to\s+(.+)', text, re.I)
    if match:
        return Command('file_action', match[2].strip('"'), {'operation': match[1].lower(), 'destination': match[3].strip('"')})
    match = re.fullmatch(r'(?:recycle|delete)\s+(?:file\s+|folder\s+)?(.+)', text, re.I)
    if match:
        return Command('file_action', match[1].strip('"'), {'operation': 'recycle'})
    return None
