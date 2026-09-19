import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from Backend.Assistant import Assistant
from Backend.Config import Config
from Backend.Commands import Command
from Backend.Tools import ToolRegistry, ToolDefinition, validate_command
from Backend.Permissions import Risk, ExecutionContext
from Backend.ActionResult import ActionResult
from Backend.Audit import AuditUnavailable

class RegistryTests(unittest.TestCase):
    def test_duplicate_and_unknown_tool_rejected(self):
        registry = ToolRegistry()
        item = ToolDefinition("time", "Read time", Risk.LOW, validate_command, Mock())
        registry.register(item)
        with self.assertRaises(ValueError):
            registry.register(item)
        with self.assertRaises(ValueError):
            registry.get("arbitrary_shell")

    def test_validation_rejects_injected_or_wrong_parameters(self):
        commands = [Command("shell", "evil"), Command("keys", "ctrl s", {"confirmed": True}),
                    Command("keys", "enter", {"count": True}), Command("keys", "enter", {"count": 100}),
                    Command("volume", "101"), Command("file_action", "file", {"operation": "wipe"}),
                    Command("mouse", "position", {"x": 1}), Command("grid", "click", {"cell": 20}),
                    Command("system", "format c"), Command("type", "a\x00b")]
        for command in commands:
            with self.subTest(command=command), self.assertRaises(ValueError):
                validate_command(command)

    def test_guest_denial_does_not_execute_or_read_private_history(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop = Mock()
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock())
            result = assistant.handle("open notepad", context=ExecutionContext("guest"))
            self.assertFalse(result.success)
            desktop.open_app.assert_not_called()
            self.assertEqual(assistant.store.history(), [])
            self.assertEqual(assistant.audit.recent()[0]["outcome"], "failed")
            self.assertTrue(any(r["outcome"] == "denied" for r in assistant.audit.recent()))

    def test_audit_failure_before_action_blocks_it(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop, audit = Mock(), Mock()
            audit.record.side_effect = AuditUnavailable("unavailable")
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock(), audit=audit)
            self.assertEqual(assistant.handle("open notepad").error, "audit_unavailable")
            desktop.open_app.assert_not_called()

    def test_audit_failure_after_action_reports_uncertain_state(self):
        with tempfile.TemporaryDirectory() as folder:
            desktop, audit = Mock(), Mock()
            desktop.open_app.return_value = ActionResult.ok("open", "Opened")
            audit.record.side_effect = [None, AuditUnavailable("unavailable")]
            assistant = Assistant(Config(Path(folder)), desktop=desktop, brain=Mock(), audit=audit)
            result = assistant.handle("open notepad")
            self.assertEqual(result.error, "audit_unavailable")
            self.assertIn("may have completed", result.message)
            desktop.open_app.assert_called_once()

    def test_file_changed_after_confirmation_does_not_open(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file.cmd"
            path.write_text("original")
            desktop = Mock()
            assistant = Assistant(Config(Path(folder) / "state"), desktop=desktop, brain=Mock())
            self.assertEqual(assistant.handle("open file " + str(path)).action, "confirmation")
            path.write_text("changed file")
            result = assistant.handle("yes")
            self.assertFalse(result.success)
            desktop.open_path.assert_not_called()

    def test_untrusted_source_cannot_claim_legacy_memory_access(self):
        with tempfile.TemporaryDirectory() as folder:
            assistant = Assistant(Config(Path(folder)), desktop=Mock(), brain=Mock())
            assistant.store = Mock()
            result = assistant.handle("what time is it", context=ExecutionContext("remote", source="remote", legacy_local=True))
            self.assertTrue(result.success)
            assistant.store.history.assert_not_called()

    def test_service_reports_post_action_audit_failure(self):
        from Backend.Services import Services
        with tempfile.TemporaryDirectory() as folder:
            assistant = Assistant(Config(Path(folder)), desktop=Mock(), brain=Mock(), audit=Mock())
            service = Services(assistant.config, assistant=assistant)
            assistant.audit.record.side_effect = [None, AuditUnavailable("disk")]
            callback = Mock()
            with self.assertRaisesRegex(AuditUnavailable, "may have completed"):
                service.call("settings.update", callback)
            callback.assert_called_once()
