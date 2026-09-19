"""Software contract tests. These do not verify biometric hardware or cloning."""
import datetime
import json
import threading
import queue
import io
import wave
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from Backend.Config import Config
from Backend.PersonalVoice import import_reference, delete_reference, record_reference, status
from Backend.VoiceOutput import VoiceOutput, startup_greeting


def test_startup_selects_current_engine_once_without_enabling_microphone(tmp_path):
    from Backend.Assistant import Assistant
    from Backend.EngineService import EngineService
    from Backend.Services import Services
    from scripts.tests.test_engine_service import FakeSpeaker, FakeVoice
    config = Config(tmp_path)
    config.update({'listen_on_startup': False, 'assistant_name': 'Friday', 'user_name': 'Owner'})
    assistant = Assistant(config, desktop=Mock(), brain=Mock())
    engine = EngineService(config, Mock(), start_workers=False,
        services=Services(config, assistant=assistant), voice_factory=FakeVoice, speaker_factory=FakeSpeaker)
    engine.refresh_index = Mock()
    try:
        engine.handle({'op': 'connect'})
        engine.handle({'op': 'connect'})
        engine.speaker.say.assert_called_once()
        assert 'Friday' in engine.speaker.say.call_args.args[0]
        assert not engine.voice.enabled.is_set()
        engine.stop(pause=True)
        assert engine._personal_cancel.is_set()
    finally:
        engine.close()


def test_missing_reference_blocks_generation_without_worker(tmp_path):
    config = Config(tmp_path)
    config.update({'voice_consent': True, 'voice_reference': str(tmp_path / 'missing.wav')})
    with patch('threading.Thread.start'):
        voice = VoiceOutput(config)
    with patch('subprocess.Popen') as worker, pytest.raises(ValueError):
        voice._pocket('Hello')
    worker.assert_not_called()


def wav_fixture(path):
    with wave.open(str(path), 'wb') as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes(b'\x00\x01' * 16000 * 4)


def test_explicit_consent_and_private_copy(tmp_path):
    config = Config(tmp_path / 'profile')
    original = tmp_path / 'input.wav'
    wav_fixture(original)
    with pytest.raises(ValueError, match='Confirm'):
        import_reference(config, original)
    import_reference(config, original, consent=True)
    assert status(config)['reference_ready']
    assert Path(config.settings.voice_reference).parent == config.directory / 'voice/recordings'
    assert Config(config.directory).settings.voice_consent
    delete_reference(config)
    assert original.is_file()
    assert not status(config)['reference_ready']
    assert config.settings.voice_provider == 'windows'


def test_invalid_reference_does_not_replace_recording(tmp_path):
    config = Config(tmp_path / 'profile')
    original = tmp_path / 'input.wav'
    wav_fixture(original)
    import_reference(config, original, consent=True)
    before = Path(config.settings.voice_reference).read_bytes()
    broken = tmp_path / 'broken.wav'
    broken.write_bytes(b'not audio')
    with pytest.raises(ValueError):
        import_reference(config, broken, consent=True)
    assert Path(config.settings.voice_reference).read_bytes() == before


def test_recording_requires_consent_before_opening_microphone(tmp_path):
    with patch('sounddevice.InputStream') as stream, pytest.raises(ValueError):
        record_reference(Config(tmp_path), threading.Event())
    stream.assert_not_called()


def test_greeting_uses_settings_and_time(tmp_path):
    config = Config(tmp_path)
    config.update({'assistant_name': 'Friday', 'user_name': 'Tatheer', 'voice_startup': True})
    assert startup_greeting(config.settings, datetime.datetime(2026, 1, 1, 14)) == 'Good afternoon, Tatheer. Friday is ready to help.'


def test_configuration_and_public_interface(tmp_path):
    with patch('threading.Thread.start'):
        voice = VoiceOutput(Config(tmp_path))
    voice.set_voice('pocket')
    voice.set_speed(2)
    voice.set_volume(35)
    loaded = Config(tmp_path)
    assert (loaded.settings.voice_provider, loaded.settings.voice_rate, loaded.settings.voice_volume) == ('pocket', 2, 35)
    assert voice.speak('test') and not voice.is_speaking()
    voice.stop()
    assert voice._queue.empty()
    with pytest.raises(ValueError):
        voice.set_voice('online')


def test_missing_personal_voice_falls_back_without_secret_leak(tmp_path, caplog):
    config = Config(tmp_path)
    config.update({'voice_provider': 'pocket'})
    with patch('threading.Thread.start'):
        voice = VoiceOutput(config, Mock())
    voice._pocket = Mock(side_effect=RuntimeError('secret-pin-value'))
    voice._windows = Mock(side_effect=lambda _: voice.closed.set())
    voice.say('Hello')
    with patch('Backend.VoiceOutput.time.sleep'):
        voice._run()
    voice._windows.assert_called_once_with('Hello')
    assert 'secret-pin-value' not in caplog.text + str(voice.on_status.call_args_list)


def test_stop_during_personal_failure_prevents_fallback(tmp_path):
    config = Config(tmp_path)
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


def test_stop_terminates_worker_and_clears_queue(tmp_path):
    with patch('threading.Thread.start'):
        voice = VoiceOutput(Config(tmp_path))
    voice._process = Mock()
    voice._process.pid = 99999999
    voice._process.poll.return_value = None
    voice.say('First', append=True)
    voice.say('Second', append=True)
    voice.stop()
    voice._process.terminate.assert_called_once()
    assert voice._queue.empty() and voice.cancelled.is_set()


def test_stop_terminates_windows_worker_child(tmp_path):
    from Backend.VoiceOutput import terminate_worker
    process = Mock(pid=123)
    process.poll.return_value = None
    child = Mock()
    with patch('psutil.Process') as factory:
        factory.return_value.children.return_value = [child]
        terminate_worker(process)
    child.terminate.assert_called_once()
    process.terminate.assert_called_once()


def test_personal_reference_without_consent_never_starts_worker(tmp_path):
    with patch('threading.Thread.start'):
        voice = VoiceOutput(Config(tmp_path))
    with patch('subprocess.Popen') as process, pytest.raises(RuntimeError, match='consent'):
        voice._pocket('Hello')
    process.assert_not_called()


def test_low_memory_does_not_start_model(tmp_path):
    config = Config(tmp_path / 'profile')
    original = tmp_path / 'input.wav'
    wav_fixture(original)
    import_reference(config, original, consent=True)
    with patch('threading.Thread.start'):
        voice = VoiceOutput(config)
    with patch('psutil.virtual_memory', return_value=Mock(available=1024)), patch('subprocess.Popen') as process:
        with pytest.raises(RuntimeError, match='RAM'):
            voice._pocket('Hello')
    process.assert_not_called()


def test_ready_worker_is_reused_between_replies(tmp_path):
    config = Config(tmp_path / 'profile')
    original = tmp_path / 'input.wav'
    wav_fixture(original)
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
    assert len(process.stdin.getvalue().splitlines()) == 2
    assert voice.model_state == 'loaded'


def test_worker_disables_outbound_network_without_opening_audio():
    import runpy
    worker = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'voice_worker.py'))
    with pytest.raises(RuntimeError, match='disabled'):
        worker['deny_network']()
