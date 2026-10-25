"""Software contract tests. These do not verify biometric hardware or cloning."""
import datetime
import json
import logging
import threading
import queue
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

from Backend.Config import Config
from Backend.PersonalVoice import import_reference, delete_reference, record_reference, status
from Backend.VoiceOutput import VoiceOutput, startup_greeting


class PersonalVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_startup_selects_current_engine_once_without_enabling_microphone(self):
        from Backend.Assistant import Assistant
        from Backend.EngineService import EngineService
        from Backend.Services import Services
        from scripts.tests.test_engine_service import FakeSpeaker, FakeVoice
        config = Config(self.root)
        config.update({'listen_on_startup': False, 'assistant_name': 'Friday', 'user_name': 'Owner'})
        assistant = Assistant(config, desktop=Mock(), brain=Mock())
        engine = EngineService(config, Mock(), start_workers=False,
            services=Services(config, assistant=assistant), voice_factory=FakeVoice, speaker_factory=FakeSpeaker)
        engine.refresh_index = Mock()
        try:
            engine.handle({'op': 'connect'})
            engine.handle({'op': 'connect'})
            engine.speaker.say.assert_called_once()
            self.assertIn('Friday', engine.speaker.say.call_args.args[0])
            self.assertFalse(engine.voice.enabled.is_set())
            engine.stop(pause=True)
            self.assertTrue(engine._personal_cancel.is_set())
        finally:
            engine.close()

    def test_missing_reference_blocks_generation_without_worker(self):
        config = Config(self.root)
        config.update({'voice_consent': True, 'voice_reference': str(self.root / 'missing.wav')})
        with patch('threading.Thread.start'):
            voice = VoiceOutput(config)
        with patch('subprocess.Popen') as worker, self.assertRaises(ValueError):
            voice._pocket('Hello')
        worker.assert_not_called()

    def wav_fixture(self, path):
        with wave.open(str(path), 'wb') as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(16000)
            file.writeframes(b'\x00\x01' * 16000 * 4)

    def test_explicit_consent_and_private_copy(self):
        config = Config(self.root / 'profile')
        original = self.root / 'input.wav'
        self.wav_fixture(original)
        with self.assertRaisesRegex(ValueError, 'Confirm'):
            import_reference(config, original)
        import_reference(config, original, consent=True)
        self.assertTrue(status(config)['reference_ready'])
        self.assertEqual(Path(config.settings.voice_reference).parent, config.directory / 'voice/recordings')
        self.assertTrue(Config(config.directory).settings.voice_consent)
        delete_reference(config)
        self.assertTrue(original.is_file())
        self.assertFalse(status(config)['reference_ready'])
        self.assertEqual(config.settings.voice_provider, 'windows')

    def test_invalid_reference_does_not_replace_recording(self):
        config = Config(self.root / 'profile')
        original = self.root / 'input.wav'
        self.wav_fixture(original)
        import_reference(config, original, consent=True)
        before = Path(config.settings.voice_reference).read_bytes()
        broken = self.root / 'broken.wav'
        broken.write_bytes(b'not audio')
        with self.assertRaises(ValueError):
            import_reference(config, broken, consent=True)
        self.assertEqual(Path(config.settings.voice_reference).read_bytes(), before)

    def test_recording_requires_consent_before_opening_microphone(self):
        with patch('sounddevice.InputStream') as stream, self.assertRaises(ValueError):
            record_reference(Config(self.root), threading.Event())
        stream.assert_not_called()

    def test_greeting_uses_settings_and_time(self):
        config = Config(self.root)
        config.update({'assistant_name': 'Friday', 'user_name': 'Tatheer', 'voice_startup': True})
        self.assertEqual(startup_greeting(config.settings, datetime.datetime(2026, 1, 1, 14)),
                         'Good afternoon, Tatheer. Friday is ready to help.')

    def test_configuration_and_public_interface(self):
        with patch('threading.Thread.start'):
            voice = VoiceOutput(Config(self.root))
        voice.set_voice('pocket')
        voice.set_speed(2)
        voice.set_volume(35)
        loaded = Config(self.root)
        self.assertEqual((loaded.settings.voice_provider, loaded.settings.voice_rate, loaded.settings.voice_volume),
                         ('pocket', 2, 35))
        self.assertTrue(voice.speak('test'))
        self.assertFalse(voice.is_speaking())
        voice.stop()
        self.assertTrue(voice._queue.empty())
        with self.assertRaises(ValueError):
            voice.set_voice('online')

    def test_missing_personal_voice_falls_back_without_secret_leak(self):
        config = Config(self.root)
        config.update({'voice_provider': 'pocket'})
        with patch('threading.Thread.start'):
            voice = VoiceOutput(config, Mock())
        voice._pocket = Mock(side_effect=RuntimeError('secret-pin-value'))
        voice._windows = Mock(side_effect=lambda _: voice.closed.set())
        voice.say('Hello')
        captured = []

        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        logger = logging.getLogger('Jarvis.Speech')
        capture = Capture()
        logger.addHandler(capture)
        try:
            with patch('Backend.VoiceOutput.time.sleep'):
                voice._run()
        finally:
            logger.removeHandler(capture)
        voice._windows.assert_called_once_with('Hello')
        self.assertNotIn('secret-pin-value', "".join(captured) + str(voice.on_status.call_args_list))

    def test_stop_during_personal_failure_prevents_fallback(self):
        config = Config(self.root)
        config.update({'voice_provider': 'pocket'})
        with patch('threading.Thread.start'):
            voice = VoiceOutput(config)

        def fail(_):
            voice.stop()
            voice.closed.set()
            raise RuntimeError('cancelled')
        voice._pocket = fail
        voice._windows = Mock()
        voice.say('Hello')
        with patch('Backend.VoiceOutput.time.sleep'):
            voice._run()
        voice._windows.assert_not_called()

    def test_stop_terminates_worker_and_clears_queue(self):
        with patch('threading.Thread.start'):
            voice = VoiceOutput(Config(self.root))
        voice._process = Mock()
        voice._process.pid = 99999999
        voice._process.poll.return_value = None
        voice.say('First', append=True)
        voice.say('Second', append=True)
        voice.stop()
        voice._process.terminate.assert_called_once()
        self.assertTrue(voice._queue.empty() and voice.cancelled.is_set())

    def test_stop_terminates_windows_worker_child(self):
        from Backend.VoiceOutput import terminate_worker
        process = Mock(pid=123)
        process.poll.return_value = None
        child = Mock()
        with patch('psutil.Process') as factory:
            factory.return_value.children.return_value = [child]
            terminate_worker(process)
        child.terminate.assert_called_once()
        process.terminate.assert_called_once()

    def test_personal_reference_without_consent_never_starts_worker(self):
        with patch('threading.Thread.start'):
            voice = VoiceOutput(Config(self.root))
        with patch('subprocess.Popen') as process, self.assertRaisesRegex(RuntimeError, 'consent'):
            voice._pocket('Hello')
        process.assert_not_called()

    def test_low_memory_does_not_start_model(self):
        config = Config(self.root / 'profile')
        original = self.root / 'input.wav'
        self.wav_fixture(original)
        import_reference(config, original, consent=True)
        with patch('threading.Thread.start'):
            voice = VoiceOutput(config)
        with patch('psutil.virtual_memory', return_value=Mock(available=1024)), patch('subprocess.Popen') as process:
            with self.assertRaisesRegex(RuntimeError, 'RAM'):
                voice._pocket('Hello')
        process.assert_not_called()

    def test_ready_worker_is_reused_between_replies(self):
        config = Config(self.root / 'profile')
        original = self.root / 'input.wav'
        self.wav_fixture(original)
        import_reference(config, original, consent=True)
        from Backend.PersonalVoice import worker_python
        reference = Path(config.settings.voice_reference)
        with patch('threading.Thread.start'):
            voice = VoiceOutput(config)
        process = Mock(pid=123)
        process.poll.return_value = None
        process.stdin = io.StringIO()
        voice._process = process
        voice._worker_key = (str(worker_python(config)), '', str(reference), reference.stat().st_mtime_ns)
        voice._responses = queue.Queue()
        voice._responses.put({'ok': True})
        voice._responses.put({'ok': True})
        with patch('psutil.Process') as info, patch('subprocess.Popen') as spawn:
            info.return_value.children.return_value = []
            info.return_value.memory_info.return_value.rss = 1024
            voice._pocket('First sentence.')
            voice._pocket('Second sentence.')
            spawn.assert_not_called()
        self.assertEqual(len(process.stdin.getvalue().splitlines()), 2)
        self.assertEqual(voice.model_state, 'loaded')

    def test_worker_disables_outbound_network_without_opening_audio(self):
        import runpy
        worker = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'voice_worker.py'))
        with self.assertRaisesRegex(RuntimeError, 'disabled'):
            worker['deny_network']()


if __name__ == '__main__':
    unittest.main()
