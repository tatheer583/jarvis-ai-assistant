"""Compatibility names for the local Windows/personal voice output."""
from Backend.Config import Config
from Backend.VoiceOutput import VoiceOutput
_output = None

def _speaker():
    global _output
    if _output is None:
        _output = VoiceOutput(Config())
    return _output

def TextToSpeechAsync(text, func=None):
    _speaker().say(text)
    return _speaker()._thread

def TextToSpeech(text, func=None):
    import time
    output = _speaker()
    output.say(text)
    time.sleep(0.1)
    while output.speaking.is_set() or not output._queue.empty():
        time.sleep(0.05)
    return True

def stop_speaking():
    if _output:
        _output.stop()

def is_speaking():
    return bool(_output and _output.speaking.is_set())
