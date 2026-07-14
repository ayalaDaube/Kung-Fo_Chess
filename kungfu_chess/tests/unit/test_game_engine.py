from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.model.board import Board
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.engine.game_engine import GameEngine, MoveResult, MoveReason
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.rendering.snapshot_builder import build_snapshot


def parse(text: str) -> Board:
    return BoardParser().parse(text)


def make_engine(text: str, ms_per_square: int = 500) -> tuple[GameEngine, Board]:
    board = parse(text)
    arbiter = RealTimeArbiter(ms_per_square=ms_per_square)
    engine = GameEngine(board, RuleEngine(), arbiter)
    return engine, board


class TestGameEngine(unittest.TestCase):

    def test_valid_move_accepted(self):
        engine, _ = make_engine("wR . .\n. . .\n. . .")
        result = engine.request_move(Position(0, 0), Position(0, 2))
        self.assertTrue(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.OK)

    def test_invalid_move_rejected(self):
        engine, _ = make_engine("wR . .\n. . .\n. . .")
        result = engine.request_move(Position(0, 0), Position(1, 1))
        self.assertFalse(result.is_accepted)

    def test_empty_source_rejected(self):
        engine, _ = make_engine("wR . .")
        result = engine.request_move(Position(0, 1), Position(0, 2))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.EMPTY_SOURCE)

    def test_motion_in_progress_blocks_second_move(self):
        engine, _ = make_engine("wR . .\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        result = engine.request_move(Position(0, 0), Position(0, 1))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.MOTION_IN_PROGRESS)

    def test_game_over_blocks_moves(self):
        engine, _ = make_engine("wR . bK\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(2000)
        self.assertTrue(engine.game_over)
        result = engine.request_move(Position(0, 2), Position(0, 0))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.GAME_OVER)

    def test_game_over_blocks_jump(self):
        engine, _ = make_engine("wR . bK\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(2000)
        result = engine.request_jump(Position(0, 2))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.GAME_OVER)

    def test_jump_empty_source_rejected(self):
        engine, _ = make_engine("wK . .")
        result = engine.request_jump(Position(0, 1))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.EMPTY_SOURCE)

    def test_jump_motion_in_progress_blocked(self):
        engine, _ = make_engine("wK . .")
        engine.request_jump(Position(0, 0))
        result = engine.request_jump(Position(0, 0))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, MoveReason.MOTION_IN_PROGRESS)

    def test_wait_delegates_to_arbiter(self):
        engine, board = make_engine("wR . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(2000)
        self.assertIsNone(board.get_piece(Position(0, 0)))
        self.assertIsNotNone(board.get_piece(Position(0, 2)))

    def test_king_capture_sets_game_over(self):
        engine, _ = make_engine("wR bK")
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.wait(1000)
        self.assertTrue(engine.game_over)

    def test_king_eliminated_in_collision_sets_game_over(self):
        """King eliminated via EliminationEvent (simultaneous head-on collision) sets game_over."""
        engine, board = make_engine("wR bK", ms_per_square=1000)
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.request_move(Position(0, 1), Position(0, 0))
        engine.wait(1000)
        self.assertTrue(engine.game_over)

    def test_get_piece_at_returns_piece(self):
        engine, _ = make_engine("wR . .")
        piece = engine.get_piece_at(Position(0, 0))
        self.assertIsNotNone(piece)
        self.assertEqual(piece.kind, PieceKind.ROOK)

    def test_get_piece_at_returns_none_for_empty(self):
        engine, _ = make_engine("wR . .")
        self.assertIsNone(engine.get_piece_at(Position(0, 1)))

    def test_snapshot_idle_piece(self):
        engine, board = make_engine("wR . .", ms_per_square=1000)
        snap = build_snapshot(board, engine._arbiter, cell_size_px=100, selected_cell=None, game_over=False)
        self.assertEqual(snap.board_width, 3)
        self.assertEqual(snap.board_height, 1)
        self.assertFalse(snap.game_over)
        self.assertEqual(len(snap.pieces), 1)
        self.assertEqual(snap.pieces[0].pixel_x, 0)
        self.assertEqual(snap.pieces[0].pixel_y, 0)

    def test_snapshot_excludes_captured_piece(self):
        engine, board = make_engine("wR bK", ms_per_square=1000)
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.wait(1000)
        snap = build_snapshot(board, engine._arbiter, cell_size_px=100, selected_cell=None, game_over=True)
        self.assertEqual(len(snap.pieces), 1)
        self.assertEqual(snap.pieces[0].kind, PieceKind.ROOK)

    def test_snapshot_moving_piece_interpolation(self):
        engine, board = make_engine("wR . .", ms_per_square=1000)
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(1000)
        snap = build_snapshot(board, engine._arbiter, cell_size_px=100, selected_cell=None, game_over=False)
        px = snap.pieces[0].pixel_x
        self.assertGreater(px, 0)
        self.assertLess(px, 200)

    def test_snapshot_airborne_pos(self):
        engine, board = make_engine("wK . .", ms_per_square=1000)
        engine.request_jump(Position(0, 0))
        snap = build_snapshot(board, engine._arbiter, cell_size_px=100, selected_cell=None, game_over=False)
        self.assertEqual(snap.airborne_pos, Position(0, 0))

    def test_snapshot_zero_distance_motion(self):
        """Covers the `else 1.0` branch in build_snapshot when total_ms == 0 (same-cell motion)."""
        board = parse("wR .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 0))
        snap = build_snapshot(board, arbiter, cell_size_px=100, selected_cell=None, game_over=False)
        self.assertEqual(snap.pieces[0].pixel_x, 0)
        self.assertEqual(snap.pieces[0].pixel_y, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
