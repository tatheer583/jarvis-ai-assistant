"""Unit tests for security config loading."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from Backend.Security.config import SecurityConfig, load_security_config


class SecurityConfigTests(unittest.TestCase):
    def test_defaults_when_env_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_security_config(Path(tmp) / "missing.env")
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.camera_enabled)
        self.assertFalse(cfg.enforce)
        self.assertEqual(cfg.owner_display_name, "Tatheer")
        self.assertEqual(cfg.owner_name, "Tatheer")
        self.assertEqual(cfg.absence_timeout_sec, 25.0)
        self.assertEqual(cfg.unknown_person_timeout_sec, 20.0)
        self.assertIn("Hi sir Tatheer", cfg.authorized_greeting)
        self.assertIn("not Tatheer", cfg.unauthorized_message)

    def test_parse_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            lines = [
                "SecurityEnabled=false",
                "CameraEnabled=false",
                "SecurityEnforce=true",
                "AbsenceTimeout=30",
                "UnknownPersonTimeout=12",
                "OwnerName=Tatheer",
                "PresenceCheckInterval=0.25",
                "CameraIndex=1",
            ]
            env.write_text(chr(10).join(lines), encoding="utf-8")
            cfg = load_security_config(env)
        self.assertFalse(cfg.enabled)
        self.assertFalse(cfg.camera_enabled)
        self.assertTrue(cfg.enforce)
        self.assertEqual(cfg.absence_timeout_sec, 30.0)
        self.assertEqual(cfg.unknown_person_timeout_sec, 12.0)
        self.assertEqual(cfg.frame_interval_sec, 0.25)
        self.assertEqual(cfg.camera_index, 1)

    def test_manual_disable_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            sec_dir = Path(tmp) / "Security"
            sec_dir.mkdir()
            cfg = SecurityConfig(enabled=True, security_dir=sec_dir)
            self.assertTrue(cfg.effective_enabled())
            (sec_dir / "DISABLE").write_text("1", encoding="utf-8")
            self.assertFalse(cfg.effective_enabled())


if __name__ == "__main__":
    unittest.main()
