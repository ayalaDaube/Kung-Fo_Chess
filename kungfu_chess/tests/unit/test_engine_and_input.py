from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceColor, PieceKind, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine, MoveResult
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter


def parse(text: str) -> Board:
    return BoardParser().parse(text)


def make_engine(text: str, ms_per_square: int = 500) -> tuple[GameEngine, Board]:
    board = parse(text)
    rule_engine = RuleEngine()
    arbiter = RealTimeArbiter(board, ms_per_square=ms_per_square)
    engine = GameEngine(board, rule_engine, arbiter)
    return engine, board


# ── RuleEngine ────────────────────────────────────────────────────────────────

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
        # Pass a movements dict that has no entry for ROOK
        v = RuleEngine(movements={PieceKind.KING: None}).validate_move(board, Position(0, 0), Position(0, 1))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "illegal_piece_move")


# ── RealTimeArbiter ───────────────────────────────────────────────────────────

class TestRealTimeArbiter(unittest.TestCase):

    def test_no_active_motion_initially(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        self.assertFalse(arbiter.has_active_motion())

    def test_start_motion_sets_active(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        self.assertTrue(arbiter.has_active_motion())

    def test_partial_wait_no_arrival(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        events = arbiter.advance_time(999)
        self.assertEqual(events, [])
        self.assertTrue(arbiter.has_active_motion())

    def test_full_wait_arrival(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        events = arbiter.advance_time(2000)
        self.assertEqual(len(events), 1)
        self.assertFalse(arbiter.has_active_motion())
        self.assertIsNone(board.get_piece(Position(0, 0)))
        self.assertIsNotNone(board.get_piece(Position(0, 2)))

    def test_cumulative_wait(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        arbiter.advance_time(1000)
        events = arbiter.advance_time(1000)
        self.assertEqual(len(events), 1)

    def test_advance_time_no_motions_returns_empty(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        self.assertEqual(arbiter.advance_time(500), [])

    def test_jump_sets_airborne(self):
        board = parse("wK . .")
        arbiter = RealTimeArbiter(board, jump_duration_ms=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_jump(piece, Position(0, 0))
        self.assertEqual(arbiter.airborne_position(), Position(0, 0))

    def test_jump_resolves_clears_airborne(self):
        board = parse("wK . .")
        arbiter = RealTimeArbiter(board, jump_duration_ms=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_jump(piece, Position(0, 0))
        arbiter.advance_time(1000)
        self.assertIsNone(arbiter.airborne_position())
        self.assertEqual(board.get_piece(Position(0, 0)), piece)

    def test_has_active_motion_for_specific_piece(self):
        board = parse("wR . . bR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        wR = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(0, 3))
        arbiter.start_motion(wR, Position(0, 0), Position(0, 2))
        self.assertTrue(arbiter.has_active_motion(wR))
        self.assertFalse(arbiter.has_active_motion(bR))

    def test_get_motion_for_returns_none_when_idle(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        self.assertIsNone(arbiter.get_motion_for(piece))

    def test_get_motion_for_returns_motion_when_moving(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        motion = arbiter.get_motion_for(piece)
        self.assertIsNotNone(motion)
        self.assertIs(motion.piece, piece)

    def test_air_capture_arriving_piece_eliminated(self):
        board = parse("wK .\nbR .")
        arbiter = RealTimeArbiter(board, ms_per_square=1000, jump_duration_ms=2000)
        wK = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(1, 0))
        arbiter.start_jump(wK, Position(0, 0))
        arbiter.start_motion(bR, Position(1, 0), Position(0, 0))
        events = arbiter.advance_time(1000)
        # bR arrives at (0,0) where wK is airborne — bR is eliminated
        self.assertEqual(events, [])
        self.assertEqual(bR.state, PieceState.CAPTURED)
        self.assertIsNone(board.get_piece(Position(1, 0)))
        self.assertIsNotNone(board.get_piece(Position(0, 0)))  # wK still on board

    def test_ms_per_square_property(self):
        board = parse("wR .")
        arbiter = RealTimeArbiter(board, ms_per_square=750)
        self.assertEqual(arbiter.ms_per_square, 750)

    def test_collision_earlier_mover_loses(self):
        """Covers lines 112-114: piece arrives at destination while enemy still moving there — arrives first loses."""
        board = parse("wR . bR")
        # wR: half square at ms_per_square=500 -> 500ms; bR: 1 square -> 1000ms, both heading to (0,1)
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        wR = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(0, 2))
        # manually set different remaining_ms so wR arrives first
        arbiter.start_motion(wR, Position(0, 0), Position(0, 1))  # 1000ms
        arbiter.start_motion(bR, Position(0, 2), Position(0, 1))  # 1000ms
        # force wR to arrive first by reducing its remaining_ms
        arbiter._active_motions[0].remaining_ms = 500
        # after 500ms: wR arrives, bR still has 500ms left -> collision branch fires, bR loses
        arbiter.advance_time(500)
        self.assertEqual(bR.state, PieceState.CAPTURED)

    def test_pawn_promotion_to_queen(self):
        """Covers line 137: white pawn reaching row 0 becomes a queen."""
        board = parse("wP .\n. .")
        # place wP at row 1, move to row 0
        board2 = parse(". .\nwP .")
        arbiter = RealTimeArbiter(board2, ms_per_square=1000)
        pawn = board2.get_piece(Position(1, 0))
        arbiter.start_motion(pawn, Position(1, 0), Position(0, 0))
        arbiter.advance_time(1000)
        self.assertEqual(pawn.kind, PieceKind.QUEEN)


# ── GameEngine ────────────────────────────────────────────────────────────────

class TestGameEngine(unittest.TestCase):

    def test_valid_move_accepted(self):
        engine, _ = make_engine("wR . .\n. . .\n. . .")
        result = engine.request_move(Position(0, 0), Position(0, 2))
        self.assertTrue(result.is_accepted)
        self.assertEqual(result.reason, "ok")

    def test_invalid_move_rejected(self):
        engine, _ = make_engine("wR . .\n. . .\n. . .")
        result = engine.request_move(Position(0, 0), Position(1, 1))
        self.assertFalse(result.is_accepted)

    def test_empty_source_rejected(self):
        engine, _ = make_engine("wR . .")
        result = engine.request_move(Position(0, 1), Position(0, 2))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "empty_source")

    def test_motion_in_progress_blocks_second_move(self):
        engine, _ = make_engine("wR . .\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        result = engine.request_move(Position(0, 0), Position(0, 1))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "motion_in_progress")

    def test_game_over_blocks_moves(self):
        engine, _ = make_engine("wR . bK\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(2000)
        self.assertTrue(engine.game_over)
        result = engine.request_move(Position(0, 2), Position(0, 0))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "game_over")

    def test_game_over_blocks_jump(self):
        engine, _ = make_engine("wR . bK\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(2000)
        result = engine.request_jump(Position(0, 2))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "game_over")

    def test_jump_empty_source_rejected(self):
        engine, _ = make_engine("wK . .")
        result = engine.request_jump(Position(0, 1))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "empty_source")

    def test_jump_motion_in_progress_blocked(self):
        engine, _ = make_engine("wK . .")
        engine.request_jump(Position(0, 0))
        result = engine.request_jump(Position(0, 0))
        self.assertFalse(result.is_accepted)
        self.assertEqual(result.reason, "motion_in_progress")

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

    def test_get_piece_at_returns_piece(self):
        engine, _ = make_engine("wR . .")
        piece = engine.get_piece_at(Position(0, 0))
        self.assertIsNotNone(piece)
        self.assertEqual(piece.kind, PieceKind.ROOK)

    def test_get_piece_at_returns_none_for_empty(self):
        engine, _ = make_engine("wR . .")
        self.assertIsNone(engine.get_piece_at(Position(0, 1)))

    def test_snapshot_idle_piece(self):
        engine, _ = make_engine("wR . .", ms_per_square=1000)
        snap = engine.snapshot(cell_size_px=100)
        self.assertEqual(snap.board_width, 3)
        self.assertEqual(snap.board_height, 1)
        self.assertFalse(snap.game_over)
        self.assertEqual(len(snap.pieces), 1)
        self.assertEqual(snap.pieces[0].pixel_x, 0)
        self.assertEqual(snap.pieces[0].pixel_y, 0)

    def test_snapshot_moving_piece_interpolation(self):
        engine, _ = make_engine("wR . .", ms_per_square=1000)
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(1000)  # halfway through 2000ms journey
        snap = engine.snapshot(cell_size_px=100)
        px = snap.pieces[0].pixel_x
        self.assertGreater(px, 0)
        self.assertLess(px, 200)

    def test_snapshot_airborne_pos(self):
        engine, _ = make_engine("wK . .", ms_per_square=1000)
        engine.request_jump(Position(0, 0))
        snap = engine.snapshot()
        self.assertEqual(snap.airborne_pos, Position(0, 0))

    def test_snapshot_zero_distance_motion(self):
        """Covers the `else 1.0` branch in snapshot when total_ms == 0 (same-cell motion)."""
        engine, board = make_engine("wR .", ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        # Manually inject a motion with to_pos == from_pos so total_ms == 0
        engine._arbiter.start_motion(piece, Position(0, 0), Position(0, 0))
        snap = engine.snapshot(cell_size_px=100)
        self.assertEqual(snap.pieces[0].pixel_x, 0)
        self.assertEqual(snap.pieces[0].pixel_y, 0)


# ── BoardMapper ───────────────────────────────────────────────────────────────

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


# ── Controller ────────────────────────────────────────────────────────────────

class FakeEngine:
    """Minimal fake GameEngine for Controller unit tests — no real logic."""

    def __init__(self, piece_at: dict = None, move_accepted: bool = True, jump_accepted: bool = True):
        self._piece_at = piece_at or {}  # Position -> Piece or None
        self._move_result = MoveResult(move_accepted, "ok" if move_accepted else "illegal_piece_move")
        self._jump_result = MoveResult(jump_accepted, "ok" if jump_accepted else "motion_in_progress")
        self.move_calls = []   # records (source, destination)
        self.jump_calls = []   # records pos

    def get_piece_at(self, pos: Position):
        return self._piece_at.get(pos)

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        self.move_calls.append((source, destination))
        return self._move_result

    def request_jump(self, pos: Position) -> MoveResult:
        self.jump_calls.append(pos)
        return self._jump_result


def _piece(pos: Position) -> Piece:
    return Piece("p1", PieceColor.WHITE, PieceKind.ROOK, pos)


class TestController(unittest.TestCase):

    def _ctrl(self, cols=3, rows=1, piece_at=None, move_accepted=True, jump_accepted=True):
        engine = FakeEngine(piece_at=piece_at, move_accepted=move_accepted, jump_accepted=jump_accepted)
        mapper = BoardMapper(cols, rows, 100)
        return Controller(mapper, engine), engine

    def test_first_click_selects_piece(self):
        p = _piece(Position(0, 0))
        ctrl, _ = self._ctrl(piece_at={Position(0, 0): p})
        ctrl.click(50, 50)
        self.assertEqual(ctrl.selected_cell, Position(0, 0))

    def test_first_click_empty_ignored(self):
        ctrl, _ = self._ctrl()
        ctrl.click(150, 50)
        self.assertIsNone(ctrl.selected_cell)

    def test_second_click_requests_move_and_clears(self):
        p = _piece(Position(0, 0))
        ctrl, engine = self._ctrl(piece_at={Position(0, 0): p})
        ctrl.click(50, 50)
        result = ctrl.click(250, 50)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "move_requested")
        self.assertEqual(engine.move_calls, [(Position(0, 0), Position(0, 2))])

    def test_second_click_rejected_move_clears_selection(self):
        p = _piece(Position(0, 0))
        ctrl, _ = self._ctrl(piece_at={Position(0, 0): p}, move_accepted=False)
        ctrl.click(50, 50)
        result = ctrl.click(250, 50)
        self.assertIsNone(ctrl.selected_cell)
        self.assertFalse(result.move_result.is_accepted)

    def test_outside_click_with_selection_cancels(self):
        p = _piece(Position(0, 0))
        ctrl, _ = self._ctrl(piece_at={Position(0, 0): p})
        ctrl.click(50, 50)
        result = ctrl.click(9999, 9999)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "cancelled")

    def test_outside_click_without_selection_ignored(self):
        ctrl, _ = self._ctrl()
        result = ctrl.click(9999, 9999)
        self.assertEqual(result.action, "ignored")

    def test_jump_command_accepted(self):
        p = _piece(Position(0, 0))
        ctrl, engine = self._ctrl(piece_at={Position(0, 0): p})
        result = ctrl.jump(50, 50)
        self.assertEqual(result.action, "jump_requested")
        self.assertTrue(result.move_result.is_accepted)
        self.assertEqual(engine.jump_calls, [Position(0, 0)])

    def test_jump_outside_board_ignored(self):
        ctrl, engine = self._ctrl()
        result = ctrl.jump(9999, 9999)
        self.assertEqual(result.action, "ignored")
        self.assertEqual(engine.jump_calls, [])

    def test_second_click_reselects_same_color_piece(self):
        """Covers lines 56-57: second click on a friendly piece re-selects it."""
        p1 = Piece("p1", PieceColor.WHITE, PieceKind.ROOK, Position(0, 0))
        p2 = Piece("p2", PieceColor.WHITE, PieceKind.ROOK, Position(0, 1))
        ctrl, _ = self._ctrl(cols=3, rows=1, piece_at={Position(0, 0): p1, Position(0, 1): p2})
        ctrl.click(50, 50)   # select p1
        result = ctrl.click(150, 50)  # click on p2 (same color)
        self.assertEqual(result.action, "selected")
        self.assertEqual(ctrl.selected_cell, Position(0, 1))


# ── BoardParser / BoardPrinter ────────────────────────────────────────────────

class TestBoardParserPrinter(unittest.TestCase):

    def test_round_trip(self):
        text = "wK . bR\n. . .\n. wN bK"
        board = BoardParser().parse(text)
        output = BoardPrinter().to_string(board)
        self.assertEqual(output, text)

    def test_print_outputs_to_stdout(self):
        import io, sys
        board = BoardParser().parse("wK .")
        captured = io.StringIO()
        sys.stdout = captured
        BoardPrinter().print(board)
        sys.stdout = sys.__stdout__
        self.assertIn("wK", captured.getvalue())

    def test_row_width_mismatch(self):
        with self.assertRaises(ValueError) as ctx:
            BoardParser().parse("wK .\nwR")
        self.assertIn("ROW_WIDTH_MISMATCH", str(ctx.exception))

    def test_unknown_token(self):
        with self.assertRaises(ValueError) as ctx:
            BoardParser().parse("wK XX")
        self.assertIn("UNKNOWN_TOKEN", str(ctx.exception))

    def test_single_cell(self):
        board = BoardParser().parse("wK")
        self.assertEqual(board.width, 1)
        self.assertEqual(board.height, 1)


# ── Board edge cases ──────────────────────────────────────────────────────────

class TestBoardEdgeCases(unittest.TestCase):

    def test_remove_piece_from_empty_cell_returns_none(self):
        board = Board(3, 3)
        result = board.remove_piece(Position(0, 0))
        self.assertIsNone(result)


# ── ConfigLoader ──────────────────────────────────────────────────────────────

class TestConfigLoader(unittest.TestCase):

    def test_missing_file_uses_defaults(self):
        from kungfu_chess.config_loader import load_config
        config = load_config(path="nonexistent_file.json")
        self.assertEqual(config.ms_per_pixel, 10)
        self.assertEqual(config.ms_per_square, 1000)
        self.assertEqual(config.jump_duration_ms, 1000)
        self.assertEqual(config.cell_size, 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
