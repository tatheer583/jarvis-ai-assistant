"""Local microphone capture, WebRTC VAD, Whisper transcription, and wake-word gating."""
from __future__ import annotations
import collections
import logging
import queue
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("Jarvis.Voice")
RATE, FRAME_MS = 16000, 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000

class SpeechSegmenter:
    def __init__(self, aggressiveness=2, minimum_speech_ms=350, silence_ms=850, *, neural=False):
        import webrtcvad
        self.vad = webrtcvad.Vad(aggressiveness)
        self.detector = None
        if neural:
            try:
                from Backend.SpeechDetector import SpeechDetector
                self.detector = SpeechDetector()
            except Exception:
                log.warning("Streaming speech detector unavailable; using WebRTC")
        self.minimum_speech_ms = minimum_speech_ms
        self.silence_ms = silence_ms
        self.noise_floor = 70.0
        self.reset()

    def reset(self):
        self.pre_roll = collections.deque(maxlen=10)
        self.recent = collections.deque(maxlen=5)
        self.frames = []
        self.voiced = 0
        self.silent = 0

    def feed(self, frame: bytes):
        import numpy as np
        if len(frame) != FRAME_SAMPLES * 2:
            return None
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(audio * audio)))
        if self.detector is not None:
            try:
                voiced = detected = self.detector.is_speech(frame)
            except Exception:
                log.warning("Streaming speech detector failed; using WebRTC")
                self.detector = None
        if self.detector is None:
            detected = self.vad.is_speech(frame, RATE)
            voiced = detected and rms >= max(100.0, self.noise_floor * 1.65)
        if not detected:
            self.noise_floor = min(1200.0, self.noise_floor * 0.98 + rms * 0.02)
        if not self.frames:
            self.pre_roll.append(frame)
            self.recent.append(voiced)
            if sum(self.recent) >= 3:
                self.frames = list(self.pre_roll)
                self.voiced = sum(self.recent) * FRAME_MS
            return None
        self.frames.append(frame)
        self.voiced += FRAME_MS if voiced else 0
        self.silent = 0 if voiced else self.silent + FRAME_MS
        if self.silent >= self.silence_ms or len(self.frames) * FRAME_MS >= 14000:
            result = b"".join(self.frames) if self.voiced >= self.minimum_speech_ms else None
            self.reset()
            return result
        return None

class WakeGate:
    def __init__(self):
        self.until = 0.0

    def accept(self, text: str, wake_word="jarvis", required=True, *, once=False, followup=False, now=None):
        now = time.monotonic() if now is None else now
        text = text.strip()
        words = [re.escape(wake_word.strip()), "jarvis", "jarvise", "jarvice", "جاروس", "جارویس", "جارویس"]
        pattern = r"^(?:(?:hey|hello|hi)\s+)?(?:" + "|".join(w for w in words if w) + r")(?:\b|(?=[\s،,.!?۔؟])|$)[\s،,:.!?۔؟]*"
        match = re.match(pattern, text, re.I)
        if match:
            text = text[match.end():].strip()
            if not text:
                self.until = now + 8
                return "__WAKE__"
            self.until = 0
            return text
        if once or not required or now < self.until:
            self.until = 0
            return text
        if followup:
            from Backend.Commands import parse_command
            if parse_command(text).action in {"choose", "confirm", "cancel"}:
                return text
        return ""

class OfflineRecognizer:
    def __init__(self, config):
        self.config = config
        self.model = None
        self.path = ""
        self.last_issue = ""
        self._lock = threading.Lock()

    def load(self):
        path = self.config.settings.whisper_path
        if not (Path(path) / "model.bin").is_file():
            raise RuntimeError("The offline speech model is missing. Open Settings and download local models.")
        with self._lock:
            if self.model is None or path != self.path:
                from faster_whisper import WhisperModel
                self.model = WhisperModel(path, device="cpu", compute_type="int8",
                                          cpu_threads=self.config.settings.llm_threads, local_files_only=True)
                self.path = path

    def transcribe(self, audio) -> str:
        self.load()
        language = self.config.settings.language
        with self._lock:
            self.last_issue = ""
            options = dict(beam_size=3, temperature=0.0,
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 350},
                condition_on_previous_text=False, no_speech_threshold=0.55,
                log_prob_threshold=-0.8, compression_ratio_threshold=2.2,
                initial_prompt="Jarvis. Open Notepad. Open Calculator. Open Paint. Open a file. Close a window. Press Control S. English and Urdu desktop commands.")
            segments, info = self.model.transcribe(audio,
                language=None if language == "auto" else language, **options)
            # Avoid decoding text from audio that the model's VAD completely rejected.
            if info.duration_after_vad <= 0:
                self._discard(segments)
                self.last_issue = "no_speech"
                return ""
            if language == "auto":
                selected = self._supported_language(info)
                if selected is None:
                    self._discard(segments)
                    self.last_issue = "uncertain_language"
                    return ""
                if selected != info.language:
                    # transcribe returns a lazy segment iterator. Discard it before decoding
                    # with the supported language, rather than executing unrelated-language text.
                    self._discard(segments)
                    segments, info = self.model.transcribe(audio, language=selected, **options)
            kept = [segment.text.strip() for segment in segments
                    if segment.no_speech_prob < 0.6 and segment.avg_logprob > -0.85
                    and segment.compression_ratio < 2.4]
            text = " ".join(kept).strip()
            if not text:
                self.last_issue = "unclear_speech"
            return text

    @staticmethod
    def _discard(segments):
        close = getattr(segments, "close", None)
        if close:
            close()

    @staticmethod
    def _supported_language(info):
        # Automatic in Settings means English + Urdu. Use the installed model's
        # actual probabilities; an ambiguous pair needs a repeat or fixed language.
        probabilities = dict(info.all_language_probs or [])
        probabilities.setdefault(info.language, info.language_probability)
        english, urdu = probabilities.get("en", 0.0), probabilities.get("ur", 0.0)
        total = english + urdu
        if total <= 0 or max(english, urdu) / total < 0.65:
            return None
        # A supported language should either lead overall or have meaningful model
        # support before a forced-language decode. Segment checks still apply.
        selected = "en" if english >= urdu else "ur"
        if info.language not in {"en", "ur"} and max(english, urdu) < 0.10:
            return None
        return selected


def microphones() -> list[dict]:
    import sounddevice as sd
    return [{"id": i, "name": device["name"]} for i, device in enumerate(sd.query_devices())
            if device["max_input_channels"] > 0]

class VoiceInput:
    def __init__(self, config, *, on_text, on_status, on_level, on_enabled, suppressed, followup):
        self.config = config
        self.on_text, self.on_status, self.on_level = on_text, on_status, on_level
        self.on_enabled = on_enabled
        self.suppressed, self.followup = suppressed, followup
        self.recognizer = OfflineRecognizer(config)
        self.gate = WakeGate()
        self.enabled = threading.Event()
        self.closed = threading.Event()
        self.once = False
        self._generation = 0
        self._resume_handsfree = False
        self._thread = threading.Thread(target=self._run, name="JarvisMicrophone", daemon=True)
        self._thread.start()

    def set_enabled(self, value: bool, *, once: bool = False):
        self._resume_handsfree = bool(value and once and self.enabled.is_set() and not self.once)
        self.once = once
        self._generation += 1
        if value:
            self.enabled.set()
        else:
            self.enabled.clear()
            self.gate.until = 0
        self.on_enabled(value)

    def _run(self):
        while not self.closed.is_set():
            if not self.enabled.wait(0.2):
                continue
            try:
                self.on_status("Loading offline speech recognition…")
                self.recognizer.load()
                if not self.enabled.is_set() or self.closed.is_set():
                    continue
                self._capture()
            except Exception as exc:
                log.exception("Microphone failed")
                self.on_status(str(exc))
                self.set_enabled(False)
            self.on_level(0)

    def _capture(self):
        import numpy as np
        import sounddevice as sd
        frames = queue.Queue(maxsize=80)
        def callback(indata, count, timing, status):
            if self.closed.is_set():
                return
            try:
                frames.put_nowait(bytes(indata))
            except queue.Full:
                # A bounded queue prevents delayed microphone commands from accumulating.
                try:
                    frames.get_nowait()
                    frames.put_nowait(bytes(indata))
                except (queue.Empty, queue.Full):
                    pass
        cfg = self.config.settings
        segmenter = SpeechSegmenter(cfg.vad_aggressiveness, cfg.minimum_speech_ms, cfg.silence_ms, neural=True)
        once_started = time.monotonic()
        generation = self._generation
        interrupted_segment = False
        with sd.RawInputStream(samplerate=RATE, blocksize=FRAME_SAMPLES, channels=1, dtype="int16",
                               device=cfg.microphone_device, callback=callback):
            self.on_status("Listening once…" if self.once else f"Listening for “{cfg.wake_word}”…")
            while self.enabled.is_set() and not self.closed.is_set() and generation == self._generation:
                if self.once and time.monotonic() - once_started > 20:
                    self.on_status("No command heard. Try Listen once again.")
                    self._finish_once()
                    break
                try:
                    frame = frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                interrupted_segment = interrupted_segment or self.suppressed()
                samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
                self.on_level(min(100, int(np.sqrt(np.mean(samples * samples)) / 80)))
                complete = segmenter.feed(frame)
                if complete is None:
                    if not segmenter.frames:
                        interrupted_segment = self.suppressed()
                    continue
                self.on_status("Recognizing locally…")
                text = self.recognizer.transcribe(np.frombuffer(complete, dtype=np.int16).astype(np.float32) / 32768.0)
                self._drain(frames)
                if segmenter.detector is not None:
                    segmenter.detector.reset()
                if not self.enabled.is_set() or self.closed.is_set() or generation != self._generation:
                    break
                if interrupted_segment or self.suppressed():
                    # While working/speaking, only an explicit wake-word stop can execute.
                    from Backend.Commands import parse_command
                    interrupt = WakeGate().accept(text, self.config.settings.wake_word, required=True)
                    if interrupt and parse_command(interrupt).action == "stop_speaking":
                        self.on_text(interrupt)
                    interrupted_segment = False
                    continue
                interrupted_segment = False
                if not text:
                    issue = self.recognizer.last_issue
                    self.on_status("I could not identify English or Urdu. Try again, or select your language in Settings."
                        if issue == "uncertain_language" else
                        "I could not hear a clear command. Move closer to the microphone and try again.")
                    continue
                accepted = self.gate.accept(text, self.config.settings.wake_word,
                                            self.config.settings.require_wake_word,
                                            once=self.once, followup=self.followup())
                if accepted == "__WAKE__":
                    self.on_status("Ready. Say your command.")
                elif accepted:
                    # Latch suppression before the next microphone frames can be accepted.
                    self.on_text(accepted)
                    if self.once:
                        self._finish_once()
                        break
                elif self.enabled.is_set():
                    self.on_status(f"Listening for “{self.config.settings.wake_word}”…")

    def _finish_once(self):
        resume = self._resume_handsfree
        self.set_enabled(resume)

    @staticmethod
    def _drain(frames):
        while True:
            try:
                frames.get_nowait()
            except queue.Empty:
                break

    def close(self):
        self.closed.set()
        self.enabled.clear()
        self._thread.join(timeout=2)
