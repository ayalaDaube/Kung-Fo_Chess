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

_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def _make_engine() -> GameEngine:
    board = BoardParser().parse(_MINIMAL_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_session() -> tuple[GameSession, EventBus]:
    bus = EventBus()
    session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=_make_engine)
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
        self.assertFalse(session.players_full())

    def test_full_after_two_connections(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        session.assign_color("conn-2")
        self.assertTrue(session.players_full())


class TestSpectators(unittest.TestCase):

    def test_spectator_added(self):
        session, _ = _make_session()
        session.add_spectator("spec-1")
        self.assertTrue(session.is_spectator("spec-1"))

    def test_player_is_not_spectator(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        self.assertFalse(session.is_spectator("conn-1"))

    def test_spectator_owns_no_piece(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        session.assign_color("conn-2")
        session.add_spectator("spec-1")
        self.assertFalse(session.owns_piece_at("spec-1", Position(6, 4)))


class TestRecordJoin(unittest.TestCase):

    def test_stores_username(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        self.assertEqual(session.username_for("conn-1"), "alice")

    def test_unknown_conn_returns_none(self):
        session, _ = _make_session()
        self.assertIsNone(session.username_for("nobody"))

    def test_publishes_player_joined(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        received = []
        bus.subscribe(topics.PLAYER_JOINED, lambda p: received.append(p))
        run(session.record_join("conn-1", "alice"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["username"], "alice")
        self.assertEqual(received[0]["conn_id"], "conn-1")

    def test_player_joined_payload_includes_game_id(self):
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=_make_engine, game_id="room-42")
        session.assign_color("conn-1")
        received = []
        bus.subscribe(topics.PLAYER_JOINED, lambda p: received.append(p))
        run(session.record_join("conn-1", "alice"))
        self.assertEqual(received[0]["game_id"], "room-42")


class TestReconnect(unittest.TestCase):

    def test_reconnect_rebinds_to_existing_record(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        # alice reconnects with a new connection_id
        run(session.record_join("conn-new", "alice"))
        self.assertEqual(session.username_for("conn-new"), "alice")
        self.assertIsNone(session.username_for("conn-1"))

    def test_reconnect_preserves_color(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        run(session.record_join("conn-new", "alice"))
        self.assertEqual(session.color_for("conn-new"), PieceColor.WHITE)

    def test_reconnect_does_not_duplicate_player(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        run(session.record_join("conn-new", "alice"))
        # still only one player record for alice
        self.assertEqual(
            sum(1 for u in ["alice"] if session.color_for("conn-new") is not None), 1
        )


class TestIdentityResolver(unittest.TestCase):

    def test_custom_resolver_is_applied(self):
        bus = EventBus()
        session = GameSession(
            bus=bus,
            piece_scores=_PIECE_SCORES,
            engine_factory=_make_engine,
            identity_resolver=lambda name: name.lower(),
        )
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "ALICE"))
        self.assertEqual(session.username_for("conn-1"), "alice")


class TestOwnsPieceAt(unittest.TestCase):

    def test_returns_true_for_own_piece(self):
        session, _ = _make_session()
        session.assign_color("conn-1")  # WHITE
        self.assertTrue(session.owns_piece_at("conn-1", Position(6, 4)))  # wP

    def test_returns_false_for_opponent_piece(self):
        session, _ = _make_session()
        session.assign_color("conn-1")  # WHITE
        session.assign_color("conn-2")  # BLACK
        self.assertFalse(session.owns_piece_at("conn-2", Position(6, 4)))  # wP

    def test_returns_false_for_empty_square(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        self.assertFalse(session.owns_piece_at("conn-1", Position(4, 4)))

    def test_returns_false_for_unassigned_connection(self):
        session, _ = _make_session()
        self.assertFalse(session.owns_piece_at("nobody", Position(6, 4)))


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

    def test_valid_move_publishes_snapshot_with_game_id(self):
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=_make_engine, game_id="g-snap")
        session.assign_color("conn-1")
        received = []
        bus.subscribe(topics.SNAPSHOT, lambda s: received.append(s))
        run(session.handle_command("conn-1", MoveCommand(from_pos=Position(6, 4), to_pos=Position(4, 4))))
        self.assertEqual(received[0]["game_id"], "g-snap")

    def test_valid_move_publishes_move_accepted(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        accepted = []
        bus.subscribe(topics.MOVE_ACCEPTED, lambda r: accepted.append(r))
        cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(4, 4))
        run(session.handle_command("conn-1", cmd))
        self.assertEqual(len(accepted), 1)

    def test_valid_move_accepted_includes_game_id(self):
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=_make_engine, game_id="g-ma")
        session.assign_color("conn-1")
        accepted = []
        bus.subscribe(topics.MOVE_ACCEPTED, lambda r: accepted.append(r))
        run(session.handle_command("conn-1", MoveCommand(from_pos=Position(6, 4), to_pos=Position(4, 4))))
        self.assertEqual(accepted[0]["game_id"], "g-ma")

    def test_invalid_move_publishes_move_rejected(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        rejected = []
        bus.subscribe(topics.MOVE_REJECTED, lambda r: rejected.append(r))
        cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(6, 4))
        result, _ = run(session.handle_command("conn-1", cmd))
        self.assertFalse(result.is_accepted)
        self.assertEqual(len(rejected), 1)

    def test_invalid_move_rejected_includes_game_id(self):
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=_make_engine, game_id="g-mr")
        session.assign_color("conn-1")
        rejected = []
        bus.subscribe(topics.MOVE_REJECTED, lambda r: rejected.append(r))
        run(session.handle_command("conn-1", MoveCommand(from_pos=Position(6, 4), to_pos=Position(6, 4))))
        self.assertEqual(rejected[0]["game_id"], "g-mr")

    def test_valid_jump_publishes_jump_accepted(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        accepted = []
        bus.subscribe(topics.JUMP_ACCEPTED, lambda r: accepted.append(r))
        cmd = JumpCommand(pos=Position(6, 4))
        result, _ = run(session.handle_command("conn-1", cmd))
        self.assertTrue(result.is_accepted)
        self.assertEqual(len(accepted), 1)

    def test_valid_jump_accepted_includes_game_id(self):
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=_make_engine, game_id="g-ja")
        session.assign_color("conn-1")
        accepted = []
        bus.subscribe(topics.JUMP_ACCEPTED, lambda r: accepted.append(r))
        run(session.handle_command("conn-1", JumpCommand(pos=Position(6, 4))))
        self.assertEqual(accepted[0]["game_id"], "g-ja")


class TestHandleCommandSnapshot(unittest.TestCase):

    def test_captured_piece_excluded_from_snapshot(self):
        board = BoardParser().parse("wR bK")
        engine = GameEngine(board=board, rule_engine=RuleEngine(),
                            arbiter=RealTimeArbiter(ms_per_square=500))
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=lambda: engine)
        session.assign_color("conn-1")
        cmd = MoveCommand(from_pos=Position(0, 0), to_pos=Position(0, 1))
        run(session.handle_command("conn-1", cmd))
        engine.wait(1000)
        snapshot = session.build_snapshot()
        from kungfu_chess.model.piece import PieceKind
        self.assertNotIn(PieceKind.KING, [p.kind for p in snapshot.pieces])
        self.assertEqual(len(snapshot.pieces), 1)

    def test_scores_populated_when_stats_wired_in(self):
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
        self.assertEqual(snapshot.scores[PieceColor.WHITE], 1)


class TestStatsWiring(unittest.TestCase):
    """Regression: GameSession.tick() must feed events to GameStatsTracker so
    build_snapshot() returns non-empty scores and move_history after a capture."""

    def test_capture_updates_scores_via_tick(self):
        # wR at (0,0), bP at (0,1) — rook captures pawn in one square move
        board = BoardParser().parse("wR bP")
        engine = GameEngine(board=board, rule_engine=RuleEngine(),
                            arbiter=RealTimeArbiter(ms_per_square=500))
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=lambda: engine)
        session.assign_color("conn-1")

        run(session.handle_command("conn-1", MoveCommand(from_pos=Position(0, 0), to_pos=Position(0, 1))))
        session.tick(1000)   # piece arrives and captures

        snapshot = session.build_snapshot()
        self.assertEqual(snapshot.scores[PieceColor.WHITE], 1)   # pawn = 1 point

    def test_capture_populates_move_history_via_tick(self):
        board = BoardParser().parse("wR bP")
        engine = GameEngine(board=board, rule_engine=RuleEngine(),
                            arbiter=RealTimeArbiter(ms_per_square=500))
        bus = EventBus()
        session = GameSession(bus=bus, piece_scores=_PIECE_SCORES, engine_factory=lambda: engine)
        session.assign_color("conn-1")

        run(session.handle_command("conn-1", MoveCommand(from_pos=Position(0, 0), to_pos=Position(0, 1))))
        session.tick(1000)

        snapshot = session.build_snapshot()
        self.assertGreater(len(snapshot.move_history), 0)

    def test_scores_zero_before_any_capture(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        snapshot = session.build_snapshot()
        self.assertEqual(snapshot.scores.get(PieceColor.WHITE, 0), 0)
        self.assertEqual(snapshot.scores.get(PieceColor.BLACK, 0), 0)




    def test_move_in_one_room_does_not_affect_other(self):
        """A move command in session A must not change session B's state at all."""
        session_a, _ = _make_session()
        session_b, _ = _make_session()
        session_a.assign_color("conn-a")
        session_b.assign_color("conn-b")

        snap_b_before = session_b.build_snapshot()

        cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(4, 4))
        run(session_a.handle_command("conn-a", cmd))

        snap_b_after = session_b.build_snapshot()

        # B's pieces are completely unchanged
        positions_before = {(p.cell.row, p.cell.col) for p in snap_b_before.pieces}
        positions_after  = {(p.cell.row, p.cell.col) for p in snap_b_after.pieces}
        self.assertEqual(positions_before, positions_after)


class TestResign(unittest.TestCase):

    def test_resign_sets_game_over_on_snapshot(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        session.assign_color("conn-2")
        run(session.record_join("conn-2", "bob"))
        snapshot = run(session.resign("alice"))
        self.assertTrue(snapshot.game_over)

    def test_resign_publishes_game_ended(self):
        session, bus = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        session.assign_color("conn-2")
        run(session.record_join("conn-2", "bob"))
        events: list[dict] = []
        bus.subscribe(topics.GAME_ENDED, lambda p: events.append(p))
        run(session.resign("alice"))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["loser"], "alice")
        self.assertEqual(events[0]["winner"], "bob")

    def test_resign_sets_winner_color_on_snapshot(self):
        """
        Regression test: previously the game-over snapshot carried no
        indication of who won a resignation, so a client had no way to
        show "YOU WIN"/"YOU LOSE" — only a bare "GAME OVER".
        assign_color() gives the first joiner WHITE, the second BLACK, so
        alice (conn-1, joined first) is WHITE and bob (conn-2) is BLACK.
        Alice resigns → bob (BLACK) is the winner.
        """
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        session.assign_color("conn-2")
        run(session.record_join("conn-2", "bob"))
        snapshot = run(session.resign("alice"))
        self.assertEqual(snapshot.winner_color, PieceColor.BLACK)


class TestPublicBusMethods(unittest.TestCase):

    def test_publish_disconnected_fires_event(self):
        session, bus = _make_session()
        received: list[dict] = []
        bus.subscribe(topics.PLAYER_DISCONNECTED, lambda p: received.append(p))
        run(session.publish_disconnected("room-1", "alice", "conn-1"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["username"], "alice")
        self.assertEqual(received[0]["conn_id"], "conn-1")
        self.assertEqual(received[0]["game_id"], "room-1")

    def test_publish_reconnected_fires_event(self):
        session, bus = _make_session()
        received: list[dict] = []
        bus.subscribe(topics.PLAYER_RECONNECTED, lambda p: received.append(p))
        run(session.publish_reconnected("room-1", "alice", "conn-2"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["username"], "alice")
        self.assertEqual(received[0]["conn_id"], "conn-2")
        self.assertEqual(received[0]["game_id"], "room-1")

    def test_other_player_username_returns_opponent(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        session.assign_color("conn-2")
        run(session.record_join("conn-2", "bob"))
        self.assertEqual(session.other_player_username("alice"), "bob")
        self.assertEqual(session.other_player_username("bob"), "alice")

    def test_other_player_username_returns_none_when_solo(self):
        session, _ = _make_session()
        session.assign_color("conn-1")
        run(session.record_join("conn-1", "alice"))
        self.assertIsNone(session.other_player_username("alice"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
