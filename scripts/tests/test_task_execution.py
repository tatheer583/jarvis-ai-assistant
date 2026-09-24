import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from Backend.Assistant import Assistant
from Backend.Config import Config
from Backend.ActionResult import ActionResult
from Backend.Tasks import CancellationToken, TaskState

class TaskExecutionTests(unittest.TestCase):
    def test_stop_prevents_later_batch_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Mock()
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock())
            def first(name):
                assistant.stop()
                return ActionResult.ok("open", "Opened")
            desktop.open_app.side_effect = first
            result = assistant.handle("open notepad and open calculator")
            self.assertEqual(result.error, "cancelled")
            self.assertEqual(desktop.open_app.call_count, 1)
            self.assertEqual(assistant.current_task.state, TaskState.CANCELLED)

    def test_cancelled_queued_token_is_never_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Mock()
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock())
            token = CancellationToken()
            token.cancel()
            self.assertEqual(assistant.handle("open notepad", token=token).error, "cancelled")
            desktop.open_app.assert_not_called()

    def test_expired_task_does_not_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Mock()
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock())
            self.assertEqual(assistant.handle("open notepad", token=CancellationToken(-1)).error, "timeout")
            desktop.open_app.assert_not_called()

    def test_task_does_not_expose_private_request(self):
        with tempfile.TemporaryDirectory() as folder:
            brain = Mock()
            brain.reply.return_value = "reply"
            assistant = Assistant(Config(Path(folder)), desktop=Mock(), brain=brain)
            assistant.handle("SECRET PRIVATE TEXT")
            self.assertNotIn("SECRET", str(assistant.current_task.to_dict()))
            self.assertEqual(assistant.current_task.state, TaskState.SUCCEEDED)

    def test_failed_operation_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Mock()
            desktop.open_app.return_value = ActionResult.fail("open", "Failed")
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock())
            self.assertFalse(assistant.handle("open notepad").success)
            desktop.open_app.assert_called_once()
