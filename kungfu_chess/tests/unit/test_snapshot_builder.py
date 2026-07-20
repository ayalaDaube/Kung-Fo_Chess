"""
Unit tests for kungfu_chess.engine.snapshot_builder.
Pure logic — no I/O, no canvas.
"""
from __future__ import annotations
import unittest

from kungfu_chess.engine.snapshot_builder import build_snapshot, StatsProvider, _motion_info
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.model.game_state import MoveRecord
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.engine.game_engine import GameEngine


def _make(text: str, ms_per_square: int = 1000):
    board = BoardParser().parse(text)
    arbiter = RealTimeArbiter(ms_per_square=ms_per_square)
    return board, arbiter


class TestMotionInfo(unittest.TestCase):

    def test_settled_piece_returns_none_and_1(self):
        board, arbiter = _make("wR . .")
        piece = board.get_piece(Position(0, 0))
        target, t = _motion_info(piece, arbiter)
        self.assertIsNone(target)
        self.assertEqual(t, 1.0)

    def test_moving_piece_returns_target_and_progress(self):
        board, arbiter = _make("wR . .")
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        arbiter.advance_time(1000)  # halfway through 2000ms journey
        target, t = _motion_info(piece, arbiter)
        self.assertEqual(target, Position(0, 2))
        self.assertAlmostEqual(t, 0.5, places=1)

    def test_same_cell_motion_returns_none(self):
        board, arbiter = _make("wR .")
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 0))
        target, t = _motion_info(piece, arbiter)
        self.assertIsNone(target)
        self.assertEqual(t, 1.0)


class TestBuildSnapshot(unittest.TestCase):

    def test_board_dimensions(self):
        board, arbiter = _make("wR . .\n. . .")
        snap = build_snapshot(board, arbiter, selected_cell=None, game_over=False)
        self.assertEqual(snap.board_width, 3)
        self.assertEqual(snap.board_height, 2)

    def test_captured_piece_excluded(self):
        board, arbiter = _make("wR bK")
        engine = GameEngine(board, RuleEngine(), arbiter)
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.wait(1000)
        snap = engine.snapshot()
        self.assertEqual(len(snap.pieces), 1)
        self.assertEqual(snap.pieces[0].kind, PieceKind.ROOK)

    def test_selected_cell_passed_through(self):
        board, arbiter = _make("wR . .")
        snap = build_snapshot(board, arbiter, selected_cell=Position(0, 0), game_over=False)
        self.assertEqual(snap.selected_cell, Position(0, 0))

    def test_game_over_passed_through(self):
        board, arbiter = _make("wR . .")
        snap = build_snapshot(board, arbiter, selected_cell=None, game_over=True)
        self.assertTrue(snap.game_over)

    def test_airborne_pos_from_arbiter(self):
        board, arbiter = _make("wK . .")
        piece = board.get_piece(Position(0, 0))
        arbiter.start_jump(piece, Position(0, 0))
        snap = build_snapshot(board, arbiter, selected_cell=None, game_over=False)
        self.assertEqual(snap.airborne_pos, Position(0, 0))

    def test_no_stats_gives_empty_scores_and_history(self):
        board, arbiter = _make("wR . .")
        snap = build_snapshot(board, arbiter, selected_cell=None, game_over=False)
        self.assertEqual(snap.scores, {})
        self.assertEqual(snap.move_history, [])

    def test_stats_provider_scores_and_history_used(self):
        class FakeStats:
            @property
            def scores(self): return {PieceColor.WHITE: 5}
            @property
            def move_history(self): return [MoveRecord(1000, "Ra1", PieceColor.WHITE)]

        board, arbiter = _make("wR . .")
        snap = build_snapshot(board, arbiter, selected_cell=None, game_over=False,
                              stats=FakeStats())
        self.assertEqual(snap.scores[PieceColor.WHITE], 5)
        self.assertEqual(len(snap.move_history), 1)

    def test_stats_provider_protocol_satisfied_by_fake(self):
        class FakeStats:
            @property
            def scores(self): return {}
            @property
            def move_history(self): return []

        self.assertIsInstance(FakeStats(), StatsProvider)


class TestStatsProviderProtocol(unittest.TestCase):

    def test_object_missing_scores_not_stats_provider(self):
        class Bad:
            @property
            def move_history(self): return []

        self.assertNotIsInstance(Bad(), StatsProvider)

    def test_object_missing_move_history_not_stats_provider(self):
        class Bad:
            @property
            def scores(self): return {}

        self.assertNotIsInstance(Bad(), StatsProvider)


if __name__ == "__main__":
    unittest.main(verbosity=2)
