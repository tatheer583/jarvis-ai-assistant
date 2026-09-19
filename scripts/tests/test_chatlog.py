"""Unit tests for thread-safe ChatLog helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import Backend.ChatLog as chatlog


class ChatLogTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "ChatLog.json"
        self._patcher = mock.patch.object(chatlog, "CHAT_LOG_PATH", self.path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def test_read_empty_creates_file(self):
        data = chatlog.read_chat_log()
        self.assertEqual(data, [])
        self.assertTrue(self.path.exists())

    def test_append_and_read(self):
        chatlog.append_messages(
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        )
        data = chatlog.read_chat_log()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["role"], "user")
        self.assertEqual(data[1]["content"], "hi there")

    def test_skips_empty_entries(self):
        out = chatlog.append_messages({"role": "user", "content": "  "})
        self.assertEqual(out, [])

    def test_write_trims_to_max(self):
        messages = [{"role": "user", "content": f"m{i}"} for i in range(120)]
        trimmed = chatlog.write_chat_log(messages)
        self.assertEqual(len(trimmed), chatlog.MAX_MESSAGES)
        self.assertEqual(trimmed[0]["content"], "m20")
        self.assertEqual(len(chatlog.read_chat_log()), chatlog.MAX_MESSAGES)


if __name__ == "__main__":
    unittest.main()
