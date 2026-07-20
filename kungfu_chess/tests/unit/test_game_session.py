"""
Tests for GameSession using real GameEngine (no patching).
Fake engine factory injects a minimal board so tests are fast and deterministic.
"""
from __future__ import annotations
import asyncio
import unittest

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.model.piece import PieceColor
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.bus import topics
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand
from kungfu_chess.server.session.game_session import GameSession


def run(coro):
    return asyncio.run(coro)


# Minimal board: one white pawn at (6,4), one black pawn at (1,4)
_MINIMAL_BOARD = """\
. . . . bK . . .
. . . . bP . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . wP . . .
. . . . wK . . .
"""


def _make_engine() -> GameEngine:
    board = BoardParser().parse(_MINIMAL_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_session() -> tuple[GameSession, EventBus]:
    bus = EventBus()
    session = GameSession(bus=bus, engine_factory=_make_engine)
    return session, bus


class TestColorAssignment(unittest.TestCase):

    def test_first_connection_gets_white(self):
        session, _ = _make_session()
        color = session.assign_color("conn-1")
        self.assertEqual(color, PieceColor.WHITE)

    def test_second_connection_gets_black(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        color = session.assign_color("conn-2")
        self.assertEqual(color, PieceColor.BLACK)

    def test_color_for_returns_assigned_color(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        self.assertEqual(session.color_for("conn-1"), PieceColor.WHITE)

    def test_color_for_unknown_returns_none(self):
        session, _ = _make_session()
        self.assertIsNone(session.color_for("nobody"))


class TestSessionFull(unittest.TestCase):

    def test_not_full_initially(self):
        session, _ = _make_session()
        self.assertFalse(session.is_full())

    def test_full_after_two_connections(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        session.assign_color("conn-2")
        self.assertTrue(session.is_full())


class TestHandleCommand(unittest.TestCase):

    def test_valid_move_publishes_snapshot(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        received = []
        bus.subscribe(topics.SNAPSHOT, lambda s: received.append(s))

        cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(4, 4))
        result, snapshot = run(session.handle_command("conn-1", cmd))

        self.assertTrue(result.is_accepted)
        self.assertEqual(len(received), 1)

    def test_valid_move_publishes_move_accepted(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        accepted = []
        bus.subscribe(topics.MOVE_ACCEPTED, lambda r: accepted.append(r))

        cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(4, 4))
        run(session.handle_command("conn-1", cmd))

        self.assertEqual(len(accepted), 1)

    def test_invalid_move_publishes_move_rejected(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        rejected = []
        bus.subscribe(topics.MOVE_REJECTED, lambda r: rejected.append(r))

        cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(6, 4))
        result, _ = run(session.handle_command("conn-1", cmd))

        self.assertFalse(result.is_accepted)
        self.assertEqual(len(rejected), 1)

    def test_valid_jump_publishes_jump_accepted(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        accepted = []
        bus.subscribe(topics.JUMP_ACCEPTED, lambda r: accepted.append(r))

        cmd = JumpCommand(pos=Position(6, 4))
        result, _ = run(session.handle_command("conn-1", cmd))

        self.assertTrue(result.is_accepted)
        self.assertEqual(len(accepted), 1)


class TestHandleCommandSnapshot(unittest.TestCase):

    def test_captured_piece_excluded_from_snapshot(self):
        """After a king capture, the captured king must not appear in the snapshot."""
        board = BoardParser().parse("wR bK")
        engine = GameEngine(board=board, rule_engine=RuleEngine(),
                            arbiter=RealTimeArbiter(ms_per_square=500))
        bus = EventBus()
        session = GameSession(bus=bus, engine_factory=lambda: engine)
        session.assign_color("conn-1")

        cmd = MoveCommand(from_pos=Position(0, 0), to_pos=Position(0, 1))
        run(session.handle_command("conn-1", cmd))
        engine.wait(1000)  # piece arrives and captures king

        snapshot = session.build_snapshot()
        kinds = [p.kind for p in snapshot.pieces]
        from kungfu_chess.model.piece import PieceKind
        self.assertNotIn(PieceKind.KING, kinds)
        self.assertEqual(len(snapshot.pieces), 1)

    def test_scores_populated_when_stats_wired_in(self):
        """engine.snapshot(stats=tracker) must reflect captured piece scores."""
        from kungfu_chess.ui.game_stats_tracker import GameStatsTracker
        _SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}

        board = BoardParser().parse("wR bP")
        engine = GameEngine(board=board, rule_engine=RuleEngine(),
                            arbiter=RealTimeArbiter(ms_per_square=500))
        tracker = GameStatsTracker(board_height=board.height, piece_scores=_SCORES)

        engine.request_move(Position(0, 0), Position(0, 1))
        events = engine.wait(1000)
        tracker.process(events, 1000)

        snapshot = engine.snapshot(stats=tracker)
        from kungfu_chess.model.piece import PieceColor
        self.assertEqual(snapshot.scores[PieceColor.WHITE], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
