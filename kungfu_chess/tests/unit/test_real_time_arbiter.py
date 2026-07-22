from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import PieceKind, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.realtime.motion import ArrivalEvent, EliminationEvent
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser


def parse(text: str) -> Board:
    return BoardParser().parse(text)


def make_engine(text: str, ms_per_square: int = 500, jump_duration_ms: int = 1000) -> tuple[GameEngine, Board]:
    board = parse(text)
    arbiter = RealTimeArbiter(ms_per_square=ms_per_square, jump_duration_ms=jump_duration_ms)
    engine = GameEngine(board, RuleEngine(), arbiter)
    return engine, board


class TestRealTimeArbiter(unittest.TestCase):

    def test_no_active_motion_initially(self):
        arbiter = RealTimeArbiter(ms_per_square=1000)
        self.assertFalse(arbiter.has_active_motion())

    def test_start_motion_sets_active(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        self.assertTrue(arbiter.has_active_motion())

    def test_partial_wait_no_arrival(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        events = arbiter.advance_time(999)
        self.assertEqual(events, [])
        self.assertTrue(arbiter.has_active_motion())

    def test_full_wait_arrival_event(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        events = arbiter.advance_time(2000)
        arrival_events = [e for e in events if isinstance(e, ArrivalEvent)]
        self.assertEqual(len(arrival_events), 1)
        self.assertFalse(arbiter.has_active_motion())

    def test_full_wait_board_updated_via_engine(self):
        engine, board = make_engine("wR . .", ms_per_square=1000)
        engine.request_move(Position(0, 0), Position(0, 2))
        engine.wait(2000)
        self.assertIsNone(board.get_piece(Position(0, 0)))
        self.assertIsNotNone(board.get_piece(Position(0, 2)))

    def test_cumulative_wait(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        arbiter.advance_time(1000)
        events = arbiter.advance_time(1000)
        arrival_events = [e for e in events if isinstance(e, ArrivalEvent)]
        self.assertEqual(len(arrival_events), 1)

    def test_advance_time_no_motions_returns_empty(self):
        arbiter = RealTimeArbiter(ms_per_square=1000)
        self.assertEqual(arbiter.advance_time(500), [])

    def test_jump_sets_airborne(self):
        board = parse("wK . .")
        arbiter = RealTimeArbiter(jump_duration_ms=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_jump(piece, Position(0, 0))
        self.assertEqual(arbiter.airborne_position(), Position(0, 0))

    def test_jump_resolves_clears_airborne(self):
        engine, board = make_engine("wK . .", jump_duration_ms=1000)
        engine.request_jump(Position(0, 0))
        engine.wait(1000)
        self.assertIsNone(engine._arbiter.airborne_position())
        self.assertEqual(board.get_piece(Position(0, 0)).kind, PieceKind.KING)

    def test_has_active_motion_for_specific_piece(self):
        board = parse("wR . . bR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        wR = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(0, 3))
        arbiter.start_motion(wR, Position(0, 0), Position(0, 2))
        self.assertTrue(arbiter.has_active_motion(wR))
        self.assertFalse(arbiter.has_active_motion(bR))

    def test_get_motion_for_returns_none_when_idle(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        self.assertIsNone(arbiter.get_motion_for(piece))

    def test_get_motion_for_returns_motion_when_moving(self):
        board = parse("wR . .")
        arbiter = RealTimeArbiter(ms_per_square=1000)
        piece = board.get_piece(Position(0, 0))
        arbiter.start_motion(piece, Position(0, 0), Position(0, 2))
        motion = arbiter.get_motion_for(piece)
        self.assertIsNotNone(motion)
        self.assertIs(motion.piece, piece)

    def test_air_capture_arriving_piece_eliminated(self):
        engine, board = make_engine("wK .\nbR .", ms_per_square=1000, jump_duration_ms=2000)
        wK = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(1, 0))
        engine.request_jump(Position(0, 0))
        engine.request_move(Position(1, 0), Position(0, 0))
        engine.wait(1000)
        self.assertEqual(bR.state, PieceState.CAPTURED)
        self.assertIsNone(board.get_piece(Position(1, 0)))
        self.assertIsNotNone(board.get_piece(Position(0, 0)))

    def test_ms_per_square_property(self):
        arbiter = RealTimeArbiter(ms_per_square=750)
        self.assertEqual(arbiter.ms_per_square, 750)

    def test_collision_earlier_mover_wins(self):
        """Piece arrives at destination while enemy still moving there — the later mover loses."""
        engine, board = make_engine("wR . bR", ms_per_square=1000)
        wR = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(0, 2))
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.request_move(Position(0, 2), Position(0, 1))
        engine._arbiter.get_motion_for(wR).set_remaining_ms(500)
        engine.wait(500)
        self.assertEqual(bR.state, PieceState.CAPTURED)

    def test_pawn_promotion_to_queen(self):
        """White pawn reaching row 0 becomes a queen via GameEngine promotion policy."""
        engine, board = make_engine(". .\nwP .", ms_per_square=1000)
        engine.request_move(Position(1, 0), Position(0, 0))
        engine.wait(1000)
        pawn = board.get_piece(Position(0, 0))
        self.assertEqual(pawn.kind, PieceKind.QUEEN)

    def test_simultaneous_head_on_swap_loser_eliminated(self):
        """Two enemies heading to each other's source simultaneously — earlier index wins."""
        engine, board = make_engine("wR bR", ms_per_square=1000)
        wR = board.get_piece(Position(0, 0))
        bR = board.get_piece(Position(0, 1))
        engine.request_move(Position(0, 0), Position(0, 1))
        engine.request_move(Position(0, 1), Position(0, 0))
        engine.wait(1000)
        self.assertEqual(bR.state, PieceState.CAPTURED)
        self.assertNotEqual(wR.state, PieceState.CAPTURED)

    def test_air_capture_same_color_not_eliminated(self):
        """Arriving friendly piece reaching airborne friendly cell — no elimination."""
        engine, board = make_engine("wK .\nwR .", ms_per_square=1000, jump_duration_ms=2000)
        wK = board.get_piece(Position(0, 0))
        wR = board.get_piece(Position(1, 0))
        engine.request_jump(Position(0, 0))
        engine.request_move(Position(1, 0), Position(0, 0))
        engine.wait(1000)
        self.assertNotEqual(wR.state, PieceState.CAPTURED)


class TestAirborneBug2a(unittest.TestCase):
    """
    Bug 2a: _resolve_move() used to unconditionally clear _airborne_pos,
    wiping the airborne marker of an unrelated jumping piece.
    """

    def test_unrelated_move_does_not_clear_airborne_marker(self):
        """
        wK jumps (duration 2000 ms).  wR moves one square (arrives at 500 ms).
        After the rook arrives, the king must still be marked airborne.
        """
        engine, board = make_engine("wK . .\nwR . .", ms_per_square=500, jump_duration_ms=2000)
        engine.request_jump(Position(0, 0))    # wK airborne for 2000 ms
        engine.request_move(Position(1, 0), Position(1, 1))  # wR moves, arrives at 500 ms
        engine.wait(500)   # rook arrives — must NOT clear king's airborne marker
        self.assertEqual(engine._arbiter.airborne_position(), Position(0, 0))

    def test_airborne_clears_only_when_jump_resolves(self):
        """
        After the jump duration expires the marker must be gone.
        """
        engine, board = make_engine("wK . .\nwR . .", ms_per_square=500, jump_duration_ms=1000)
        engine.request_jump(Position(0, 0))
        engine.request_move(Position(1, 0), Position(1, 1))
        engine.wait(500)   # rook arrives — king still airborne
        self.assertIsNotNone(engine._arbiter.airborne_position())
        engine.wait(500)   # jump resolves
        self.assertIsNone(engine._arbiter.airborne_position())


class TestAirborneBug2b(unittest.TestCase):
    """
    Bug 2b (design a): only one piece may be airborne at a time.
    A second jump while _airborne_pos is set must be rejected.
    """

    def test_second_jump_rejected_while_first_airborne(self):
        """
        wK jumps successfully.  wR attempts to jump while wK is still airborne
        — must be rejected (MOTION_IN_PROGRESS).
        """
        from kungfu_chess.engine.game_engine import MoveReason
        engine, board = make_engine("wK .\nwR .", jump_duration_ms=2000)
        result1 = engine.request_jump(Position(0, 0))   # wK jumps
        result2 = engine.request_jump(Position(1, 0))   # wR tries to jump
        self.assertTrue(result1.is_accepted)
        self.assertFalse(result2.is_accepted)
        self.assertEqual(result2.reason, MoveReason.MOTION_IN_PROGRESS)

    def test_second_jump_accepted_after_first_lands(self):
        """
        After the first jump resolves, a new jump must be accepted.
        """
        engine, board = make_engine("wK .\nwR .", jump_duration_ms=500)
        engine.request_jump(Position(0, 0))
        engine.wait(500)   # wK lands
        self.assertIsNone(engine._arbiter.airborne_position())
        result = engine.request_jump(Position(1, 0))
        self.assertTrue(result.is_accepted)

    def test_airborne_marker_not_overwritten_by_rejected_jump(self):
        """
        The rejected second jump must not change _airborne_pos.
        """
        engine, board = make_engine("wK .\nwR .", jump_duration_ms=2000)
        engine.request_jump(Position(0, 0))
        engine.request_jump(Position(1, 0))   # rejected
        self.assertEqual(engine._arbiter.airborne_position(), Position(0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
