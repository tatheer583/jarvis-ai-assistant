import unittest
from unittest.mock import Mock, patch
from Backend.AIProviders import AIOrchestrator, ModelUnavailable
from Backend.Events import EventBus
from Backend.Tasks import CancellationToken, cancellation_scope, Cancelled

class ProviderTests(unittest.TestCase):
    def test_offline_mode_never_touches_online_provider(self):
        local, online = Mock(), Mock()
        local.reply.return_value = "Local response"
        provider = AIOrchestrator(local, online=online)
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            self.assertEqual(provider.reply("hello"), "Local response")
        online.ready.assert_not_called()
        online.reply.assert_not_called()

    def test_online_failure_falls_back_without_exposing_error_secrets(self):
        local, online = Mock(), Mock()
        local.reply.return_value = "Local fallback"
        online.ready.return_value = True
        online.reply.side_effect = RuntimeError("SECRET API KEY")
        events = EventBus()
        observed = []
        events.subscribe(observed.append)
        provider = AIOrchestrator(local, online=online, online_enabled=True, events=events)
        self.assertEqual(provider.reply("question"), "Local fallback")
        self.assertNotIn("SECRET", str(observed))
        self.assertEqual(provider.active_provider, "local")

    def test_missing_online_provider_still_uses_local(self):
        local = Mock()
        local.reply.return_value = "offline"
        self.assertEqual(AIOrchestrator(local, online_enabled=True).reply("hi"), "offline")

    def test_local_model_error_remains_explicit(self):
        local = Mock()
        local.reply.side_effect = ModelUnavailable("Model missing")
        with self.assertRaises(ModelUnavailable):
            AIOrchestrator(local).reply("question")

    def test_cancelled_request_does_not_fall_back_or_start_model(self):
        token = CancellationToken()
        token.cancel()
        local, online = Mock(), Mock()
        with cancellation_scope(token), self.assertRaises(Cancelled):
            AIOrchestrator(local, online=online, online_enabled=True).reply("hi")
        local.reply.assert_not_called()
        online.reply.assert_not_called()
