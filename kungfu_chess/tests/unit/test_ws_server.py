"""
Tests for WsServer using hand-written fake WebSocket connections.
No unittest.mock.patch, no monkeypatching.
"""
from __future__ import annotations
import asyncio
import json
import unittest

from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.network.protocol import CMD_MOVE, CMD_JUMP
from kungfu_chess.server.network.ws_server import WsServer
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine


def run(coro):
    return asyncio.run(coro)


# ── fake WebSocket ────────────────────────────────────────────────────────────

class FakeWebSocket:
    """
    Hand-written stand-in for websockets.ServerConnection.
    Supports send(), close(), async iteration over a pre-loaded message queue.
    """

    def __init__(self, messages: list[str] | None = None) -> None:
        self._inbox = list(messages or [])
        self.sent: list[str] = []
        self.closed = False

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if not self._inbox:
            raise StopAsyncIteration
        return self._inbox.pop(0)


# ── helpers ───────────────────────────────────────────────────────────────────

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


def _make_server() -> WsServer:
    bus = EventBus()
    session = GameSession(bus=bus, engine_factory=_make_engine)
    return WsServer(session=session, bus=bus)


def _move_msg(fr, fc, tr, tc) -> str:
    return json.dumps({"cmd": CMD_MOVE,
                       "from": {"row": fr, "col": fc},
                       "to":   {"row": tr, "col": tc}})


# ── tests ─────────────────────────────────────────────────────────────────────

class TestColorAssignmentViaWs(unittest.TestCase):

    def test_first_client_receives_white(self):
        server = _make_server()
        ws = FakeWebSocket()
        run(server.handle(ws))
        assigned = json.loads(ws.sent[0])
        self.assertEqual(assigned["type"], "assigned")
        self.assertEqual(assigned["color"], "w")

    def test_second_client_receives_black(self):
        server = _make_server()
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        run(server.handle(ws1))
        run(server.handle(ws2))
        assigned = json.loads(ws2.sent[0])
        self.assertEqual(assigned["color"], "b")


class TestThirdConnectionRejected(unittest.TestCase):

    def test_third_connection_receives_error_and_is_closed(self):
        server = _make_server()
        run(server.handle(FakeWebSocket()))
        run(server.handle(FakeWebSocket()))
        ws3 = FakeWebSocket()
        run(server.handle(ws3))

        self.assertTrue(ws3.closed)
        msg = json.loads(ws3.sent[0])
        self.assertEqual(msg["type"], "error")
        self.assertIn("2", msg["reason"])  # mentions the player limit


class TestProtocolErrorRelayed(unittest.TestCase):

    def test_malformed_message_sends_error_to_sender(self):
        server = _make_server()
        ws = FakeWebSocket(messages=["not json"])
        run(server.handle(ws))
        # sent[0] = assigned, sent[1] = error
        error_msg = json.loads(ws.sent[1])
        self.assertEqual(error_msg["type"], "error")

    def test_unknown_command_sends_error(self):
        server = _make_server()
        ws = FakeWebSocket(messages=[json.dumps({"cmd": "teleport"})])
        run(server.handle(ws))
        error_msg = json.loads(ws.sent[1])
        self.assertEqual(error_msg["type"], "error")


class TestValidMoveRelayed(unittest.TestCase):

    def test_valid_move_triggers_snapshot_to_sender(self):
        server = _make_server()
        ws1 = FakeWebSocket(messages=[_move_msg(6, 4, 4, 4)])
        run(server.handle(FakeWebSocket()))  # ws2 connects first
        run(server.handle(ws1))              # ws1 connects and sends move

        # ws1: sent[0]=assigned, sent[1]=snapshot
        self.assertGreaterEqual(len(ws1.sent), 2)
        snapshot = json.loads(ws1.sent[1])
        self.assertEqual(snapshot["type"], "snapshot")


if __name__ == "__main__":
    unittest.main(verbosity=2)
