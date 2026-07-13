from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.io.board_parser import BoardParser


def parse(text: str) -> Board:
    return BoardParser().parse(text)


class TestRuleEngine(unittest.TestCase):

    def test_valid_rook_move(self):
        board = parse("wR . .\n. . .\n. . .")
        v = RuleEngine().validate_move(board, Position(0, 0), Position(0, 2))
        self.assertTrue(v.is_valid)
        self.assertEqual(v.reason, "ok")

    def test_outside_board(self):
        board = parse("wR .")
        v = RuleEngine().validate_move(board, Position(0, 0), Position(5, 5))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "outside_board")

    def test_empty_source(self):
        board = parse("wR .")
        v = RuleEngine().validate_move(board, Position(0, 1), Position(0, 0))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "empty_source")

    def test_friendly_destination(self):
        board = parse("wR wK")
        v = RuleEngine().validate_move(board, Position(0, 0), Position(0, 1))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "friendly_destination")

    def test_illegal_piece_move(self):
        board = parse("wR .\n. .")
        v = RuleEngine().validate_move(board, Position(0, 0), Position(1, 1))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "illegal_piece_move")

    def test_allow_friendly_capture_policy(self):
        board = parse("wR wK")
        v = RuleEngine(allow_friendly_capture=True).validate_move(board, Position(0, 0), Position(0, 1))
        self.assertTrue(v.is_valid)

    def test_rook_blocked_by_friendly(self):
        board = parse("wR wP . .")
        v = RuleEngine().validate_move(board, Position(0, 0), Position(0, 3))
        self.assertFalse(v.is_valid)

    def test_no_movement_rule_returns_illegal(self):
        board = parse("wR .")
        v = RuleEngine(movements={PieceKind.KING: None}).validate_move(board, Position(0, 0), Position(0, 1))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "illegal_piece_move")


if __name__ == "__main__":
    unittest.main(verbosity=2)
