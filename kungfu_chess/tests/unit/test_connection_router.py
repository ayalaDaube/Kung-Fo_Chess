"""
Tests for ConnectionRouter.
Uses fake WebSockets and injected session/room-id factories — no patching.
"""
from __future__ import annotations
import asyncio
import json
import unittest

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import AuthConfig, RealtimeConfig
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_MOVE, CMD_JOIN, CMD_CREATE_ROOM, CMD_JOIN_ROOM, CMD_CANCEL_ROOM,
    CMD_LOGIN, CMD_REGISTER,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ROOM_CANCELLED,
    MSG_ASSIGNED, MSG_JOINED, MSG_ERROR, MSG_LOGGED_IN, MSG_REGISTERED,
    MSG_SNAPSHOT,
)
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

_AUTH_CONFIG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")
_RT_CONFIG = RealtimeConfig(tick_interval_ms=50)


class FakeWebSocket:
    def __init__(self, messages=None):
        self._inbox = list(messages or [])
        self.sent = []
        self.closed = False

    async def send(self, msg): self.sent.append(msg)
    async def close(self): self.closed = True
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._inbox:
            raise StopAsyncIteration
        return self._inbox.pop(0)


def _make_engine():
    board = BoardParser().parse(_MINIMAL_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_router(auth=None) -> ConnectionRouter:
    counter = [0]

    def _room_id_gen():
        counter[0] += 1
        return f"room-{counter[0]}"

    def _session_factory():
        return GameSession(bus=EventBus(), engine_factory=_make_engine)

    return ConnectionRouter(
        session_factory=_session_factory,
        realtime_config=_RT_CONFIG,
        auth_service=auth,
        room_id_generator=_room_id_gen,
    )


def _make_router_with_auth() -> tuple[ConnectionRouter, AuthService]:
    auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CONFIG)
    return _make_router(auth=auth), auth


def _msg(**kwargs) -> str:
    return json.dumps(kwargs)


class TestRoomLifecycle(unittest.TestCase):

    def test_create_room_returns_room_id(self):
        router = _make_router()
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_CREATE_ROOM)])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ROOM_CREATED)
        self.assertIn("room_id", msg)

    def test_join_room_as_player_receives_assigned(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await router.handle(ws)
            return ws

        ws = run(_go())
        types = [json.loads(m)["type"] for m in ws.sent]
        self.assertIn(MSG_ROOM_JOINED, types)
        self.assertIn(MSG_ASSIGNED, types)

    def test_first_player_white_second_black(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            ws1 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            ws2 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="bob")])
            await router.handle(ws1)
            await router.handle(ws2)
            return ws1, ws2

        ws1, ws2 = run(_go())
        color1 = next(json.loads(m)["color"] for m in ws1.sent
                      if json.loads(m).get("type") == MSG_ASSIGNED)
        color2 = next(json.loads(m)["color"] for m in ws2.sent
                      if json.loads(m).get("type") == MSG_ASSIGNED)
        self.assertEqual(color1, "w")
        self.assertEqual(color2, "b")

    def test_cancel_room_sends_cancelled(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_CANCEL_ROOM, room_id=rid)])
            await router.handle(ws)
            return ws


        ws = run(_go())
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ROOM_CANCELLED)

    def test_cancel_nonexistent_room_sends_error(self):
        router = _make_router()
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_CANCEL_ROOM, room_id="ghost")])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ERROR)

    def test_join_nonexistent_room_sends_error(self):
        router = _make_router()
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id="ghost")])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ERROR)


class TestSpectatorSupport(unittest.TestCase):

    def test_third_connection_joins_as_spectator(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            for name in ("alice", "bob"):
                ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username=name)])
                await router.handle(ws)
            ws3 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="carol")])
            await router.handle(ws3)
            return ws3

        ws3 = run(_go())
        joined = next(json.loads(m) for m in ws3.sent
                      if json.loads(m).get("type") == MSG_ROOM_JOINED)
        self.assertEqual(joined["role"], "spectator")

    def test_spectator_does_not_receive_assigned(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            for name in ("alice", "bob"):
                await router.handle(FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username=name)]))
            ws3 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="carol")])
            await router.handle(ws3)
            return ws3

        ws3 = run(_go())
        types = [json.loads(m)["type"] for m in ws3.sent]
        self.assertNotIn(MSG_ASSIGNED, types)

    def test_spectator_move_rejected(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            for name in ("alice", "bob"):
                await router.handle(FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username=name)]))
            ws3 = FakeWebSocket(messages=[
                _msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="carol"),
                _msg(cmd=CMD_MOVE, **{"from": {"row": 6, "col": 4}, "to": {"row": 4, "col": 4}}),
            ])
            await router.handle(ws3)
            return ws3

        ws3 = run(_go())
        errors = [json.loads(m) for m in ws3.sent if json.loads(m).get("type") == MSG_ERROR]
        self.assertTrue(any("not your piece" in e["reason"] for e in errors))


class TestRoomIsolation(unittest.TestCase):

    def test_move_in_room_a_does_not_broadcast_to_room_b(self):
        router = _make_router()

        async def _go():
            rid_a = await router.create_room()
            rid_b = await router.create_room()
            ws_a = FakeWebSocket(messages=[
                _msg(cmd=CMD_JOIN_ROOM, room_id=rid_a, username="alice"),
                _msg(cmd=CMD_MOVE, **{"from": {"row": 6, "col": 4}, "to": {"row": 4, "col": 4}}),
            ])
            ws_b = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid_b, username="bob")])
            await router.handle(ws_b)
            await router.handle(ws_a)
            return ws_b

        ws_b = run(_go())
        snapshots_b = [json.loads(m) for m in ws_b.sent
                       if json.loads(m).get("type") == MSG_SNAPSHOT]
        self.assertEqual(len(snapshots_b), 0)


class TestGameCommandsWithoutRoom(unittest.TestCase):

    def test_move_without_room_sends_error(self):
        router = _make_router()
        ws = FakeWebSocket(messages=[
            _msg(cmd=CMD_MOVE, **{"from": {"row": 6, "col": 4}, "to": {"row": 4, "col": 4}}),
        ])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ERROR)
        self.assertIn("not in a room", msg["reason"])


class TestAuthRouting(unittest.TestCase):

    def test_register_sends_registered(self):
        router, _ = _make_router_with_auth()
        ws = FakeWebSocket(messages=[
            _msg(cmd=CMD_REGISTER, username="alice", password="secret"),
        ])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_REGISTERED)

    def test_login_sends_logged_in(self):
        router, auth = _make_router_with_auth()
        run(auth.register("alice", "secret"))
        ws = FakeWebSocket(messages=[
            _msg(cmd=CMD_LOGIN, username="alice", password="secret"),
        ])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_LOGGED_IN)
        self.assertIn("elo", msg)

    def test_wrong_password_sends_error(self):
        router, auth = _make_router_with_auth()
        run(auth.register("alice", "secret"))
        ws = FakeWebSocket(messages=[
            _msg(cmd=CMD_LOGIN, username="alice", password="wrong"),
        ])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ERROR)

    def test_auth_not_configured_sends_error(self):
        router = _make_router(auth=None)
        ws = FakeWebSocket(messages=[
            _msg(cmd=CMD_LOGIN, username="alice", password="secret"),
        ])
        run(router.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ERROR)


class TestJoinCommandInRoom(unittest.TestCase):

    def test_join_command_sends_joined_ack(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            ws = FakeWebSocket(messages=[
                _msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice"),
                _msg(cmd=CMD_JOIN, username="alice"),
            ])
            await router.handle(ws)
            return ws

        ws = run(_go())
        types = [json.loads(m)["type"] for m in ws.sent]
        self.assertIn(MSG_JOINED, types)


class TestReconnect(unittest.TestCase):
    """
    A player who disconnects and reconnects with the same username must
    get their original color back, not be demoted to spectator.

    This is the exact scenario that shipped broken twice: the old
    PlayerRecord kept players_full() == True, so the reconnecting
    connection was routed to add_spectator() before identity was known.
    """

    def test_reconnect_restores_original_color(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()

            # alice joins first (WHITE), bob joins second (BLACK)
            ws_alice = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            ws_bob   = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="bob")])
            await router.handle(ws_alice)
            await router.handle(ws_bob)

            # alice's socket closes — router removes her connection
            router._connections.pop(str(id(ws_alice)), None)
            router._conn_to_room.pop(str(id(ws_alice)), None)

            # alice reconnects with a new socket but the same username
            ws_alice2 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await router.handle(ws_alice2)
            return ws_alice2

        ws_alice2 = run(_go())
        msgs = [json.loads(m) for m in ws_alice2.sent]
        joined = next(m for m in msgs if m["type"] == MSG_ROOM_JOINED)
        assigned = next(m for m in msgs if m["type"] == MSG_ASSIGNED)
        self.assertEqual(joined["role"], "player")
        self.assertEqual(assigned["color"], "w")

    def test_reconnect_is_not_marked_as_spectator(self):
        router = _make_router()

        async def _go():
            rid = await router.create_room()
            ws_alice = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            ws_bob   = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="bob")])
            await router.handle(ws_alice)
            await router.handle(ws_bob)

            router._connections.pop(str(id(ws_alice)), None)
            router._conn_to_room.pop(str(id(ws_alice)), None)

            ws_alice2 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await router.handle(ws_alice2)

            session = router.session_for(rid)
            return session, str(id(ws_alice2))

        session, conn_id = run(_go())
        self.assertFalse(session.is_spectator(conn_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
