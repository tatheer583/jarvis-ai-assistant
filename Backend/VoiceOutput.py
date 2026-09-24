"""Offline Windows speech and an optional local reference-voice worker."""
from __future__ import annotations
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("Jarvis.Speech")

def installed_voices() -> list[dict]:
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            return [{"id": token.Id, "name": token.GetDescription(), "language": token.GetAttribute("Language")}
                    for token in voice.GetVoices()]
        finally:
            voice = None
            pythoncom.CoUninitialize()
    except Exception as exc:
        log.warning("Could not list installed voices: %s", exc)
        return []

class VoiceOutput:
    def __init__(self, config, on_status=lambda text: None):
        self.config = config
        self.on_status = on_status
        self.speaking = threading.Event()
        self.cancelled = threading.Event()
        self.closed = threading.Event()
        self._queue = queue.Queue()
        self._process = None
        self._lock = threading.RLock()
        self._generation = 0
        self._thread = threading.Thread(target=self._run, name="JarvisSpeech", daemon=True)
        self._thread.start()

    def say(self, text: str, *, force=False, append=False):
        with self._lock:
            if self.closed.is_set() or (not self.config.settings.speech_enabled and not force):
                return False
            if not append:
                self.stop()
            self._queue.put((self._generation, text))
            return True

    def stop(self):
        with self._lock:
            self._generation += 1
            self.cancelled.set()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()

    def _run(self):
        while not self.closed.is_set():
            try:
                generation, text = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                if generation != self._generation or self.closed.is_set():
                    continue
                self.cancelled.clear()
                self.speaking.set()
            try:
                # Keep spoken answers manageable; full output stays in chat.
                spoken = text if len(text) < 650 else text[:600].rsplit(" ", 1)[0] + ". The full reply is in the chat."
                if self.config.settings.voice_provider == "pocket":
                    self._pocket(spoken)
                else:
                    self._windows(spoken)
            except Exception as exc:
                log.exception("Speech output failed")
                self.on_status(f"Voice unavailable: {exc}")
            finally:
                # Let speaker echo settle before the microphone resumes.
                time.sleep(0.25)
                self.speaking.clear()

    def _windows(self, text):
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            cfg = self.config.settings
            speaker.Rate, speaker.Volume = cfg.voice_rate, cfg.voice_volume
            for voice in speaker.GetVoices():
                if cfg.voice_id and voice.Id == cfg.voice_id:
                    speaker.Voice = voice
                    break
            with self._lock:
                if self.cancelled.is_set() or self.closed.is_set():
                    return
                speaker.Speak(text, 1 | 16)  # async, literal text (not XML)
            while not speaker.WaitUntilDone(50):
                if self.cancelled.is_set() or self.closed.is_set():
                    speaker.Speak("", 2)
                    break
        finally:
            speaker = None
            voice = None
            pythoncom.CoUninitialize()

    def _pocket(self, text):
        reference = Path(self.config.settings.voice_reference)
        if not reference.is_file():
            raise RuntimeError("Record or choose your voice sample in Settings first.")
        if any("\u0600" <= ch <= "\u06ff" for ch in text):
            raise RuntimeError("The personal voice model currently supports English, not Urdu. Choose a Windows Urdu voice for Urdu output.")
        payload = json.dumps({"text": text, "reference": str(reference), "directory": str(self.config.directory)})
        worker = Path(__file__).resolve().parent.parent / "scripts/voice_worker.py"
        process = subprocess.Popen([sys.executable, "-X", "utf8", str(worker)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._process = process
        try:
            _, error = process.communicate(payload, timeout=180)
            if process.returncode and not self.cancelled.is_set():
                raise RuntimeError(error.strip()[-350:] or "Install the optional local voice model in Settings.")
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("Personal voice generation timed out.")
        finally:
            self._process = None

    def close(self):
        self.closed.set()
        self.stop()
        self._thread.join(timeout=2)
