import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from Backend.Audit import AuditLog, AuditUnavailable
from Backend.Events import EventBus

class AuditTests(unittest.TestCase):
    def test_metadata_allowlist_never_writes_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            log = AuditLog(Path(folder))
            log.record(tool="files.copy", outcome="allowed", source="typed",
                       password="SECRET", token="SECRET", payload={"api_key": "SECRET"},
                       command="SECRET", code="invalid code SECRET")
            text = json.dumps(log.recent())
            self.assertNotIn("SECRET", text)
            self.assertIn("redacted", text)
            self.assertEqual(log.recent()[0]["outcome"], "allowed")

    def test_retention_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            log = AuditLog(Path(folder), 1)
            log.record(tool="time", outcome="succeeded")
            db = log._connect()
            db.execute("UPDATE events SET created=0")
            db.commit()
            db.close()
            reopened = AuditLog(Path(folder), 1)
            reopened.record(tool="date", outcome="succeeded")
            self.assertEqual([r["tool"] for r in reopened.recent()], ["date"])

    def test_storage_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            log = AuditLog(Path(folder))
            with patch.object(log, "_connect", side_effect=OSError("disk")):
                with self.assertRaises(AuditUnavailable):
                    log.record(tool="time")

    def test_event_subscriber_failure_is_isolated_and_unsubscribe_works(self):
        bus = EventBus()
        received = []
        def broken(event):
            raise RuntimeError("private exception")
        bus.subscribe(broken)
        remove = bus.subscribe(received.append)
        bus.emit("task", {"state": "running"})
        remove()
        bus.emit("task", {"state": "done"})
        self.assertEqual(len(received), 1)
