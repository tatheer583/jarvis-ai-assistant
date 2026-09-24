"""Streaming/cancellation regressions: no microphone, real actions or network."""
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from Backend.AIProviders import LocalProvider, AIOrchestrator
from Backend.Assistant import Assistant
from Backend.ActionResult import ActionResult
from Backend.Config import Config
from Backend.EngineService import EngineService
from Backend.Events import Event, EventBus
from Backend.LocalBrain import LocalBrain
from Backend.ReplyStream import VisibleReply, spoken_boundary
from Backend.Services import Services
from Backend.Tasks import CancellationToken, cancellation_scope, Cancelled
from Backend.VoiceInput import SpeechSegmenter, FRAME_SAMPLES
from Backend.VoiceOutput import VoiceOutput
from scripts.tests.test_engine_service import FakeSpeaker, FakeVoice


def delta(text):
    return {"choices": [{"delta": {"content": text}}]}

class StreamTests(unittest.TestCase):
    def test_split_thought_tags_never_reach_output(self):
        text = "<think>private reasoning</think>Visible answer."
        for split in range(len(text)):
            observed = []
            stream = VisibleReply(observed.append)
            stream.feed(text[:split]); stream.feed(text[split:])
            self.assertEqual(stream.finish(), "Visible answer.")
            self.assertEqual("".join(observed), "Visible answer.")

    def test_unclosed_thought_is_never_disclosed(self):
        seen=[]; stream=VisibleReply(seen.append)
        for chunk in ("<thi", "nk>do not show this"):
            stream.feed(chunk)
        self.assertEqual(stream.finish(), "")
        self.assertEqual(seen, [])

    def test_sentence_boundary_avoids_decimal_and_supports_urdu(self):
        self.assertEqual(spoken_boundary("Value 3.14"), 0)
        self.assertEqual(spoken_boundary("Hello. Next"), 7)
        self.assertEqual(spoken_boundary("ٹھیک ہے۔ اگلا"), 9)

    def test_local_model_delivers_output_before_generation_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            brain=LocalBrain(Config(Path(folder)))
            brain.ready=Mock(return_value=True)
            brain._model=Mock(); brain._loaded_path=brain.config.settings.llm_path
            seen=[]
            def generate(**kwargs):
                self.assertEqual(kwargs["max_tokens"], 160)
                yield delta("<think>hidden</think>First sentence. ")
                self.assertEqual(seen, ["First sentence. "])
                yield delta("Second sentence.")
            brain._model.create_chat_completion.side_effect=generate
            with patch.dict("sys.modules", {"llama_cpp":SimpleNamespace(Llama=Mock())}):
                self.assertEqual(brain.reply("Explain RAM",on_delta=seen.append), "First sentence. Second sentence.")

    def test_cancellation_during_stream_has_no_late_output(self):
        with tempfile.TemporaryDirectory() as folder:
            brain=LocalBrain(Config(Path(folder))); brain.ready=Mock(return_value=True)
            brain._model=Mock(); brain._loaded_path=brain.config.settings.llm_path
            token=CancellationToken(); seen=[]
            def generate(**kwargs):
                yield delta("First. ")
                token.cancel()
                yield delta("Must not appear.")
            brain._model.create_chat_completion.side_effect=generate
            with patch.dict("sys.modules", {"llama_cpp":SimpleNamespace(Llama=Mock())}), cancellation_scope(token):
                with self.assertRaises(Cancelled): brain.reply("Explain RAM",on_delta=seen.append)
            self.assertEqual(seen, ["First. "])

    def test_brief_reply_stops_at_sentence_boundary_and_closes_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            brain=LocalBrain(Config(Path(folder))); brain.ready=Mock(return_value=True)
            brain._model=Mock(); brain._loaded_path=brain.config.settings.llm_path
            closed=[]; seen=[]
            def generate(**kwargs):
                try:
                    yield delta("First sentence. Second sentence. ")
                    self.fail("Unneeded tokens must not be generated")
                finally: closed.append(True)
            brain._model.create_chat_completion.side_effect=generate
            with patch.dict("sys.modules", {"llama_cpp":SimpleNamespace(Llama=Mock())}):
                self.assertEqual(brain.reply("Explain RAM",on_delta=seen.append),"First sentence. Second sentence.")
            self.assertEqual(closed,[True])

    def test_detailed_request_keeps_long_output_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            brain=LocalBrain(Config(Path(folder))); brain.ready=Mock(return_value=True)
            brain._model=Mock(); brain._loaded_path=brain.config.settings.llm_path
            def generate(**kwargs):
                self.assertEqual(kwargs["max_tokens"],384)
                yield delta("One. Two. Three. Four.")
            brain._model.create_chat_completion.side_effect=generate
            with patch.dict("sys.modules", {"llama_cpp":SimpleNamespace(Llama=Mock())}):
                self.assertEqual(brain.reply("Write a detailed explanation"),"One. Two. Three. Four.")

    def test_simple_answers_do_not_load_model(self):
        with tempfile.TemporaryDirectory() as folder:
            brain=LocalBrain(Config(Path(folder))); seen=[]
            self.assertEqual(brain.reply("calculate 2+2",on_delta=seen.append), "The answer is 4.")
            self.assertIsNone(brain._model)
            self.assertEqual(seen, ["The answer is 4."])

    def test_failed_online_reply_does_not_mix_into_local_stream(self):
        local, online=Mock(),Mock(); online.ready.return_value=True
        online.reply.side_effect=RuntimeError("private token"); seen=[]
        def reply(text,history,*,on_delta):
            on_delta("Local response."); return "Local response."
        local.reply.side_effect=reply
        answer=AIOrchestrator(local,online=online,online_enabled=True).reply("Question",on_delta=seen.append)
        self.assertEqual(answer,"Local response."); self.assertEqual(seen,["Local response."])

class EngineStreamTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.config=Config(Path(self.folder.name))
        self.events=EventBus(); provider=LocalProvider(self.config)
        self.brain=provider.brain; self.brain.ready=Mock(return_value=True)
        self.brain._model=Mock(); self.brain._loaded_path=self.config.settings.llm_path
        assistant=Assistant(self.config,desktop=Mock(),brain=AIOrchestrator(provider,events=self.events),events=self.events)
        self.emit=Mock()
        self.engine=EngineService(self.config,self.emit,start_workers=False,
            services=Services(self.config,assistant=assistant,events=self.events),voice_factory=FakeVoice,speaker_factory=FakeSpeaker)
        self.engine.speaker.say.return_value=True

    def tearDown(self):
        self.engine.close(); self.folder.cleanup()

    def run_reply(self,generator):
        self.brain._model.create_chat_completion.side_effect=generator
        self.engine._active_token=CancellationToken()
        with patch.dict("sys.modules", {"llama_cpp":SimpleNamespace(Llama=Mock())}):
            result=self.engine.services.execute("Explain computer memory",token=self.engine._active_token)
        self.engine._speak_result(result,self.engine._active_token)
        return result

    def test_first_sentence_spoken_early_then_remainder_without_duplicate(self):
        def generate(**kwargs):
            yield delta("Memory holds working data. ")
            self.engine.speaker.say.assert_called_once_with("Memory holds working data.",append=True)
            self.assertTrue(any(call.args[0]=="reply_progress" for call in self.emit.call_args_list))
            yield delta("RAM is temporary.")
        result=self.run_reply(generate)
        self.assertTrue(result.success)
        self.assertEqual([c.args[0] for c in self.engine.speaker.say.call_args_list],
                         ["Memory holds working data.","RAM is temporary."])
        self.assertEqual(self.engine.assistant.store.history(1)[0]["content"],result.message)

    def test_stop_during_generation_blocks_remaining_speech_and_deltas(self):
        def generate(**kwargs):
            yield delta("First sentence. ")
            self.engine.stop(pause=True)
            yield delta("Late text.")
        result=self.run_reply(generate)
        self.assertFalse(result.success)
        self.assertEqual(self.engine.speaker.say.call_count,1)
        self.assertNotIn("Late text",str(self.emit.call_args_list))

    def test_mismatched_task_delta_is_ignored(self):
        self.engine._active_token=CancellationToken()
        self.engine.assistant.current_task=SimpleNamespace(id="current")
        self.engine._on_event(Event("reply_delta",{"task_id":"old","text":"Ignore me."}))
        self.engine.speaker.say.assert_not_called()
        self.emit.assert_not_called()

class VoiceQueueTests(unittest.TestCase):
    def test_stopped_dequeued_sentence_cannot_restart(self):
        with tempfile.TemporaryDirectory() as folder, patch("threading.Thread.start"):
            speaker=VoiceOutput(Config(Path(folder)))
        stale_generation=speaker._generation
        speaker.stop()
        # Simulate a sentence dequeued concurrently with Stop.
        class StaleQueue:
            taken = False
            def get(self,**kwargs):
                if self.taken:
                    speaker.closed.set()
                    raise queue.Empty
                self.taken = True
                return stale_generation,"stale audio"
        speaker._queue=StaleQueue(); speaker._windows=Mock()
        speaker._run()
        speaker._windows.assert_not_called()
        self.assertTrue(speaker.cancelled.is_set())

    def test_append_keeps_order_and_stop_removes_entire_reply(self):
        with tempfile.TemporaryDirectory() as folder, patch("threading.Thread.start"):
            speaker=VoiceOutput(Config(Path(folder)))
        speaker.say("First.",append=True); speaker.say("Second.",append=True)
        self.assertEqual([item[1] for item in speaker._queue.queue],["First.","Second."])
        speaker.stop(); self.assertTrue(speaker._queue.empty())

class SpeechDetectionTests(unittest.TestCase):
    def test_neural_failure_falls_back_to_existing_detector(self):
        with patch("Backend.SpeechDetector.SpeechDetector",side_effect=RuntimeError("missing model")):
            segmenter=SpeechSegmenter(neural=True)
        self.assertIsNone(segmenter.detector)
        self.assertIsNone(segmenter.feed(bytes(FRAME_SAMPLES*2)))

    def test_neural_detector_ends_on_silence_without_cutting_long_speech(self):
        with patch("Backend.SpeechDetector.SpeechDetector") as factory:
            factory.return_value.is_speech.return_value=True
            segmenter=SpeechSegmenter(neural=True)
            frame=np.full(FRAME_SAMPLES,1000,dtype=np.int16).tobytes()
            for _ in range(260): self.assertIsNone(segmenter.feed(frame))  # 7.8 s uninterrupted
            factory.return_value.is_speech.return_value=False
            completed=[segmenter.feed(bytes(FRAME_SAMPLES*2)) for _ in range(35)]
            self.assertEqual(sum(chunk is not None for chunk in completed),1)
            self.assertGreater(len(next(chunk for chunk in completed if chunk))/32000,7.8)

    def test_real_bundled_detector_rejects_noise_offline(self):
        with patch("socket.socket.connect",side_effect=AssertionError("network forbidden")):
            segmenter=SpeechSegmenter(neural=True)
            self.assertIsNotNone(segmenter.detector)
            rng=np.random.default_rng(42)
            for _ in range(100):
                noise=rng.integers(-1500,1500,FRAME_SAMPLES,dtype=np.int16).tobytes()
                self.assertIsNone(segmenter.feed(noise))
