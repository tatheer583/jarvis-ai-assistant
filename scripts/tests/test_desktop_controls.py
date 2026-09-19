"""Behavior tests for desktop commands; never sends input to real applications."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from Backend.ActionResult import ActionResult
from Backend.Assistant import Assistant
from Backend.Commands import parse_command, parse_commands
from Backend.Config import Config
from Backend.InputControls import key_codes
from Backend.VoiceInput import VoiceInput

class GrammarTests(unittest.TestCase):
    def test_desktop_command_families(self):
        cases = {
            'press control shift s': ('keys', 'control shift s'),
            'copy': ('keys', 'ctrl c'), 'new tab': ('keys', 'ctrl t'),
            'move mouse right 100': ('mouse', 'move'), 'scroll down 3': ('mouse', 'scroll'),
            'click': ('mouse', 'click'), 'click the Save button': ('click_control', 'Save'),
            'show grid': ('grid', 'show'), 'zoom five': ('grid', 'zoom'),
            'click three': ('grid', 'click'), 'set volume to 40 percent': ('volume', '40'),
            'maximize notepad': ('window', 'notepad'), 'snap left current window': ('window', 'current window'),
            'pause listening': ('pause_listening', ''), 'create folder Projects in documents': ('file_action', 'Projects'),
            'copy file my budget to downloads': ('file_action', 'my budget'),
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                result = parse_command(phrase)
                self.assertEqual((result.action, result.target), expected)
    def test_shortcut_parsing_rejects_code_and_multiple_non_modifier_keys(self):
        self.assertEqual(key_codes('control shift s'), [17, 16, 83])
        self.assertEqual(key_codes('Windows + d'), [91, 68])
        self.assertEqual(key_codes('page down'), [34])
        for value in ['{ENTER}', 'a b c', 'ctrl ctrl s', 'os.system(1)', 'press enter']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                key_codes(value)
    def test_dictation_in_a_batch_cannot_become_another_action(self):
        commands = parse_commands('open notepad and type Hello and close Chrome!')
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[1].action, 'type')
        self.assertEqual(commands[1].target, 'Hello and close Chrome!')
    def test_mouse_options_and_repeated_keys(self):
        self.assertEqual(parse_command('move mouse to -100, 300').options, {'x': -100, 'y': 300})
        self.assertEqual(parse_command('press tab 3 times').options['count'], 3)
        self.assertEqual(parse_command('right click five').options['cell'], 5)

class DesktopBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(self.root/'state')
        self.desktop = Mock()
        self.desktop.keyboard.return_value = ActionResult.ok('keys', 'Pressed')
        self.desktop.window_action.return_value = ActionResult.ok('window', 'Focused')
        self.engine = Assistant(self.config, desktop=self.desktop, brain=Mock())
    def tearDown(self):
        self.temp.cleanup()
    def test_keyboard_execution_uses_parsed_shortcut(self):
        self.assertTrue(self.engine.handle('press control s').success)
        self.desktop.keyboard.assert_called_once_with('control s', 1)
    def test_window_choices_focus_instead_of_closing(self):
        self.desktop.windows.return_value = [{'name':'Notes','hwnd':123}, {'name':'Calculator','hwnd':456}]
        self.engine.handle('list windows')
        self.engine.handle('choose 2')
        self.desktop.window_action.assert_called_once_with(456, 'focus')
        self.desktop.close_window.assert_not_called()
    def test_file_creation_copy_and_rename_do_not_overwrite(self):
        destination = self.root/'files'
        destination.mkdir()
        self.config.update({'aliases':{'test folder':str(destination)}})
        self.assertTrue(self.engine.handle('create file sample.txt in test folder').success)
        self.assertFalse(self.engine.handle('create file sample.txt in test folder').success)
        (destination/'sample.txt').write_text('original')
        self.assertTrue(self.engine.handle(f'rename file "{destination / "sample.txt"}" to final.txt').success)
        self.assertEqual((destination/'final.txt').read_text(), 'original')
        self.assertFalse(self.engine.handle(f'copy file "{destination / "final.txt"}" to test folder').success)
        self.assertEqual((destination/'final.txt').read_text(), 'original')
    def test_recycling_requires_confirmation_and_can_be_cancelled(self):
        source = self.root/'old.txt'
        source.write_text('keep')
        result = self.engine.handle('recycle file '+str(source))
        self.assertEqual(result.action, 'confirmation')
        self.assertTrue(source.exists())
        self.engine.handle('no')
        self.engine.handle('yes')
        self.assertTrue(source.exists())
    def test_recycle_batch_cannot_execute_earlier_actions(self):
        result = self.engine.handle('open notepad and recycle file old.txt')
        self.assertFalse(result.success)
        self.desktop.open_app.assert_not_called()
    def test_move_into_source_subfolder_is_rejected(self):
        folder = self.root/'source'
        child = folder/'nested'
        child.mkdir(parents=True)
        result = self.engine.files.execute('move', str(folder), str(child))
        self.assertFalse(result.success)
        self.assertTrue(folder.exists())

class VoiceTransitionTests(unittest.TestCase):
    def voice(self):
        # Construct only the state machine; no audio worker or microphone.
        voice = VoiceInput.__new__(VoiceInput)
        voice.once=False
        voice._generation=0
        voice._resume_handsfree=False
        voice.enabled=threading.Event()
        voice.gate=Mock()
        voice.on_enabled=Mock()
        return voice
    def test_listen_once_resumes_handsfree_if_it_was_active(self):
        voice=self.voice()
        voice.set_enabled(True)
        voice.set_enabled(True,once=True)
        voice._finish_once()
        self.assertTrue(voice.enabled.is_set())
        self.assertFalse(voice.once)
    def test_listen_once_returns_to_paused_if_it_was_paused(self):
        voice=self.voice()
        voice.set_enabled(True,once=True)
        voice._finish_once()
        self.assertFalse(voice.enabled.is_set())
