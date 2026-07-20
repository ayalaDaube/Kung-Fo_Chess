"""
Tests for shell_login.prompt_username.
read_line is injected — no monkeypatching of builtins.input.
"""
from __future__ import annotations
import unittest

from kungfu_chess.client.shell_login import prompt_username


def _reader(*values: str):
    """Returns a callable that yields values in sequence."""
    queue = list(values)
    def read_line() -> str:
        return queue.pop(0)
    return read_line


class TestPromptUsername(unittest.TestCase):

    def test_valid_input_returned_immediately(self):
        result = prompt_username(read_line=_reader("alice"))
        self.assertEqual(result, "alice")

    def test_empty_then_valid_re_prompts(self):
        result = prompt_username(read_line=_reader("", "bob"))
        self.assertEqual(result, "bob")

    def test_whitespace_only_then_valid_re_prompts(self):
        result = prompt_username(read_line=_reader("   ", "carol"))
        self.assertEqual(result, "carol")

    def test_overlong_then_valid_re_prompts(self):
        result = prompt_username(read_line=_reader("a" * 33, "dave"))
        self.assertEqual(result, "dave")

    def test_multiple_invalid_then_valid(self):
        result = prompt_username(read_line=_reader("", "   ", "a" * 33, "eve"))
        self.assertEqual(result, "eve")

    def test_strips_surrounding_whitespace(self):
        result = prompt_username(read_line=_reader("  frank  "))
        self.assertEqual(result, "frank")

    def test_exactly_max_length_accepted(self):
        name = "a" * 32
        result = prompt_username(read_line=_reader(name))
        self.assertEqual(result, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
