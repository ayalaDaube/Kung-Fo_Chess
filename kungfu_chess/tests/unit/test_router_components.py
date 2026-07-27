"""
Unit tests for the five classes extracted from ConnectionRouter.

No real sockets, no monkeypatching — injected fakes only.
"""
from __future__ import annotations
import asyncio
import unittest

from kungfu_chess.server.auth.auth_handler import AuthHandler
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.auth.elo_service import EloService
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import (
    AuthConfig, RealtimeConfig, MatchmakingConfig,
)
from kungfu_chess.server.matchmaking.matchmaking_coordinator import MatchmakingCoordinator
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    MSG_LOGGED_IN, MSG_REGISTERED, MSG_ERROR,
    MSG_ROOM_JOINED, MSG_ASSIGNED, MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
    MSG_OPPONENT_DISCONNECTED,
)
from kungfu_chess.server.session.disconnect_coordinator import DisconnectCoordinator
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.server.session.room_manager import RoomManager

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine


def run(coro):
    return asyncio.run(coro)


_AUTH_CFG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")
_RT_CFG = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=50)
_MM_CFG = MatchmakingConfig(elo_range=500, elo_widen_step=50, widen_interval_ms=20, timeout_ms=5000)
_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}

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


# ── shared fakes ──────────────────────────────────────────────────────────────

class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, msg: str):
        import json
        self.sent.append(json.loads(msg))


def _make_registry_with_ws() -> tuple[ConnectionRegistry, str, FakeWS]:
    reg = ConnectionRegistry()
    ws = FakeWS()
    conn_id = "conn-1"
    reg.register(conn_id, ws)
    return reg, conn_id, ws


def _make_auth_service() -> AuthService:
    return AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)


def _make_engine():
    board = BoardParser().parse(_MINIMAL_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_room_manager(registry: ConnectionRegistry) -> RoomManager:
    sent: list = []

    async def _send(conn_id, payload):
        ws = registry.get_ws(conn_id)
        if ws:
            await ws.send(__import__("json").dumps(payload))

    async def _send_to_others(room_id, exclude, payload):
        pass

    def _make_broadcast(room_id):
        async def _bc(msg): pass
        return _bc

    return RoomManager(
        session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
        realtime_config=_RT_CFG,
        registry=registry,
        room_id_generator=lambda: "test-room",
        send=_send,
        send_to_others=_send_to_others,
        make_broadcast=_make_broadcast,
    )


# ── 1. ConnectionRegistry ─────────────────────────────────────────────────────

class TestConnectionRegistry(unittest.TestCase):

    def test_register_and_get_ws(self):
        reg = ConnectionRegistry()
        ws = object()
        reg.register("c1", ws)
        self.assertIs(reg.get_ws("c1"), ws)

    def test_forget_removes_all(self):
        reg = ConnectionRegistry()
        reg.register("c1", object())
        reg.mark_logged_in("c1", "alice", 1200)
        reg.assign_room("c1", "room-1")
        reg.forget("c1")
        self.assertIsNone(reg.get_ws("c1"))
        self.assertIsNone(reg.identity_of("c1"))
        self.assertIsNone(reg.room_of("c1"))

    def test_mark_logged_in_and_identity_of(self):
        reg = ConnectionRegistry()
        reg.register("c1", object())
        reg.mark_logged_in("c1", "bob", 1300)
        self.assertEqual(reg.identity_of("c1"), ("bob", 1300))

    def test_assign_room_and_room_of(self):
        reg = ConnectionRegistry()
        reg.register("c1", object())
        reg.assign_room("c1", "r1")
        self.assertEqual(reg.room_of("c1"), "r1")

    def test_conns_in_room(self):
        reg = ConnectionRegistry()
        reg.register("c1", object())
        reg.register("c2", object())
        reg.assign_room("c1", "r1")
        reg.assign_room("c2", "r1")
        self.assertCountEqual(reg.conns_in_room("r1"), ["c1", "c2"])

    def test_remove_room_entries(self):
        reg = ConnectionRegistry()
        reg.register("c1", object())
        reg.assign_room("c1", "r1")
        reg.remove_room_entries("r1")
        self.assertIsNone(reg.room_of("c1"))


# ── 2. RoomManager ────────────────────────────────────────────────────────────

class TestRoomManager(unittest.TestCase):

    def _make(self):
        reg = ConnectionRegistry()
        ws = FakeWS()
        reg.register("c1", ws)
        rm = _make_room_manager(reg)
        return rm, reg, ws

    def test_create_room_appears_in_room_ids(self):
        rm, _, _ = self._make()
        run(rm.create_room("r1"))
        self.assertIn("r1", rm.room_ids())

    def test_cancel_room_removes_it(self):
        rm, _, _ = self._make()
        run(rm.create_room("r1"))
        rm.cancel_room("r1")
        self.assertNotIn("r1", rm.room_ids())

    def test_cancel_nonexistent_returns_false(self):
        rm, _, _ = self._make()
        self.assertFalse(rm.cancel_room("ghost"))

    def test_session_for_returns_game_session(self):
        rm, _, _ = self._make()
        run(rm.create_room("r1"))
        self.assertIsInstance(rm.session_for("r1"), GameSession)

    def test_join_room_assigns_player(self):
        rm, reg, ws = self._make()
        run(rm.create_room("r1"))
        run(rm.handle_join_room("c1", "r1", "alice"))
        types = [m["type"] for m in ws.sent]
        self.assertIn(MSG_ROOM_JOINED, types)
        self.assertIn(MSG_ASSIGNED, types)

    def test_join_nonexistent_room_sends_error(self):
        rm, reg, ws = self._make()
        run(rm.handle_join_room("c1", "ghost"))
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)

    def test_third_player_joins_as_spectator(self):
        reg = ConnectionRegistry()
        ws1, ws2, ws3 = FakeWS(), FakeWS(), FakeWS()
        for cid, ws in [("c1", ws1), ("c2", ws2), ("c3", ws3)]:
            reg.register(cid, ws)
        rm = _make_room_manager(reg)
        run(rm.create_room("r1"))
        run(rm.handle_join_room("c1", "r1", "alice"))
        run(rm.handle_join_room("c2", "r1", "bob"))
        run(rm.handle_join_room("c3", "r1", "carol"))
        joined = next(m for m in ws3.sent if m["type"] == MSG_ROOM_JOINED)
        self.assertEqual(joined["role"], "spectator")


# ── 3. DisconnectCoordinator ──────────────────────────────────────────────────

class TestDisconnectCoordinator(unittest.TestCase):

    def _make(self):
        reg = ConnectionRegistry()
        ws1, ws2 = FakeWS(), FakeWS()
        reg.register("c1", ws1)
        reg.register("c2", ws2)
        rm = _make_room_manager(reg)

        snapshots = []

        async def _broadcast_snapshot(room_id, snapshot):
            snapshots.append(snapshot)

        async def _send_to_others(room_id, exclude, payload):
            for cid in reg.conns_in_room(room_id):
                if cid != exclude:
                    ws = reg.get_ws(cid)
                    if ws:
                        await ws.send(__import__("json").dumps(payload))

        dc = DisconnectCoordinator(
            room_manager=rm,
            registry=reg,
            realtime_config=_RT_CFG,
            broadcast_snapshot=_broadcast_snapshot,
            send_to_others=_send_to_others,
        )
        return dc, rm, reg, ws1, ws2, snapshots

    def test_disconnect_notifies_opponent(self):
        async def _go():
            dc, rm, reg, ws1, ws2, _ = self._make()
            await rm.create_room("r1")
            await rm.handle_join_room("c1", "r1", "alice")
            await rm.handle_join_room("c2", "r1", "bob")
            await dc.on_disconnect("c1")
            return ws2

        ws2 = run(_go())
        types = [m["type"] for m in ws2.sent]
        self.assertIn(MSG_OPPONENT_DISCONNECTED, types)

    def test_auto_resign_fires_after_delay(self):
        async def _go():
            dc, rm, reg, ws1, ws2, snapshots = self._make()
            await rm.create_room("r1")
            await rm.handle_join_room("c1", "r1", "alice")
            await rm.handle_join_room("c2", "r1", "bob")
            await dc.on_disconnect("c1")
            await asyncio.sleep(0.15)
            return rm, snapshots

        rm, snapshots = run(_go())
        self.assertNotIn("r1", rm.room_ids())
        self.assertEqual(len(snapshots), 1)
        self.assertTrue(snapshots[0].game_over)

    def test_monitor_cancelled_on_reconnect(self):
        async def _go():
            dc, rm, reg, ws1, ws2, _ = self._make()
            await rm.create_room("r1")
            await rm.handle_join_room("c1", "r1", "alice")
            await rm.handle_join_room("c2", "r1", "bob")
            await dc.on_disconnect("c1")
            self.assertIn(("r1", "alice"), dc.monitors())
            # reconnect cancels monitor
            await rm.handle_join_room("c1", "r1", "alice", disconnect_monitors=dc.monitors())
            await asyncio.sleep(0.15)
            return rm

        rm = run(_go())
        # room still alive — resign never fired
        self.assertIn("r1", rm.room_ids())


# ── 4. MatchmakingCoordinator ─────────────────────────────────────────────────

class TestMatchmakingCoordinator(unittest.TestCase):

    def _make(self):
        reg = ConnectionRegistry()
        ws1, ws2 = FakeWS(), FakeWS()
        reg.register("c1", ws1)
        reg.register("c2", ws2)
        reg.mark_logged_in("c1", "alice", 1200)
        reg.mark_logged_in("c2", "bob", 1200)
        rm = _make_room_manager(reg)

        async def _send(conn_id, payload):
            ws = reg.get_ws(conn_id)
            if ws:
                await ws.send(__import__("json").dumps(payload))

        mm = MatchmakingCoordinator(
            config=_MM_CFG,
            room_manager=rm,
            registry=reg,
            send=_send,
            join_room=rm.handle_join_room,
            disconnect_monitors={},
        )
        return mm, reg, ws1, ws2

    def test_find_match_enqueues_player(self):
        mm, _, _, _ = self._make()
        run(mm.handle_find_match("c1"))
        self.assertEqual(mm.matchmaker.queue_size(), 1)

    def test_cancel_match_dequeues_player(self):
        mm, _, _, _ = self._make()
        run(mm.handle_find_match("c1"))
        run(mm.handle_cancel_match("c1"))
        self.assertEqual(mm.matchmaker.queue_size(), 0)

    def test_cancel_by_identity_removes_queued_player(self):
        mm, _, _, _ = self._make()
        run(mm.handle_find_match("c1"))
        mm.cancel_by_identity("c1")
        self.assertEqual(mm.matchmaker.queue_size(), 0)

    def test_find_match_not_logged_in_sends_error(self):
        reg = ConnectionRegistry()
        ws = FakeWS()
        reg.register("c1", ws)
        rm = _make_room_manager(reg)

        async def _send(conn_id, payload):
            await ws.send(__import__("json").dumps(payload))

        mm = MatchmakingCoordinator(
            config=_MM_CFG, room_manager=rm, registry=reg,
            send=_send, join_room=rm.handle_join_room, disconnect_monitors={},
        )
        run(mm.handle_find_match("c1"))
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)

    def test_match_found_sends_match_found_to_both(self):
        async def _go():
            mm, reg, ws1, ws2 = self._make()
            await mm.handle_find_match("c1")
            await mm.handle_find_match("c2")
            mm.loop.start()
            await asyncio.sleep(0.1)
            mm.loop.stop()
            return ws1, ws2

        ws1, ws2 = run(_go())
        self.assertTrue(any(m["type"] == MSG_MATCH_FOUND for m in ws1.sent))
        self.assertTrue(any(m["type"] == MSG_MATCH_FOUND for m in ws2.sent))


# ── 5. AuthHandler ────────────────────────────────────────────────────────────

class TestAuthHandler(unittest.TestCase):

    def _make(self):
        reg, conn_id, ws = _make_registry_with_ws()
        auth_svc = _make_auth_service()

        async def _send(cid, payload):
            w = reg.get_ws(cid)
            if w:
                await w.send(__import__("json").dumps(payload))

        handler = AuthHandler(auth_service=auth_svc, registry=reg, send=_send)
        return handler, reg, conn_id, ws, auth_svc

    def test_register_sends_registered(self):
        from kungfu_chess.server.network.protocol import RegisterCommand
        handler, _, conn_id, ws, _ = self._make()
        run(handler.handle(conn_id, RegisterCommand(username="alice", password="secret")))
        self.assertEqual(ws.sent[0]["type"], MSG_REGISTERED)

    def test_register_marks_logged_in(self):
        from kungfu_chess.server.network.protocol import RegisterCommand
        handler, reg, conn_id, ws, _ = self._make()
        run(handler.handle(conn_id, RegisterCommand(username="alice", password="secret")))
        self.assertIsNotNone(reg.identity_of(conn_id))
        self.assertEqual(reg.identity_of(conn_id)[0], "alice")

    def test_login_success_sends_logged_in(self):
        from kungfu_chess.server.network.protocol import LoginCommand, RegisterCommand
        handler, _, conn_id, ws, auth_svc = self._make()
        run(auth_svc.register("alice", "secret"))
        run(handler.handle(conn_id, LoginCommand(username="alice", password="secret")))
        self.assertEqual(ws.sent[0]["type"], MSG_LOGGED_IN)
        self.assertIn("elo", ws.sent[0])

    def test_login_wrong_password_sends_error(self):
        from kungfu_chess.server.network.protocol import LoginCommand
        handler, _, conn_id, ws, auth_svc = self._make()
        run(auth_svc.register("alice", "secret"))
        run(handler.handle(conn_id, LoginCommand(username="alice", password="wrong")))
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)

    def test_login_does_not_mark_logged_in_on_failure(self):
        from kungfu_chess.server.network.protocol import LoginCommand
        handler, reg, conn_id, ws, auth_svc = self._make()
        run(auth_svc.register("alice", "secret"))
        run(handler.handle(conn_id, LoginCommand(username="alice", password="wrong")))
        self.assertIsNone(reg.identity_of(conn_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
