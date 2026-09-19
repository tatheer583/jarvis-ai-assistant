"""Unit tests for security state machine transitions."""

from __future__ import annotations

import unittest

from Backend.Security.state_machine import InvalidTransition, SecurityStateMachine
from Backend.Security.states import SecurityState


class SecurityStateMachineTests(unittest.TestCase):
    def test_initial_state(self):
        sm = SecurityStateMachine()
        self.assertEqual(sm.state, SecurityState.STARTING)

    def test_starting_to_no_person_and_authorized(self):
        sm = SecurityStateMachine()
        r = sm.transition(SecurityState.NO_PERSON, "test")
        self.assertTrue(r.changed)
        self.assertEqual(sm.state, SecurityState.NO_PERSON)
        self.assertEqual(sm.state, SecurityState.ABSENT)  # legacy alias
        sm.transition(SecurityState.AUTHORIZED, "present")
        self.assertEqual(sm.state, SecurityState.AUTHORIZED)

    def test_unknown_person_transition(self):
        sm = SecurityStateMachine(SecurityState.STARTING)
        sm.transition(SecurityState.UNKNOWN_PERSON, "face")
        self.assertEqual(sm.state, SecurityState.UNKNOWN_PERSON)

    def test_absence_timeout_path(self):
        sm = SecurityStateMachine(SecurityState.NO_PERSON)
        sm.transition(SecurityState.PROTECTION_PENDING, "timeout")
        self.assertEqual(sm.state, SecurityState.PROTECTION_PENDING)
        sm.transition(SecurityState.PROTECTED, "threshold")
        self.assertEqual(sm.state, SecurityState.PROTECTED)
        self.assertEqual(sm.state, SecurityState.PROTECTING)  # alias

    def test_warning_to_protected_to_locked(self):
        sm = SecurityStateMachine(SecurityState.WARNING)
        sm.transition(SecurityState.PROTECTED, "threshold")
        sm.transition(SecurityState.LOCKED, "lock_ok")
        self.assertEqual(sm.state, SecurityState.LOCKED)

    def test_illegal_transition_raises(self):
        sm = SecurityStateMachine(SecurityState.STARTING)
        with self.assertRaises(InvalidTransition):
            sm.transition(SecurityState.LOCKED, "nope")

    def test_noop_same_state(self):
        sm = SecurityStateMachine(SecurityState.NO_PERSON)
        r = sm.transition(SecurityState.NO_PERSON, "same")
        self.assertFalse(r.changed)

    def test_camera_error_recover(self):
        sm = SecurityStateMachine(SecurityState.STARTING)
        sm.transition(SecurityState.CAMERA_ERROR, "fail")
        sm.transition(SecurityState.STARTING, "retry")
        self.assertEqual(sm.state, SecurityState.STARTING)


if __name__ == "__main__":
    unittest.main()
