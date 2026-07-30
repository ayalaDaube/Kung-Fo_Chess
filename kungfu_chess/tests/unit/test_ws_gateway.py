"""
Tests for WsGateway.

Covers the live-connection tier: room lifecycle, spectators, moves,
matchmaking, disconnect/reconnect.  Auth is pre-seeded into the
ConnectionRegistry (as ApiGateway would do) — not tested here.
No monkeypatching.
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
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import (
    AuthConfig, MatchmakingConfig, RealtimeConfig, load_server_config as _load_cfg,
)
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    CMD_MOVE, CMD_CREATE_ROOM, CMD_JOIN_ROOM, CMD_CANCEL_ROOM,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ROOM_CANCELLED,
    MSG_ASSIGNED, MSG_ERROR, MSG_SNAPSHOT,
)
from kungfu_chess.server.network.ws_gateway import WsGateway
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

_RT_CONFIG = RealtimeConfig(
    tick_interval_ms=50,
    auto_resign_ms=_load_cfg().realtime.auto_resign_ms,
)
_RT_CONFIG_FAST_RESIGN = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=50)
_MM_CFG = MatchmakingConfig(
    elo_range=500, elo_widen_step=50, widen_interval_ms=20, timeout_ms=5000,
)
_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


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


def _msg(**kwargs) -> str:
    return json.dumps(kwargs)


def _make_gateway(config=_RT_CONFIG, mm_config=None) -> WsGateway:
    counter = [0]

    def _room_id_gen():
        counter[0] += 1
        return f"room-{counter[0]}"

    registry = ConnectionRegistry()
    return WsGateway(
        session_factory=lambda: GameSession(
            bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine,
        ),
        realtime_config=config,
        registry=registry,
        room_id_generator=_room_id_gen,
        matchmaking_config=mm_config,
    )


class TestWsGatewayRoomLifecycle(unittest.TestCase):

    def test_create_room_returns_room_id(self):
        gw = _make_gateway()
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_CREATE_ROOM)])
        run(gw.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ROOM_CREATED)
        self.assertIn("room_id", msg)

    def test_join_room_as_player_receives_assigned(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await gw.handle(ws)
            return ws

        ws = run(_go())
        types = [json.loads(m)["type"] for m in ws.sent]
        self.assertIn(MSG_ROOM_JOINED, types)
        self.assertIn(MSG_ASSIGNED, types)

    def test_first_player_white_second_black(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            ws1 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            ws2 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="bob")])
            await gw.handle(ws1)
            await gw.handle(ws2)
            return ws1, ws2

        ws1, ws2 = run(_go())
        color1 = next(json.loads(m)["color"] for m in ws1.sent
                      if json.loads(m).get("type") == MSG_ASSIGNED)
        color2 = next(json.loads(m)["color"] for m in ws2.sent
                      if json.loads(m).get("type") == MSG_ASSIGNED)
        self.assertEqual(color1, "w")
        self.assertEqual(color2, "b")

    def test_cancel_room_sends_cancelled(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_CANCEL_ROOM, room_id=rid)])
            await gw.handle(ws)
            return ws

        ws = run(_go())
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ROOM_CANCELLED)

    def test_cancel_nonexistent_room_sends_error(self):
        gw = _make_gateway()
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_CANCEL_ROOM, room_id="ghost")])
        run(gw.handle(ws))
        self.assertEqual(json.loads(ws.sent[0])["type"], MSG_ERROR)

    def test_join_nonexistent_room_sends_error(self):
        gw = _make_gateway()
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id="ghost")])
        run(gw.handle(ws))
        self.assertEqual(json.loads(ws.sent[0])["type"], MSG_ERROR)


class TestWsGatewaySpectators(unittest.TestCase):

    def test_third_connection_joins_as_spectator(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            for name in ("alice", "bob"):
                await gw.handle(FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username=name)]))
            ws3 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="carol")])
            await gw.handle(ws3)
            return ws3

        ws3 = run(_go())
        joined = next(json.loads(m) for m in ws3.sent
                      if json.loads(m).get("type") == MSG_ROOM_JOINED)
        self.assertEqual(joined["role"], "spectator")

    def test_spectator_move_rejected(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            for name in ("alice", "bob"):
                await gw.handle(FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username=name)]))
            ws3 = FakeWebSocket(messages=[
                _msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="carol"),
                _msg(cmd=CMD_MOVE, **{"from": {"row": 6, "col": 4}, "to": {"row": 4, "col": 4}}),
            ])
            await gw.handle(ws3)
            return ws3

        ws3 = run(_go())
        errors = [json.loads(m) for m in ws3.sent if json.loads(m).get("type") == MSG_ERROR]
        self.assertTrue(any("not your piece" in e["reason"] for e in errors))


class TestWsGatewayJoinSnapshot(unittest.TestCase):
    """Joiners must receive an immediate snapshot regardless of TickLoop activity."""

    def test_new_player_receives_snapshot_on_join(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await gw.handle(ws)
            return ws

        ws = run(_go())
        types = [json.loads(m)["type"] for m in ws.sent]
        self.assertIn(MSG_SNAPSHOT, types)

    def test_spectator_receives_snapshot_on_join(self):
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            for name in ("alice", "bob"):
                await gw.handle(FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username=name)]))
            ws3 = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="carol")])
            await gw.handle(ws3)
            return ws3

        ws3 = run(_go())
        types = [json.loads(m)["type"] for m in ws3.sent]
        self.assertIn(MSG_SNAPSHOT, types)

    def test_snapshot_arrives_after_join_messages(self):
        """Snapshot must come after MSG_ROOM_JOINED/MSG_ASSIGNED, not before."""
        gw = _make_gateway()

        async def _go():
            rid = await gw.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await gw.handle(ws)
            return ws

        ws = run(_go())
        types = [json.loads(m)["type"] for m in ws.sent]
        snapshot_idx = types.index(MSG_SNAPSHOT)
        joined_idx = types.index(MSG_ROOM_JOINED)
        self.assertGreater(snapshot_idx, joined_idx)




    def test_move_without_room_sends_error(self):
        gw = _make_gateway()
        ws = FakeWebSocket(messages=[
            _msg(cmd=CMD_MOVE, **{"from": {"row": 6, "col": 4}, "to": {"row": 4, "col": 4}}),
        ])
        run(gw.handle(ws))
        msg = json.loads(ws.sent[0])
        self.assertEqual(msg["type"], MSG_ERROR)
        self.assertIn("not in a room", msg["reason"])

    def test_move_in_room_a_does_not_broadcast_to_room_b(self):
        gw = _make_gateway()

        async def _go():
            rid_a = await gw.create_room()
            rid_b = await gw.create_room()
            ws_a = FakeWebSocket(messages=[
                _msg(cmd=CMD_JOIN_ROOM, room_id=rid_a, username="alice"),
                _msg(cmd=CMD_MOVE, **{"from": {"row": 6, "col": 4}, "to": {"row": 4, "col": 4}}),
            ])
            ws_b = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid_b, username="bob")])
            await gw.handle(ws_b)
            await gw.handle(ws_a)
            return ws_b

        ws_b = run(_go())
        snapshots = [json.loads(m) for m in ws_b.sent if json.loads(m).get("type") == MSG_SNAPSHOT]
        # ws_b receives exactly the join-time snapshot; room A's move adds none.
        self.assertEqual(len(snapshots), 1)


class TestWsGatewayAuthDispatch(unittest.TestCase):

    def test_auth_command_forwarded_to_dispatch(self):
        """Auth commands must be forwarded to the injected auth_dispatch callable."""
        from kungfu_chess.server.network.protocol import CMD_LOGIN
        dispatched = []

        async def _auth_dispatch(conn_id, command):
            dispatched.append((conn_id, command))

        registry = ConnectionRegistry()
        gw = WsGateway(
            session_factory=lambda: GameSession(
                bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine,
            ),
            realtime_config=_RT_CONFIG,
            registry=registry,
            auth_dispatch=_auth_dispatch,
        )
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_LOGIN, username="alice", password="secret")])
        run(gw.handle(ws))
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(dispatched[0][0], str(id(ws)))

    def test_auth_command_without_dispatch_sends_error(self):
        from kungfu_chess.server.network.protocol import CMD_LOGIN
        registry = ConnectionRegistry()
        gw = WsGateway(
            session_factory=lambda: GameSession(
                bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine,
            ),
            realtime_config=_RT_CONFIG,
            registry=registry,
            auth_dispatch=None,
        )
        ws = FakeWebSocket(messages=[_msg(cmd=CMD_LOGIN, username="alice", password="secret")])
        run(gw.handle(ws))
        self.assertEqual(json.loads(ws.sent[0])["type"], MSG_ERROR)


class TestWsGatewayAutoResign(unittest.TestCase):

    def test_room_removed_after_auto_resign(self):
        async def _go():
            gw = WsGateway(
                session_factory=lambda: GameSession(
                    bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine,
                ),
                realtime_config=_RT_CONFIG_FAST_RESIGN,
                registry=ConnectionRegistry(),
                room_id_generator=lambda: "resign-room",
            )
            rid = await gw.create_room()
            ws_alice = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            ws_bob = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="bob")])
            await gw.handle(ws_alice)
            await gw.handle(ws_bob)
            await gw._on_disconnect(str(id(ws_alice)))
            await asyncio.sleep(0.15)
            self.assertNotIn(rid, gw.room_ids())

        run(_go())


if __name__ == "__main__":
    unittest.main(verbosity=2)
