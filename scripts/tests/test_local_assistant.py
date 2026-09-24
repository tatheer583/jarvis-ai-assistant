"""Behavior tests for offline commands. Desktop actions are mocked, never executed."""
from __future__ import annotations
import datetime as dt
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from Backend.ActionResult import ActionResult
from Backend.Assistant import Assistant
from Backend.Commands import parse_command, parse_commands, reminder_details
from Backend.Config import Config
from Backend.FileIndex import FileIndex
from Backend.LocalBrain import LocalBrain, ModelUnavailable
from Backend.Store import Store

class CommandTests(unittest.TestCase):
    def test_punctuation_and_wake_word(self):
        self.assertEqual(parse_command("Jarvis, mute.").target, "mute")
        self.assertEqual(parse_command("shutdown.").target, "shutdown")
        self.assertEqual(parse_command("stop").action, "stop_speaking")
        self.assertEqual(parse_command("quit").action, "exit")

    def test_multiple_commands_without_splitting_names(self):
        self.assertEqual([c.action for c in parse_commands("open notes and then close calculator")], ["open", "close"])
        self.assertEqual(parse_commands("open research and development.pdf")[0].target, "research and development.pdf")
        self.assertEqual(len(parse_commands("type open notepad and close calculator!")), 1)
        self.assertEqual(parse_command("type Hello, Ali!").target, "Hello, Ali!")

    def test_urdu_and_roman_urdu(self):
        self.assertEqual(parse_command("downloads kholo").action, "open")
        self.assertEqual(parse_command("نوٹ پیڈ کھولو").target, "نوٹ پیڈ")
        self.assertEqual(parse_command("chrome band karo").action, "close")
        self.assertEqual(parse_command("اردو موڈ").target, "ur")

    def test_file_filters_and_choice(self):
        self.assertEqual(parse_command("find PDF invoice").options["kind"], "pdf")
        self.assertEqual(parse_command("open the first one").options["index"], 1)
        self.assertEqual(parse_command("search for python").action, "web")
        self.assertEqual(parse_command("search files for invoice").action, "find")

    def test_real_reminder_due_dates(self):
        now = dt.datetime(2026, 9, 11, 17, 0)
        text, due = reminder_details("in ten minutes to drink water", now)
        self.assertEqual(text, "drink water")
        self.assertEqual(due, now + dt.timedelta(minutes=10))
        text, due = reminder_details("to call Ali tomorrow at 8 am", now)
        self.assertEqual(text, "call Ali")
        self.assertEqual(due, dt.datetime(2026, 9, 12, 8))
        with self.assertRaises(ValueError):
            reminder_details("to drink water", now)
        with self.assertRaises(ValueError):
            reminder_details("in 0 minutes to drink", now)

class LocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(self.root / "state")
        self.desktop = Mock()
        self.desktop.open_app.return_value = None
        self.desktop.open_path.side_effect = lambda p: ActionResult.ok("open", "Opened", path=p)
        self.desktop.matching_windows.return_value = []
        self.desktop.system.return_value = ActionResult.ok("system", "Done")
        self.brain = Mock()
        self.brain.reply.return_value = "Local reply"
        self.engine = Assistant(self.config, desktop=self.desktop, brain=self.brain)

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_batch_runs_each_action_once(self):
        self.desktop.open_app.return_value = ActionResult.fail("open", "Failed")
        result = self.engine.handle("open bad-one and open bad-two")
        self.assertFalse(result.success)
        self.assertEqual(self.desktop.open_app.call_count, 2)

    def test_ambiguous_files_require_choice(self):
        for parent in ("a", "b"):
            folder = self.root / parent
            folder.mkdir()
            (folder / "budget.txt").write_text("test")
        self.engine.index.scan([str(self.root / "a"), str(self.root / "b")])
        result = self.engine.handle("open budget")
        self.assertEqual(result.action, "choices")
        self.desktop.open_path.assert_not_called()
        result = self.engine.handle("open the second one")
        self.assertTrue(result.success)
        self.desktop.open_path.assert_called_once()

    def test_full_path_outside_index_and_executable_confirmation(self):
        document = self.root / "space name.txt"
        document.write_text("test")
        self.assertTrue(self.engine.handle("open file " + str(document)).success)
        self.desktop.open_path.reset_mock()
        program = self.root / "example.ps1"
        program.write_text("Write-Output test")
        self.assertEqual(self.engine.handle("open file " + str(program)).action, "confirmation")
        self.desktop.open_path.assert_not_called()
        self.engine.handle("no")
        self.engine.handle("yes")
        self.desktop.open_path.assert_not_called()

    def test_power_confirmation_expires_and_new_commands_cancel_it(self):
        self.engine.handle("shutdown")
        self.desktop.system.assert_not_called()
        self.engine.pending["expires"] = time.monotonic() - 1
        self.engine.handle("yes")
        self.desktop.system.assert_not_called()
        self.engine.handle("restart")
        self.engine.handle("what time is it")
        self.engine.handle("yes")
        self.desktop.system.assert_not_called()
        self.engine.handle("shutdown")
        self.engine.handle("yes")
        self.desktop.system.assert_called_once_with("shutdown", confirmed=True)

    def test_power_batch_does_not_execute_other_actions(self):
        self.engine.handle("open notepad and shutdown")
        self.desktop.open_app.assert_not_called()
        self.desktop.system.assert_not_called()

    def test_closing_is_targeted_and_graceful(self):
        self.desktop.matching_windows.return_value = [{"hwnd": 123, "name": "notes", "process": "notepad.exe"}]
        self.desktop.close_window.return_value = ActionResult.ok("close", "Requested close")
        self.engine.handle("close notes.txt")
        self.desktop.close_window.assert_called_once_with(123)

    def test_reminder_persistence_and_single_delivery(self):
        reminder_id = self.engine.store.add_reminder("test", 10)
        second = Store(self.config.database)
        self.assertEqual(second.take_due_reminders(11)[0]["id"], reminder_id)
        self.assertEqual(self.engine.store.take_due_reminders(12), [])
        self.assertEqual(second.reminders(), [])

    def test_note_and_history_persist(self):
        self.engine.handle("take a note Buy bread and milk.")
        self.assertEqual(Store(self.config.database).notes()[0]["content"], "Buy bread and milk.")
        self.assertEqual(len(Store(self.config.database).history()), 2)

    def test_index_filters_and_skips_cache_directories(self):
        folder = self.root / "files"
        folder.mkdir()
        (folder / "invoice.pdf").write_text("test")
        (folder / "invoice.txt").write_text("test")
        cache = folder / "node_modules"
        cache.mkdir()
        (cache / "invoice.pdf").write_text("hidden")
        self.engine.index.scan([str(folder)])
        hits = self.engine.index.search("invoice", kind="pdf")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["path"], str(folder / "invoice.pdf"))

    def test_cancelled_index_preserves_existing_entries(self):
        folder = self.root / "files"
        folder.mkdir()
        (folder / "notes.txt").write_text("test")
        self.engine.index.scan([str(folder)])
        stop = threading.Event()
        stop.set()
        self.engine.index.scan([str(folder)], stop=stop)
        self.assertEqual(len(self.engine.index.search("notes")), 1)

    def test_missing_model_never_downloads_or_calls_a_server(self):
        brain = LocalBrain(self.config)
        with patch("socket.socket.connect", side_effect=AssertionError("No network allowed")):
            self.assertIn("answer is 6", brain.reply("what is 2 * 3"))
            self.assertIn("Hello", brain.reply("hi"))
            with self.assertRaises(ModelUnavailable):
                brain.reply("explain photosynthesis")

    def test_configuration_is_atomic_and_validated(self):
        self.config.update({"voice_rate": 3, "language": "ur"})
        self.assertEqual(Config(self.config.directory).settings.voice_rate, 3)
        with self.assertRaises(ValueError):
            self.config.update({"voice_rate": 90})
        self.assertEqual(self.config.settings.voice_rate, 3)

if __name__ == "__main__":
    unittest.main()
