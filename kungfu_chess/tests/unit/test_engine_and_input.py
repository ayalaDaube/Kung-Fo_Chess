import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceColor, PieceKind, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.io.board_parser import BoardParser


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
        engine, board = make_engine("wR . .\n. . .\n. . .")
        v = engine._rule_engine.validate_move(board, Position(0, 0), Position(0, 2))
        self.assertTrue(v.is_valid)
        self.assertEqual(v.reason, "ok")

    def test_outside_board(self):
        engine, board = make_engine("wR .")
        v = engine._rule_engine.validate_move(board, Position(0, 0), Position(5, 5))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "outside_board")

    def test_empty_source(self):
        engine, board = make_engine("wR .")
        v = engine._rule_engine.validate_move(board, Position(0, 1), Position(0, 0))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "empty_source")

    def test_friendly_destination(self):
        engine, board = make_engine("wR wK")
        v = engine._rule_engine.validate_move(board, Position(0, 0), Position(0, 1))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "friendly_destination")

    def test_illegal_piece_move(self):
        engine, board = make_engine("wR .\n. .")
        v = engine._rule_engine.validate_move(board, Position(0, 0), Position(1, 1))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "illegal_piece_move")

    def test_allow_friendly_capture_policy(self):
        board = parse("wR wK")
        rule_engine = RuleEngine(allow_friendly_capture=True)
        arbiter = RealTimeArbiter(board)
        engine = GameEngine(board, rule_engine, arbiter)
        v = rule_engine.validate_move(board, Position(0, 0), Position(0, 1))
        self.assertTrue(v.is_valid)

    def test_rook_blocked_by_friendly(self):
        engine, board = make_engine("wR wP . .")
        v = engine._rule_engine.validate_move(board, Position(0, 0), Position(0, 3))
        self.assertFalse(v.is_valid)


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

class TestController(unittest.TestCase):

    def _setup(self, text: str):
        board = parse(text)
        rule_engine = RuleEngine()
        arbiter = RealTimeArbiter(board, ms_per_square=1000)
        engine = GameEngine(board, rule_engine, arbiter)
        mapper = BoardMapper(board.width, board.height, 100)
        controller = Controller(mapper, engine)
        return controller, engine, board

    def test_first_click_selects_piece(self):
        ctrl, _, _ = self._setup("wR . .")
        ctrl.click(50, 50)
        self.assertEqual(ctrl.selected_cell, Position(0, 0))

    def test_first_click_empty_ignored(self):
        ctrl, _, _ = self._setup("wR . .")
        ctrl.click(150, 50)
        self.assertIsNone(ctrl.selected_cell)

    def test_second_click_requests_move_and_clears(self):
        ctrl, _, _ = self._setup("wR . .")
        ctrl.click(50, 50)
        result = ctrl.click(250, 50)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "move_requested")

    def test_outside_click_with_selection_cancels(self):
        ctrl, _, _ = self._setup("wR . .")
        ctrl.click(50, 50)
        result = ctrl.click(9999, 9999)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "cancelled")

    def test_outside_click_without_selection_ignored(self):
        ctrl, _, _ = self._setup("wR . .")
        result = ctrl.click(9999, 9999)
        self.assertEqual(result.action, "ignored")

    def test_illegal_move_clears_selection(self):
        ctrl, _, _ = self._setup("wR . .\n. . .\n. . .")
        ctrl.click(50, 50)
        ctrl.click(150, 150)  # אלכסון — לא חוקי לצריח
        self.assertIsNone(ctrl.selected_cell)

    def test_jump_command(self):
        ctrl, _, _ = self._setup("wK . .")
        result = ctrl.jump(50, 50)
        self.assertEqual(result.action, "jump_requested")
        self.assertTrue(result.move_result.is_accepted)


# ── BoardParser / BoardPrinter ────────────────────────────────────────────────

class TestBoardParserPrinter(unittest.TestCase):

    def test_round_trip(self):
        from kungfu_chess.io.board_printer import BoardPrinter
        text = "wK . bR\n. . .\n. wN bK"
        board = BoardParser().parse(text)
        output = BoardPrinter().to_string(board)
        self.assertEqual(output, text)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
