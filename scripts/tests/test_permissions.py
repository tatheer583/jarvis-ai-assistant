import time
import unittest
from Backend.Permissions import SecurityManager, Principal, ExecutionContext, Risk, PermissionDenied

class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.manager = SecurityManager()
        self.guest = ExecutionContext("guest")

    def test_guest_gets_only_explicit_public_low_risk(self):
        self.assertTrue(self.manager.decide("time", Risk.LOW, self.guest, public=True).allowed)
        for risk in Risk:
            self.assertFalse(self.manager.decide("memory", risk, self.guest).allowed)

    def test_strong_grant_requires_identity_scope_and_expiration(self):
        owner = Principal("owner", True, time.monotonic() + 60, frozenset({"recycle"}))
        context = ExecutionContext("owner", principal=owner)
        self.assertTrue(self.manager.decide("recycle", Risk.HIGH, context).allowed)
        self.assertFalse(self.manager.decide("secrets", Risk.HIGH, context).allowed)
        expired = ExecutionContext("owner", principal=Principal("owner", True, 1, frozenset({"recycle"})))
        self.assertFalse(self.manager.decide("recycle", Risk.HIGH, expired).allowed)

    def test_legacy_mode_does_not_authorize_new_tools_or_remote_callers(self):
        context = ExecutionContext("local", legacy_local=True)
        self.assertFalse(self.manager.decide("plugin", Risk.HIGH, context).allowed)
        self.assertTrue(self.manager.decide("system", Risk.HIGH, context, legacy_allowed=True).allowed)
        remote = ExecutionContext("local", source="remote", legacy_local=True)
        self.assertFalse(self.manager.decide("system", Risk.HIGH, remote, legacy_allowed=True).allowed)

    def test_confirmation_bound_single_use_and_expiring(self):
        self.manager.challenge({"action": "system", "target": "shutdown"}, self.guest)
        with self.assertRaises(PermissionDenied):
            self.manager.consume(ExecutionContext("other"))
        self.assertEqual(self.manager.consume(self.guest)["target"], "shutdown")
        with self.assertRaises(PermissionDenied):
            self.manager.consume(self.guest)
        self.manager.challenge({"action": "system"}, self.guest, ttl=-1)
        with self.assertRaises(PermissionDenied):
            self.manager.consume(self.guest)

    def test_cancel_discards_confirmation(self):
        self.manager.challenge({"action": "system"}, self.guest)
        self.manager.clear()
        with self.assertRaises(PermissionDenied):
            self.manager.consume(self.guest)
