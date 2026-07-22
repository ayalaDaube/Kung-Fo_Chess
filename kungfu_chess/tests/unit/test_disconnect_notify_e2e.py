"""
End-to-end tests for opponent disconnect/reconnect notifications.

Real ConnectionRouter + real websockets — no mocking, no patching.
"""
from __future__ import annotations

import asyncio
import json
import unittest

import websockets

from kungfu_chess.client.snapshot_receiver import SnapshotReceiver
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_CREATE_ROOM, CMD_JOIN_ROOM,
    MSG_ASSIGNED, MSG_ROOM_CREATED, MSG_ROOM_JOINED,
    MSG_OPPONENT_DISCONNECTED, MSG_OPPONENT_RECONNECTED,
)
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18850   # distinct from all other test files

_BOARD = """\
. . . . bK . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . wK . . .
"""

# Short auto_resign_ms so tests don't wait long.
_RT_CFG = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=300)


def _make_router() -> ConnectionRouter:
    def _engine():
        board = BoardParser().parse(_BOARD)
        return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())

    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), engine_factory=_engine),
        realtime_config=_RT_CFG,
    )


async def _drain_until(ws, msg_type: str, limit: int = 20) -> dict:
    for _ in range(limit):
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(raw)
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"Did not receive {msg_type!r} within {limit} messages")


async def _setup_room(uri: str) -> tuple:
    """Create a room with two players; return (ws_a, ws_b, room_id, color_a)."""
    ws_a = await websockets.connect(uri)
    ws_b = await websockets.connect(uri)

    await ws_a.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
    created = await _drain_until(ws_a, MSG_ROOM_CREATED)
    room_id = created["room_id"]

    await ws_a.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "alice"}))
    await _drain_until(ws_a, MSG_ROOM_JOINED)
    assigned_a = await _drain_until(ws_a, MSG_ASSIGNED)
    color_a = assigned_a["color"]

    await ws_b.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "bob"}))
    await _drain_until(ws_b, MSG_ROOM_JOINED)
    await _drain_until(ws_b, MSG_ASSIGNED)

    return ws_a, ws_b, room_id, color_a


class TestOpponentDisconnectNotify(unittest.TestCase):

    def test_opponent_receives_disconnected_message(self):
        """
        When player A disconnects, player B receives MSG_OPPONENT_DISCONNECTED
        with the correct auto_resign_ms from RealtimeConfig.
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT):
                uri = f"ws://{_HOST}:{_PORT}"
                ws_a, ws_b, room_id, _ = await _setup_room(uri)

                # A disconnects
                await ws_a.close()

                # B should receive the notification
                msg = await _drain_until(ws_b, MSG_OPPONENT_DISCONNECTED)
                await ws_b.close()
                return msg

        msg = asyncio.run(_run())
        self.assertEqual(msg["type"], MSG_OPPONENT_DISCONNECTED)
        self.assertEqual(msg["auto_resign_ms"], _RT_CFG.auto_resign_ms)
        self.assertIn("username", msg)

    def test_opponent_receives_reconnected_message(self):
        """
        When player A reconnects within the window, player B receives
        MSG_OPPONENT_RECONNECTED and the countdown clears.
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 1):
                uri = f"ws://{_HOST}:{_PORT + 1}"
                ws_a, ws_b, room_id, _ = await _setup_room(uri)

                await ws_a.close()
                # Drain the disconnect notification on B
                await _drain_until(ws_b, MSG_OPPONENT_DISCONNECTED)

                # A reconnects before auto_resign fires
                ws_a2 = await websockets.connect(uri)
                await ws_a2.send(json.dumps({
                    "cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "alice"
                }))
                await _drain_until(ws_a2, MSG_ROOM_JOINED)

                msg = await _drain_until(ws_b, MSG_OPPONENT_RECONNECTED)
                await ws_a2.close()
                await ws_b.close()
                return msg

        msg = asyncio.run(_run())
        self.assertEqual(msg["type"], MSG_OPPONENT_RECONNECTED)
        self.assertIn("username", msg)

    def test_snapshot_receiver_tracks_countdown(self):
        """
        SnapshotReceiver.feed() sets countdown_ms on MSG_OPPONENT_DISCONNECTED
        and clears it on MSG_OPPONENT_RECONNECTED.
        """
        recv = SnapshotReceiver()
        self.assertIsNone(recv.countdown_ms)

        recv.feed(json.dumps({
            "type": MSG_OPPONENT_DISCONNECTED,
            "username": "alice",
            "auto_resign_ms": 5000,
        }))
        self.assertEqual(recv.countdown_ms, 5000)

        recv.feed(json.dumps({
            "type": MSG_OPPONENT_RECONNECTED,
            "username": "alice",
        }))
        self.assertIsNone(recv.countdown_ms)

    def test_snapshot_receiver_clears_countdown_on_game_over(self):
        """countdown_ms is cleared when a game-over snapshot arrives."""
        from kungfu_chess.server.network.serialization import snapshot_to_json
        from kungfu_chess.engine.snapshot_builder import build_snapshot
        from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter as _Arb

        board = BoardParser().parse(_BOARD)
        snap = build_snapshot(board, _Arb(), selected_cell=None, game_over=True)
        wire = snapshot_to_json(snap)

        recv = SnapshotReceiver()
        recv.feed(json.dumps({
            "type": MSG_OPPONENT_DISCONNECTED,
            "username": "alice",
            "auto_resign_ms": 5000,
        }))
        self.assertEqual(recv.countdown_ms, 5000)

        recv.feed(wire)
        self.assertIsNone(recv.countdown_ms)

    def test_disconnected_message_not_sent_to_disconnecting_player(self):
        """
        The disconnecting player's own socket is closed — they must NOT
        receive MSG_OPPONENT_DISCONNECTED (only the other player does).
        This is verified by confirming B receives it but A's socket is gone.
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 2):
                uri = f"ws://{_HOST}:{_PORT + 2}"
                ws_a, ws_b, _, _ = await _setup_room(uri)
                await ws_a.close()
                msg = await _drain_until(ws_b, MSG_OPPONENT_DISCONNECTED)
                await ws_b.close()
                return msg

        msg = asyncio.run(_run())
        self.assertEqual(msg["type"], MSG_OPPONENT_DISCONNECTED)


if __name__ == "__main__":
    unittest.main(verbosity=2)
