"""
End-to-end handshake test: real websockets server + real client in one process.
Verifies that ws_server and ws_client agree on the exact wire message sequence
without either side being faked.
No unittest.mock.patch.
"""
from __future__ import annotations
import asyncio
import unittest

import websockets

from kungfu_chess.client.ws_client import connect_and_join
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.network.protocol import MSG_ASSIGNED, MSG_JOINED
from kungfu_chess.server.network.ws_server import WsServer
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18765  # distinct port so it never clashes with a running dev server

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


def _make_server() -> WsServer:
    bus = EventBus()
    board = BoardParser().parse(_MINIMAL_BOARD)
    engine = GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())
    session = GameSession(bus=bus, engine_factory=lambda: engine)
    return WsServer(session=session, bus=bus)


class TestJoinHandshakeEndToEnd(unittest.TestCase):

    def test_full_handshake_sequence(self):
        """
        Server sends MSG_ASSIGNED on connect.
        Client sends join command.
        Server replies MSG_JOINED.
        connect_and_join returns without raising.
        """
        async def _run():
            server = _make_server()
            async with websockets.serve(server.handle, _HOST, _PORT):
                ws = await connect_and_join(_HOST, _PORT, "alice")
                await ws.close()

        asyncio.run(_run())

    def test_joined_ack_contains_username(self):
        """The MSG_JOINED ack carries back the username the client sent."""
        import json

        async def _run():
            server = _make_server()
            async with websockets.serve(server.handle, _HOST + "", _PORT + 1):
                uri = f"ws://{_HOST}:{_PORT + 1}"
                ws = await websockets.connect(uri)
                assigned = json.loads(await ws.recv())
                self.assertEqual(assigned["type"], MSG_ASSIGNED)

                await ws.send(json.dumps({"cmd": "join", "username": "bob"}))
                ack = json.loads(await ws.recv())
                self.assertEqual(ack["type"], MSG_JOINED)
                self.assertEqual(ack["username"], "bob")
                await ws.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
