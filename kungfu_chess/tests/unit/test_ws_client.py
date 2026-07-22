"""
End-to-end tests for client/ws_client.connect_and_join.
Real ConnectionRouter + real websockets — no mocking, no patching.
Mirrors the style of test_handshake_e2e.py.
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
from kungfu_chess.server.config import RealtimeConfig, load_server_config as _load_cfg
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18770   # distinct from test_handshake_e2e ports

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


class TestConnectAndJoin(unittest.TestCase):

    def test_create_room_returns_non_empty_room_id(self):
        """Passing room_id=None causes a room to be created; returned id is non-empty."""
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT):
                ws, room_id, role, color = await connect_and_join(_HOST, _PORT, "alice")
                await ws.close()
                return room_id, role, color

        room_id, role, color = asyncio.run(_run())
        self.assertTrue(len(room_id) > 0)
        self.assertEqual(role, "player")
        self.assertIn(color, ("w", "b"))

    def test_join_explicit_room_id_reaches_room_joined(self):
        """Passing an explicit room_id skips create_room and joins directly."""
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 1):
                # creator opens the room
                ws1, room_id, _, _ = await connect_and_join(_HOST, _PORT + 1, "alice")
                # second player joins by explicit id
                ws2, returned_id, role, color = await connect_and_join(
                    _HOST, _PORT + 1, "bob", room_id=room_id
                )
                await ws1.close()
                await ws2.close()
                return room_id, returned_id, role, color

        room_id, returned_id, role, color = asyncio.run(_run())
        self.assertEqual(returned_id, room_id)
        self.assertEqual(role, "player")
        self.assertEqual(color, "b")   # second player gets black

    def test_third_joiner_gets_spectator_role_and_no_color(self):
        """A third connection to a full room gets role='spectator' and color=None."""
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 2):
                ws1, room_id, _, _ = await connect_and_join(_HOST, _PORT + 2, "alice")
                ws2, _, _, _       = await connect_and_join(_HOST, _PORT + 2, "bob",   room_id=room_id)
                ws3, _, role, color = await connect_and_join(_HOST, _PORT + 2, "carol", room_id=room_id)
                await ws1.close()
                await ws2.close()
                await ws3.close()
                return role, color

        role, color = asyncio.run(_run())
        self.assertEqual(role, "spectator")
        self.assertIsNone(color)


if __name__ == "__main__":
    unittest.main(verbosity=2)
