from __future__ import annotations
import io
import sys
import unittest
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter


class TestBoardPrinter(unittest.TestCase):

    def test_round_trip(self):
        text = "wK . bR\n. . .\n. wN bK"
        board = BoardParser().parse(text)
        self.assertEqual(BoardPrinter().to_string(board), text)

    def test_print_outputs_to_stdout(self):
        board = BoardParser().parse("wK .")
        captured = io.StringIO()
        sys.stdout = captured
        BoardPrinter().print(board)
        sys.stdout = sys.__stdout__
        self.assertIn("wK", captured.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
