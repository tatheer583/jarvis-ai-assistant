"""Unit tests for shared text helpers."""

from __future__ import annotations

import unittest

from Backend.TextUtils import AnswerModifier, QueryModifier


class TextUtilsTests(unittest.TestCase):
    def test_answer_modifier_drops_blank_lines(self):
        self.assertEqual(AnswerModifier("a\n\n\nb\n"), "a\nb")

    def test_query_preserves_case(self):
        self.assertEqual(QueryModifier("Hello World"), "Hello World.")

    def test_query_adds_question_mark(self):
        self.assertTrue(QueryModifier("what is python").endswith("?"))


if __name__ == "__main__":
    unittest.main()
