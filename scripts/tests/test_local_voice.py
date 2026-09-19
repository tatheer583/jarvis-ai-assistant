"""Noise, wake-word and local-model safeguards; no microphone is opened."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from Backend.Config import Config
from Backend.VoiceInput import SpeechSegmenter, WakeGate, OfflineRecognizer, FRAME_SAMPLES

class VoiceTests(unittest.TestCase):
    def test_background_speech_without_wake_word_is_rejected(self):
        gate = WakeGate()
        self.assertEqual(gate.accept("open notepad"), "")
        self.assertEqual(gate.accept("a discussion about Jarvis and files"), "")
        self.assertEqual(gate.accept("Jarvisian open notepad"), "")
        self.assertEqual(gate.accept("Jarvis, open notepad"), "open notepad")

    def test_wake_word_followup_window_and_confirmation(self):
        gate = WakeGate()
        self.assertEqual(gate.accept("Jarvis", now=10), "__WAKE__")
        self.assertEqual(gate.accept("open notepad", now=11), "open notepad")
        self.assertEqual(gate.accept("open notepad", now=12), "")
        self.assertEqual(gate.accept("yes", followup=True), "yes")
        self.assertEqual(gate.accept("shutdown", followup=True), "")

    def test_listen_once_does_not_need_wake_word(self):
        self.assertEqual(WakeGate().accept("open notepad", once=True), "open notepad")

    def test_silence_and_low_level_noise_never_form_a_command(self):
        segmenter = SpeechSegmenter()
        rng = np.random.default_rng(17)
        for _ in range(100):
            self.assertIsNone(segmenter.feed(bytes(FRAME_SAMPLES * 2)))
            noise = rng.integers(-15, 15, FRAME_SAMPLES, dtype=np.int16).tobytes()
            self.assertIsNone(segmenter.feed(noise))

    def test_short_impulse_is_rejected_and_speech_is_segmented(self):
        segmenter = SpeechSegmenter(minimum_speech_ms=350, silence_ms=600)
        frame = np.full(FRAME_SAMPLES, 1000, dtype=np.int16).tobytes()
        with patch.object(segmenter.vad, "is_speech", return_value=True):
            for _ in range(4):
                self.assertIsNone(segmenter.feed(frame))
        for _ in range(30):
            self.assertIsNone(segmenter.feed(bytes(FRAME_SAMPLES * 2)))
        results = []
        with patch.object(segmenter.vad, "is_speech", return_value=True):
            for _ in range(20):
                results.append(segmenter.feed(frame))
        for _ in range(25):
            results.append(segmenter.feed(bytes(FRAME_SAMPLES * 2)))
        self.assertEqual(sum(x is not None for x in results), 1)

    def test_missing_speech_model_does_not_open_network(self):
        with tempfile.TemporaryDirectory() as folder:
            recognizer = OfflineRecognizer(Config(Path(folder)))
            with patch("socket.socket.connect", side_effect=AssertionError("No network allowed")):
                with self.assertRaises(RuntimeError):
                    recognizer.load()

if __name__ == "__main__":
    unittest.main()
