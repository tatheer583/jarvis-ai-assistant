"""Service-level security tests with mocked camera / verifier (no webcam)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from Backend.Security.camera import CameraError
from Backend.Security.config import SecurityConfig
from Backend.Security.face_verifier import IdentityResult, VerifyResult
from Backend.Security.service import PresenceService
from Backend.Security.states import SecurityState


class FakeVerifier:
    def __init__(self, identity: IdentityResult = IdentityResult.OWNER):
        self.identity = identity
        self.is_enrolled = True

    def reload_templates(self) -> None:
        return None

    def verify_owner(self, frame) -> VerifyResult:
        return VerifyResult(self.identity, score=0.99, faces_found=1, reason="fake")

    def verify_frame(self, frame) -> VerifyResult:
        return self.verify_owner(frame)


class SecurityServiceTests(unittest.TestCase):
    def _cfg(self, **kwargs) -> SecurityConfig:
        tmp = Path(tempfile.mkdtemp())
        defaults = dict(
            enabled=True,
            camera_enabled=True,
            enforce=True,
            warmup_frames=0,
            presence_stable_frames=1,
            absence_stable_frames=1,
            face_stable_frames=1,
            absence_timeout_sec=0.01,
            protect_threshold_sec=0.01,
            greeting_cooldown_sec=0.0,
            warning_cooldown_sec=0.0,
            security_dir=tmp,
        )
        defaults.update(kwargs)
        return SecurityConfig(**defaults)

    def test_camera_disabled_does_not_start(self):
        svc = PresenceService(self._cfg(camera_enabled=False), verifier=FakeVerifier())
        self.assertFalse(svc.start())
        self.assertFalse(svc.is_running())

    def test_camera_error_on_open_does_not_crash(self):
        cam = MagicMock()
        cam.open.side_effect = CameraError("no cam")
        svc = PresenceService(self._cfg(), verifier=FakeVerifier(), camera=cam)
        self.assertFalse(svc.start())
        self.assertEqual(svc.get_state(), SecurityState.CAMERA_ERROR)

    def test_owner_greeting_once_per_transition(self):
        spoken: list[str] = []
        svc = PresenceService(
            self._cfg(),
            verifier=FakeVerifier(IdentityResult.OWNER),
            on_speak=spoken.append,
        )
        svc._machine.force(SecurityState.NO_PERSON, "setup")
        svc._safe_transition(SecurityState.AUTHORIZED, "owner_return")
        self.assertEqual(len(spoken), 1)
        self.assertTrue(spoken[0].startswith("Hi sir"))
        self.assertTrue(svc.consume_owner_recognized_event())
        # Same state again should not re-greet
        svc._safe_transition(SecurityState.AUTHORIZED, "noop")
        self.assertEqual(len(spoken), 1)

    def test_unknown_announcement(self):
        spoken: list[str] = []
        svc = PresenceService(
            self._cfg(),
            verifier=FakeVerifier(IdentityResult.UNKNOWN),
            on_speak=spoken.append,
        )
        svc._machine.force(SecurityState.AUTHORIZED, "setup")
        svc._safe_transition(SecurityState.UNKNOWN_PERSON, "mismatch")
        self.assertEqual(len(spoken), 1)
        self.assertIn("not Tatheer", spoken[0])

    def test_owner_leave_and_protection_path(self):
        svc = PresenceService(self._cfg(), verifier=FakeVerifier())
        svc._machine.force(SecurityState.AUTHORIZED, "setup")
        svc._safe_transition(SecurityState.NO_PERSON, "owner_left")
        self.assertEqual(svc.get_state(), SecurityState.NO_PERSON)
        svc._safe_transition(SecurityState.PROTECTION_PENDING, "timeout")
        self.assertEqual(svc.get_state(), SecurityState.PROTECTION_PENDING)
        svc._safe_transition(SecurityState.PROTECTED, "threshold")
        self.assertEqual(svc.get_state(), SecurityState.PROTECTED)
        self.assertFalse(svc.allows_commands())

    def test_tick_owner_authorized(self):
        cam = MagicMock()
        cam.read.return_value = object()
        svc = PresenceService(
            self._cfg(warmup_frames=0),
            verifier=FakeVerifier(IdentityResult.OWNER),
            camera=cam,
        )
        svc._detector.person_present = lambda frame: True  # type: ignore
        svc._warmup_left = 0
        svc._tick()
        svc._tick()  # streaks
        self.assertEqual(svc.get_state(), SecurityState.AUTHORIZED)

    def test_tick_no_person(self):
        cam = MagicMock()
        cam.read.return_value = object()
        svc = PresenceService(self._cfg(), verifier=FakeVerifier(), camera=cam)
        svc._detector.person_present = lambda frame: False  # type: ignore
        svc._warmup_left = 0
        with patch("Backend.Security.service.time.monotonic", return_value=100.0) as clock:
            svc._tick()
            svc._tick()
            self.assertEqual(svc.get_state(), SecurityState.NO_PERSON)
            clock.return_value = 100.02
            svc._tick()
            self.assertEqual(svc.get_state(), SecurityState.PROTECTION_PENDING)


if __name__ == "__main__":
    unittest.main()
