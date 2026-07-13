from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.input.board_mapper import BoardMapper


class TestBoardMapper(unittest.TestCase):

    def _mapper(self):
        return BoardMapper(8, 8, 100)

    def test_origin(self):
        self.assertEqual(self._mapper().pixel_to_cell(0, 0), Position(0, 0))

    def test_col_1(self):
        self.assertEqual(self._mapper().pixel_to_cell(150, 50), Position(0, 1))

    def test_row_1(self):
        self.assertEqual(self._mapper().pixel_to_cell(50, 150), Position(1, 0))

    def test_outside_returns_none(self):
        self.assertIsNone(self._mapper().pixel_to_cell(800, 400))

    def test_negative_returns_none(self):
        self.assertIsNone(self._mapper().pixel_to_cell(-1, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
