import io
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from Backend.Assistant import Assistant
from Backend.Config import Config
from Backend.Services import Services
from Backend.EngineService import EngineService, validate_request, serve

class FakeSpeaker:
    def __init__(self, *args):
        self.speaking = threading.Event()
        self.say = Mock()
    def stop(self): pass
    def close(self): pass

class FakeVoice:
    def __init__(self, *args, **kwargs):
        self.enabled = threading.Event()
    def set_enabled(self, enabled, **kwargs):
        self.enabled.set() if enabled else self.enabled.clear()
    def close(self): pass

class EngineServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(Path(self.temp.name))
        assistant = Assistant(self.config, desktop=Mock(), brain=Mock())
        self.engine = EngineService(self.config, Mock(), start_workers=False,
            services=Services(self.config, assistant=assistant), voice_factory=FakeVoice, speaker_factory=FakeSpeaker)

    def tearDown(self):
        self.engine.close()
        self.temp.cleanup()

    def test_ipc_cannot_supply_identity_or_unknown_fields(self):
        for request in ({"op":"command","text":"hi","principal":"owner"},
                        {"op":"listen","enabled":"true"}, {"op":"snapshot","id":True},
                        {"op":"command"}, {"op":"shell","text":"anything"}):
            with self.assertRaises(ValueError):
                self.engine.handle(request)

    def test_emergency_cancels_queue_and_clears_confirmation(self):
        self.engine.submit("open notepad")
        queued = self.engine.tasks.queue[0][2]
        self.engine.assistant.pending = {"kind":"confirmation","expires":999999999999}
        self.engine.voice.set_enabled(True)
        self.engine.handle({"op":"emergency"})
        self.assertTrue(queued.event.is_set())
        self.assertTrue(self.engine.tasks.empty())
        self.assertIsNone(self.engine.assistant.pending)
        self.assertFalse(self.engine.voice.enabled.is_set())
        self.assertFalse(self.engine.busy.is_set())

    def test_native_completion_ticket_expires_and_cannot_replay(self):
        ticket = self.engine.handle({"op":"autostart_authorize","enabled":True})["ticket"]
        request = {"op":"autostart_result","ticket":ticket,"success":True}
        self.assertTrue(self.engine.handle(request)["recorded"])
        with self.assertRaises(ValueError): self.engine.handle(request)
        ticket = self.engine.handle({"op":"autostart_authorize","enabled":False})["ticket"]
        self.engine._native_requests[ticket] = (0,False)
        with self.assertRaises(ValueError):
            self.engine.handle({"op":"autostart_result","ticket":ticket,"success":False})

    def test_snapshot_truthfully_reports_unconfigured_authentication(self):
        state = self.engine.snapshot()
        self.assertFalse(state["security"]["owner_authenticated"])
        self.assertFalse(state["provider"]["online"])

    def test_audio_device_failure_does_not_disconnect_engine(self):
        with patch("Backend.EngineService.microphones", side_effect=RuntimeError("no device")):
            with self.assertRaises(RuntimeError):
                self.engine.handle({"op":"devices"})
        self.assertEqual(self.engine.handle({"op":"snapshot"})["security"]["mode"], "legacy_local")

    def test_stop_transport_does_not_wait_for_saturated_request_pool(self):
        release = threading.Event()
        observed = threading.Event()
        class SaturatedService:
            def __init__(self, *args): pass
            def handle(self, req):
                if req["op"] == "snapshot":
                    release.wait(1)
                elif req["op"] == "emergency":
                    observed.set()
                    release.set()
            def close(self): release.set()
        stream = io.StringIO(('{"op":"snapshot"}\n' * 16) + '{"op":"emergency"}\n{"op":"quit"}\n')
        with patch("Backend.EngineService.EngineService", SaturatedService), patch("sys.stdin", stream), patch("sys.stdout", io.StringIO()):
            serve(self.config)
        self.assertTrue(observed.is_set())
