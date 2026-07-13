from __future__ import annotations
import unittest
from kungfu_chess.model.board import Board
from kungfu_chess.io.board_parser import BoardParser


class TestBoardParser(unittest.TestCase):

    def test_single_cell(self):
        board = BoardParser().parse("wK")
        self.assertEqual(board.width, 1)
        self.assertEqual(board.height, 1)

    def test_row_width_mismatch(self):
        with self.assertRaises(ValueError) as ctx:
            BoardParser().parse("wK .\nwR")
        self.assertIn("ROW_WIDTH_MISMATCH", str(ctx.exception))

    def test_unknown_token(self):
        with self.assertRaises(ValueError) as ctx:
            BoardParser().parse("wK XX")
        self.assertIn("UNKNOWN_TOKEN", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
