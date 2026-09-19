"""Unit tests for PresenceService / SecurityManager command gating."""

from __future__ import annotations

import unittest

from Backend.Security.config import SecurityConfig
from Backend.Security.gate import is_command_allowed, is_sensitive_command
from Backend.Security.service import PresenceService, SecurityManager
from Backend.Security.states import SecurityState


class SecurityGateTests(unittest.TestCase):
    def test_allows_commands_when_enforce_false(self):
        cfg = SecurityConfig(enabled=True, enforce=False)
        svc = PresenceService(cfg)
        svc._machine.force(SecurityState.UNKNOWN_PERSON, "test")
        self.assertTrue(svc.allows_commands())
        self.assertTrue(svc.is_command_allowed("system mute"))

    def test_blocks_when_enforce_true_and_restricted(self):
        cfg = SecurityConfig(enabled=True, enforce=True)
        svc = PresenceService(cfg)
        svc._machine.force(SecurityState.PROTECTION_PENDING, "test")
        self.assertFalse(svc.allows_commands())
        self.assertFalse(svc.is_command_allowed("system mute"))

    def test_blocks_unknown_and_protected(self):
        cfg = SecurityConfig(enabled=True, enforce=True)
        svc = SecurityManager(cfg)
        svc._machine.force(SecurityState.UNKNOWN_PERSON, "test")
        self.assertFalse(is_command_allowed(svc, "whatsapp mom hi"))
        svc._machine.force(SecurityState.PROTECTED, "test")
        self.assertFalse(is_command_allowed(svc, "open chrome"))

    def test_allows_when_enforce_true_and_authorized(self):
        cfg = SecurityConfig(enabled=True, enforce=True)
        svc = PresenceService(cfg)
        svc._machine.force(SecurityState.AUTHORIZED, "test")
        self.assertTrue(svc.allows_commands())
        self.assertTrue(svc.is_command_allowed("system mute"))

    def test_disabled_config_always_allows(self):
        cfg = SecurityConfig(enabled=False, enforce=True)
        svc = PresenceService(cfg)
        svc._machine.force(SecurityState.LOCKED, "test")
        self.assertTrue(svc.allows_commands())

    def test_sensitive_prefix_helper(self):
        self.assertTrue(is_sensitive_command("system shutdown"))
        self.assertTrue(is_sensitive_command("send message mom hi"))
        self.assertFalse(is_sensitive_command("general hello there"))


if __name__ == "__main__":
    unittest.main()
