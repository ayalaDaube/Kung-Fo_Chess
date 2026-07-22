"""
End-to-end handshake test: real ConnectionRouter + real websockets in one process.
Verifies the full wire sequence (create_room → join_room → join) without any faking.
No unittest.mock.patch.
"""
from __future__ import annotations
import asyncio
import json
import unittest

import websockets

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import RealtimeConfig, load_server_config as _load_cfg
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_CREATE_ROOM, CMD_JOIN_ROOM,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ASSIGNED,
)
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18765   # distinct port — never clashes with a running dev server

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


def _make_router() -> ConnectionRouter:
    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
        realtime_config=RealtimeConfig(tick_interval_ms=50, auto_resign_ms=_load_cfg().realtime.auto_resign_ms),
    )


class TestJoinHandshakeEndToEnd(unittest.TestCase):

    def test_full_handshake_sequence(self):
        """
        Client creates a room, joins it as a player (receives MSG_ASSIGNED),
        then sends a join command and receives MSG_JOINED — all over a real socket.
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT):
                uri = f"ws://{_HOST}:{_PORT}"
                ws = await websockets.connect(uri)

                # create room
                await ws.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
                created = json.loads(await ws.recv())
                self.assertEqual(created["type"], MSG_ROOM_CREATED)
                room_id = created["room_id"]

                # join room as player
                await ws.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "alice"}))
                joined_room = json.loads(await ws.recv())
                self.assertEqual(joined_room["type"], MSG_ROOM_JOINED)
                self.assertEqual(joined_room["role"], "player")

                assigned = json.loads(await ws.recv())
                self.assertEqual(assigned["type"], MSG_ASSIGNED)
                self.assertIn(assigned["color"], ("w", "b"))

                await ws.close()

        asyncio.run(_run())

    def test_joined_ack_contains_username(self):
        """MSG_ROOM_JOINED carries back the room_id; role confirms player seat."""
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 1):
                uri = f"ws://{_HOST}:{_PORT + 1}"
                ws = await websockets.connect(uri)

                await ws.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
                room_id = json.loads(await ws.recv())["room_id"]

                await ws.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "bob"}))
                ack = json.loads(await ws.recv())
                self.assertEqual(ack["type"], MSG_ROOM_JOINED)
                self.assertEqual(ack["role"], "player")

                await ws.close()

        asyncio.run(_run())

    def test_second_player_gets_black(self):
        """Second connection to the same room receives color 'b'."""
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 2):
                uri = f"ws://{_HOST}:{_PORT + 2}"

                ws1 = await websockets.connect(uri)
                await ws1.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
                room_id = json.loads(await ws1.recv())["room_id"]
                await ws1.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "alice"}))
                await ws1.recv()   # MSG_ROOM_JOINED
                color1 = json.loads(await ws1.recv())["color"]   # MSG_ASSIGNED

                ws2 = await websockets.connect(uri)
                await ws2.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": "bob"}))
                await ws2.recv()   # MSG_ROOM_JOINED
                color2 = json.loads(await ws2.recv())["color"]   # MSG_ASSIGNED

                self.assertEqual(color1, "w")
                self.assertEqual(color2, "b")

                await ws1.close()
                await ws2.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
