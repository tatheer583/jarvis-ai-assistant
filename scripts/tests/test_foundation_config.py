import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from Backend.Config import Config

class FoundationConfigTests(unittest.TestCase):
    def test_legacy_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"user_name": "Owner", "voice_rate": 2}))
            config = Config(Path(folder))
            config.update({"language": "ur"})
            self.assertEqual(json.loads(path.read_text())["_schema_version"], 1)
            self.assertEqual(Config(Path(folder)).settings.user_name, "Owner")
            self.assertEqual(config.settings.voice_rate, 2)

    def test_failed_persistence_preserves_memory_and_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(Path(folder))
            config.update({"voice_rate": 1})
            previous = config.path.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    config.update({"voice_rate": 2})
            self.assertEqual(config.settings.voice_rate, 1)
            self.assertEqual(config.path.read_bytes(), previous)
            self.assertEqual(list(Path(folder).glob("settings-*.tmp")), [])

    def test_invalid_existing_file_is_not_overwritten(self):
        for contents in ('{"_schema_version": 100}', 'broken'):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "settings.json"
                path.write_text(contents)
                config = Config(Path(folder))
                self.assertTrue(config.last_error)
                self.assertFalse(config.settings.listen_on_startup)
                with self.assertRaises(ValueError):
                    config.update({"voice_rate": 1})
                self.assertEqual(path.read_text(), contents)

    def test_unknown_fields_and_invalid_values_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(Path(folder))
            for values in ({"api_key": "never store"}, {"audit_retention_days": 0}, {"wake_word": ""}):
                with self.assertRaises(ValueError):
                    config.update(values)
