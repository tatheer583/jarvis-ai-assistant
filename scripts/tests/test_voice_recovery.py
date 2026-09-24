import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from Backend.Config import Config
from Backend.VoiceInput import OfflineRecognizer, VoiceInput, WakeGate, FRAME_SAMPLES


def info(language="en", probability=.8, duration=1., probabilities=None):
    return SimpleNamespace(language=language, language_probability=probability,
        duration_after_vad=duration, all_language_probs=probabilities or [(language, probability)])


def segment(text="Jarvis, open notepad", logprob=-.2):
    return SimpleNamespace(text=text, no_speech_prob=.1, avg_logprob=logprob, compression_ratio=1.)


class RecognitionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.config=Config(Path(self.folder.name))
        self.recognizer=OfflineRecognizer(self.config)
        self.recognizer.load=Mock()
        self.recognizer.model=Mock()

    def tearDown(self):
        self.folder.cleanup()

    def test_empty_vad_never_decodes_hallucinated_words(self):
        def segments():
            self.fail("Must not decode VAD-rejected audio")
            yield segment()
        self.recognizer.model.transcribe.return_value=(segments(), info(duration=0))
        self.assertEqual(self.recognizer.transcribe(np.zeros(16000)), "")
        self.assertEqual(self.recognizer.last_issue, "no_speech")

    def test_supported_english_is_decoded_once(self):
        self.recognizer.model.transcribe.return_value=(iter([segment()]), info())
        self.assertEqual(self.recognizer.transcribe(np.zeros(16000)), "Jarvis, open notepad")
        self.recognizer.model.transcribe.assert_called_once()

    def test_automatic_mode_redecodes_with_supported_language(self):
        unrelated=Mock()
        self.recognizer.model.transcribe.side_effect=[
            (unrelated, info("nn", .29, probabilities=[("nn",.29),("en",.22),("ur",.01)])),
            (iter([segment()]), info())]
        self.assertEqual(self.recognizer.transcribe(np.zeros(16000)), "Jarvis, open notepad")
        unrelated.close.assert_called_once()
        self.assertEqual(self.recognizer.model.transcribe.call_args.kwargs["language"], "en")

    def test_ambiguous_or_unsupported_language_does_not_become_command(self):
        for probabilities in ([('en',.22),('ur',.20)], [('zh',.8),('en',.01),('ur',.01)]):
            iterator=Mock()
            self.recognizer.model.transcribe.return_value=(iterator, info("zh",.4,probabilities=probabilities))
            self.assertEqual(self.recognizer.transcribe(np.zeros(16000)), "")
            self.assertEqual(self.recognizer.last_issue, "uncertain_language")
            iterator.close.assert_called_once()

    def test_fixed_language_is_respected_and_short_clear_speech_is_kept(self):
        self.config.update({"language":"ur"},persist=False)
        self.recognizer.model.transcribe.return_value=(iter([segment("yes")]), info("ur",1.,duration=.2))
        self.assertEqual(self.recognizer.transcribe(np.zeros(16000)), "yes")
        self.assertEqual(self.recognizer.model.transcribe.call_args.kwargs["language"], "ur")

    def test_unclear_segments_are_not_submitted(self):
        self.recognizer.model.transcribe.return_value=(iter([segment(logprob=-2.)]), info())
        self.assertEqual(self.recognizer.transcribe(np.zeros(16000)), "")
        self.assertEqual(self.recognizer.last_issue, "unclear_speech")

    def test_emergency_during_model_loading_does_not_open_microphone(self):
        voice=VoiceInput.__new__(VoiceInput)
        voice.closed=threading.Event(); voice.enabled=threading.Event(); voice.enabled.set()
        voice.on_status=Mock(); voice.on_level=Mock(); voice._capture=Mock()
        voice.recognizer=Mock()
        def interrupted_load():
            voice.enabled.clear()
            voice.closed.set()
        voice.recognizer.load.side_effect=interrupted_load
        voice._run()
        voice._capture.assert_not_called()

    def test_result_from_old_listening_session_is_discarded(self):
        voice=VoiceInput.__new__(VoiceInput)
        voice.config=self.config; voice.closed=threading.Event(); voice.enabled=threading.Event(); voice.enabled.set()
        voice._generation=1; voice.once=False; voice._resume_handsfree=False
        voice.gate=WakeGate(); voice.suppressed=Mock(return_value=False); voice.followup=Mock(return_value=False)
        voice.on_status=Mock(); voice.on_text=Mock(); voice.on_level=Mock(); voice.on_enabled=Mock()
        voice.recognizer=Mock()
        def transcribe(_):
            voice.set_enabled(True,once=True)
            return "Jarvis, open notepad"
        voice.recognizer.transcribe.side_effect=transcribe
        def stream(**kwargs):
            kwargs['callback'](bytes(FRAME_SAMPLES*2),FRAME_SAMPLES,None,None)
            return MockContext()
        with patch('sounddevice.RawInputStream',side_effect=stream), patch('Backend.VoiceInput.SpeechSegmenter') as segmenter:
            segmenter.return_value.feed.return_value=bytes(FRAME_SAMPLES*2)
            voice._capture()
        voice.on_text.assert_not_called()


class MockContext:
    def __enter__(self): return self
    def __exit__(self,*args): pass
