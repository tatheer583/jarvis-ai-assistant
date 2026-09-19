"""Unit tests for local DMM command classification."""

from __future__ import annotations

import unittest

from Backend.Model import _classify_single_command, _fallback_dmm, _is_realtime_query


class ClassifySingleCommandTests(unittest.TestCase):
    def test_open_close_play(self):
        self.assertEqual(_classify_single_command("open youtube"), "open youtube")
        self.assertEqual(_classify_single_command("close notepad"), "close notepad")
        self.assertEqual(_classify_single_command("play lo-fi beats"), "play lo-fi beats")

    def test_system_commands(self):
        self.assertEqual(_classify_single_command("mute"), "system mute")
        self.assertEqual(_classify_single_command("unmute"), "system unmute")
        self.assertEqual(_classify_single_command("shutdown"), "system shutdown")
        self.assertEqual(_classify_single_command("system restart"), "system restart")

    def test_exit(self):
        self.assertEqual(_classify_single_command("bye"), "exit")
        self.assertEqual(_classify_single_command("quit"), "exit")

    def test_image_and_search(self):
        self.assertTrue(_classify_single_command("generate image of a cat").startswith("generate image"))
        self.assertEqual(
            _classify_single_command("google search python asyncio"),
            "google search python asyncio",
        )

    def test_whatsapp_message(self):
        out = _classify_single_command("send a message to Ali that I am late")
        self.assertTrue(out.startswith("send message Ali"))

    def test_general_fallback(self):
        out = _classify_single_command("explain photosynthesis")
        self.assertTrue(out.startswith("general ("))

    def test_realtime_hints_narrow(self):
        self.assertTrue(_is_realtime_query("what time is it"))
        self.assertFalse(_is_realtime_query("sometimes I feel tired"))
        self.assertTrue(_classify_single_command("what time is it").startswith("realtime ("))

    def test_fallback_split(self):
        tasks = _fallback_dmm("open chrome and mute")
        self.assertIn("open chrome", tasks)
        self.assertIn("system mute", tasks)


if __name__ == "__main__":
    unittest.main()
