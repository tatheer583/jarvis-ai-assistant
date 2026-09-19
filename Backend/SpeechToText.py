"""Offline single-utterance compatibility wrapper. The desktop uses VoiceInput."""
from Backend.Config import Config
from Backend.VoiceInput import OfflineRecognizer

def SpeechRecognition() -> str:
    import sounddevice as sd
    import numpy as np
    config = Config()
    recognizer = OfflineRecognizer(config)
    recognizer.load()
    audio = sd.rec(16000 * 6, samplerate=16000, channels=1, dtype="float32", device=config.settings.microphone_device)
    sd.wait()
    return recognizer.transcribe(np.asarray(audio).reshape(-1))

def CloseDriver():
    pass
