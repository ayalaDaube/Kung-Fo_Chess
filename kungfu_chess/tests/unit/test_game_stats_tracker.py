from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import PieceKind, PieceColor
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.rendering.game_stats_tracker import GameStatsTracker

_DEFAULT_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def make_engine(text: str, ms_per_square: int = 1000) -> tuple[GameEngine, GameStatsTracker]:
    board = BoardParser().parse(text)
    arbiter = RealTimeArbiter(ms_per_square=ms_per_square)
    engine = GameEngine(board, RuleEngine(), arbiter)
    tracker = GameStatsTracker(board_height=board.height, piece_scores=_DEFAULT_SCORES)
    return engine, tracker


def run(engine: GameEngine, tracker: GameStatsTracker, ms: int) -> None:
    events = engine.wait(ms)
    tracker.process(events, ms)


class TestGameStatsTrackerScores(unittest.TestCase):

    def test_initial_scores_are_zero(self):
        _, tracker = make_engine("wR bP")
        self.assertEqual(tracker.scores[PieceColor.WHITE], 0)
        self.assertEqual(tracker.scores[PieceColor.BLACK], 0)

    def test_capturing_pawn_adds_1(self):
        engine, tracker = make_engine("wR bP")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 1)

    def test_capturing_rook_adds_5(self):
        engine, tracker = make_engine("wR bR")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 5)

    def test_capturing_queen_adds_9(self):
        engine, tracker = make_engine("wR bQ")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 9)

    def test_capturing_knight_adds_3(self):
        engine, tracker = make_engine("wR bN")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 3)

    def test_capturing_bishop_adds_3(self):
        engine, tracker = make_engine("wR bB")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 3)

    def test_capturing_king_adds_0(self):
        engine, tracker = make_engine("wR bK")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 0)

    def test_black_captures_white_updates_black_score(self):
        engine, tracker = make_engine("wP bR")
        engine.request_move(Position(0, 1), Position(0, 0))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.scores[PieceColor.BLACK], 1)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 0)

    def test_scores_accumulate_across_multiple_captures(self):
        engine, tracker = make_engine("wR bP . bN")
        engine.request_move(Position(0, 0), Position(0, 1))
        run(engine, tracker, 1000)   # arrives at bP, enters LONG_REST
        run(engine, tracker, 1000)   # rest ends, back to IDLE
        engine.request_move(Position(0, 1), Position(0, 3))
        run(engine, tracker, 2000)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 4)  # 1 + 3

    def test_scores_returns_copy(self):
        _, tracker = make_engine("wR bP")
        tracker.scores[PieceColor.WHITE] = 99
        self.assertEqual(tracker.scores[PieceColor.WHITE], 0)


class TestGameStatsTrackerMoveHistory(unittest.TestCase):

    def test_initial_history_is_empty(self):
        _, tracker = make_engine("wR . .")
        self.assertEqual(tracker.move_history, [])

    def test_move_recorded_after_arrival(self):
        engine, tracker = make_engine("wR . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        run(engine, tracker, 2000)   # distance=2, ms_per_square=1000
        self.assertEqual(len(tracker.move_history), 1)

    def test_move_notation_rook(self):
        # board "wR . ." is 1 row x 3 cols, board_height=1
        # destination col=2 -> 'c', row = 1 - 0 = 1 -> "Rc1"
        engine, tracker = make_engine("wR . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        run(engine, tracker, 2000)
        self.assertEqual(tracker.move_history[0].notation, "Rc1")

    def test_move_notation_pawn_has_no_piece_prefix(self):
        # board ". . .\nwP . ." is 2 rows x 3 cols, board_height=2
        # pawn moves from (1,0) to (0,0): col='a', row = 2 - 0 = 2 -> "a2"
        engine, tracker = make_engine(". . .\nwP . .")
        engine.request_move(Position(1, 0), Position(0, 0))
        run(engine, tracker, 1000)
        self.assertEqual(tracker.move_history[0].notation, "a2")

    def test_move_color_recorded_correctly(self):
        engine, tracker = make_engine("wR . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        run(engine, tracker, 2000)
        self.assertEqual(tracker.move_history[0].color, PieceColor.WHITE)

    def test_elapsed_ms_recorded(self):
        engine, tracker = make_engine("wR . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        run(engine, tracker, 2000)
        self.assertEqual(tracker.move_history[0].elapsed_ms, 2000)

    def test_elapsed_ms_accumulates_across_calls(self):
        engine, tracker = make_engine("wR . . . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        run(engine, tracker, 2000)   # arrives, enters LONG_REST
        run(engine, tracker, 1000)   # rest ends, back to IDLE
        engine.request_move(Position(0, 2), Position(0, 4))
        run(engine, tracker, 2000)   # second move arrives
        self.assertEqual(tracker.move_history[1].elapsed_ms, 5000)

    def test_move_history_separates_by_color(self):
        engine, tracker = make_engine("wR . bR . .")
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.request_move(Position(0, 2), Position(0, 3))
        run(engine, tracker, 2000)
        white_moves = [m for m in tracker.move_history if m.color == PieceColor.WHITE]
        black_moves = [m for m in tracker.move_history if m.color == PieceColor.BLACK]
        self.assertEqual(len(white_moves), 1)
        self.assertEqual(len(black_moves), 1)

    def test_move_history_returns_copy(self):
        _, tracker = make_engine("wR . .")
        tracker.move_history.append("fake")
        self.assertEqual(tracker.move_history, [])

    def test_notation_row_uses_board_height_not_hardcoded(self):
        """On a 4-row board, piece at row=0 should show row=4, not row=8."""
        engine, tracker = make_engine("wR . .\n. . .\n. . .\n. . .")
        engine.request_move(Position(0, 0), Position(0, 2))
        run(engine, tracker, 2000)
        # board_height=4, destination row=0 -> 4 - 0 = 4 -> "Rc4"
        self.assertEqual(tracker.move_history[0].notation, "Rc4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
