"""
Tests for WsServer auth routing (login/register commands).
Uses InMemoryUserRepository + real AuthService injected via constructor.
No monkeypatching.
"""
from __future__ import annotations
import asyncio
import json
import unittest

from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import AuthConfig
from kungfu_chess.server.network.protocol import (
    CMD_LOGIN, CMD_REGISTER, MSG_LOGGED_IN, MSG_REGISTERED, MSG_ERROR,
)
from kungfu_chess.server.network.ws_server import WsServer
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine


def run(coro):
    return asyncio.run(coro)


_AUTH_CONFIG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")

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


def _make_server_with_auth() -> WsServer:
    bus = EventBus()
    session = GameSession(bus=bus, engine_factory=_make_engine)
    auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CONFIG)
    return WsServer(session=session, bus=bus, auth_service=auth)


def _register_msg(username, password) -> str:
    return json.dumps({"cmd": CMD_REGISTER, "username": username, "password": password})


def _login_msg(username, password) -> str:
    return json.dumps({"cmd": CMD_LOGIN, "username": username, "password": password})


class TestRegisterViaWs(unittest.TestCase):

    def test_successful_register_sends_registered(self):
        server = _make_server_with_auth()
        ws = FakeWebSocket(messages=[_register_msg("alice", "secret")])
        run(server.handle(ws))
        ack = json.loads(ws.sent[1])   # sent[0]=assigned
        self.assertEqual(ack["type"], MSG_REGISTERED)
        self.assertEqual(ack["username"], "alice")

    def test_duplicate_register_sends_error(self):
        server = _make_server_with_auth()
        ws1 = FakeWebSocket(messages=[_register_msg("alice", "secret")])
        ws2 = FakeWebSocket(messages=[_register_msg("alice", "other")])
        run(server.handle(ws1))
        run(server.handle(ws2))
        error = json.loads(ws2.sent[1])
        self.assertEqual(error["type"], MSG_ERROR)

    def test_invalid_register_sends_error(self):
        server = _make_server_with_auth()
        ws = FakeWebSocket(messages=[_register_msg("", "secret")])
        run(server.handle(ws))
        error = json.loads(ws.sent[1])
        self.assertEqual(error["type"], MSG_ERROR)


class TestLoginViaWs(unittest.TestCase):

    def _register_user(self, server, username, password):
        ws = FakeWebSocket(messages=[_register_msg(username, password)])
        run(server.handle(ws))

    def test_successful_login_sends_logged_in(self):
        server = _make_server_with_auth()
        self._register_user(server, "alice", "secret")
        ws = FakeWebSocket(messages=[_login_msg("alice", "secret")])
        run(server.handle(ws))
        ack = json.loads(ws.sent[1])
        self.assertEqual(ack["type"], MSG_LOGGED_IN)
        self.assertEqual(ack["username"], "alice")
        self.assertIn("elo", ack)

    def test_wrong_password_sends_error(self):
        server = _make_server_with_auth()
        self._register_user(server, "alice", "secret")
        ws = FakeWebSocket(messages=[_login_msg("alice", "wrong")])
        run(server.handle(ws))
        error = json.loads(ws.sent[1])
        self.assertEqual(error["type"], MSG_ERROR)

    def test_unknown_user_sends_error(self):
        server = _make_server_with_auth()
        ws = FakeWebSocket(messages=[_login_msg("nobody", "secret")])
        run(server.handle(ws))
        error = json.loads(ws.sent[1])
        self.assertEqual(error["type"], MSG_ERROR)


class TestAuthNotConfigured(unittest.TestCase):

    def test_login_without_auth_service_sends_error(self):
        bus = EventBus()
        session = GameSession(bus=bus, engine_factory=_make_engine)
        server = WsServer(session=session, bus=bus, auth_service=None)
        ws = FakeWebSocket(messages=[_login_msg("alice", "secret")])
        run(server.handle(ws))
        error = json.loads(ws.sent[1])
        self.assertEqual(error["type"], MSG_ERROR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
