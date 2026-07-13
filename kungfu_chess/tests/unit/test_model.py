from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceColor, PieceKind, PieceState
from kungfu_chess.model.board import Board


def make_board(tokens: list[list[str]]) -> Board:
    """עזר: בונה Board מרשת טוקנים."""
    from kungfu_chess.io.board_parser import BoardParser
    text = "\n".join(" ".join(row) for row in tokens)
    return BoardParser().parse(text)


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


class TestPiece(unittest.TestCase):

    def _piece(self):
        return Piece("p1", PieceColor.WHITE, PieceKind.KING, Position(0, 0))

    def test_code(self):
        self.assertEqual(self._piece().code, "wK")

    def test_default_state(self):
        self.assertEqual(self._piece().state, PieceState.IDLE)

    def test_state_change(self):
        p = self._piece()
        p.state = PieceState.MOVING
        self.assertEqual(p.state, PieceState.MOVING)


class TestBoard(unittest.TestCase):

    def test_dimensions(self):
        b = make_board([["wK", "."], [".", "bK"]])
        self.assertEqual(b.width, 2)
        self.assertEqual(b.height, 2)

    def test_get_piece_occupied(self):
        b = make_board([["wK", "."]])
        self.assertIsNotNone(b.get_piece(Position(0, 0)))

    def test_get_piece_empty(self):
        b = make_board([["wK", "."]])
        self.assertIsNone(b.get_piece(Position(0, 1)))

    def test_in_bounds(self):
        b = Board(3, 3)
        self.assertTrue(b.in_bounds(Position(0, 0)))
        self.assertFalse(b.in_bounds(Position(3, 0)))

    def test_double_occupancy_raises(self):
        b = Board(2, 2)
        p1 = Piece("p1", PieceColor.WHITE, PieceKind.KING, Position(0, 0))
        p2 = Piece("p2", PieceColor.BLACK, PieceKind.KING, Position(0, 0))
        b.add_piece(p1)
        with self.assertRaises(ValueError):
            b.add_piece(p2)

    def test_move_piece_updates_positions(self):
        b = make_board([["wR", ".", "."]])
        piece = b.get_piece(Position(0, 0))
        b.move_piece(Position(0, 0), Position(0, 2))
        self.assertIsNone(b.get_piece(Position(0, 0)))
        self.assertIs(b.get_piece(Position(0, 2)), piece)

    def test_move_piece_captures(self):
        b = make_board([["wR", "bK"]])
        captured = b.move_piece(Position(0, 0), Position(0, 1))
        self.assertIsNotNone(captured)
        self.assertEqual(captured.state, PieceState.CAPTURED)

    def test_remove_piece(self):
        b = make_board([["wK", "."]])
        b.remove_piece(Position(0, 0))
        self.assertIsNone(b.get_piece(Position(0, 0)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
