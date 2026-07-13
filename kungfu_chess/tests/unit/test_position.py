from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position


class TestPosition(unittest.TestCase):

    def test_equality(self):
        self.assertEqual(Position(1, 2), Position(1, 2))

    def test_inequality_row(self):
        self.assertNotEqual(Position(1, 2), Position(2, 2))

    def test_inequality_col(self):
        self.assertNotEqual(Position(1, 2), Position(1, 3))

    def test_repr(self):
        self.assertIn("row=1", repr(Position(1, 2)))
        self.assertIn("col=2", repr(Position(1, 2)))

    def test_hashable(self):
        s = {Position(0, 0), Position(0, 0)}
        self.assertEqual(len(s), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
