"""
Tests for ApiGateway.

Covers the stateless auth tier: login, register, error cases.
No rooms, no moves, no matchmaking — those belong in test_ws_gateway.py.
No monkeypatching.
"""
from __future__ import annotations
import asyncio
import json
import unittest

from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.config import AuthConfig
from kungfu_chess.server.network.api_gateway import ApiGateway
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    LoginCommand, RegisterCommand,
    MSG_LOGGED_IN, MSG_REGISTERED, MSG_ERROR,
)


def run(coro):
    return asyncio.run(coro)


_AUTH_CFG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, msg: str):
        self.sent.append(json.loads(msg))


def _make_gateway() -> tuple[ApiGateway, ConnectionRegistry, str, FakeWS, AuthService]:
    reg = ConnectionRegistry()
    ws = FakeWS()
    conn_id = "conn-1"
    reg.register(conn_id, ws)
    auth_svc = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)

    async def _send(cid, payload):
        w = reg.get_ws(cid)
        if w:
            await w.send(json.dumps(payload))

    gw = ApiGateway(auth_service=auth_svc, registry=reg, send=_send)
    return gw, reg, conn_id, ws, auth_svc


class TestApiGatewayRegister(unittest.TestCase):

    def test_register_sends_registered(self):
        gw, _, conn_id, ws, _ = _make_gateway()
        run(gw.handle_auth(conn_id, RegisterCommand(username="alice", password="secret")))
        self.assertEqual(ws.sent[0]["type"], MSG_REGISTERED)

    def test_register_includes_elo(self):
        gw, _, conn_id, ws, _ = _make_gateway()
        run(gw.handle_auth(conn_id, RegisterCommand(username="alice", password="secret")))
        self.assertIn("elo", ws.sent[0])

    def test_register_marks_connection_logged_in(self):
        gw, reg, conn_id, ws, _ = _make_gateway()
        run(gw.handle_auth(conn_id, RegisterCommand(username="alice", password="secret")))
        self.assertIsNotNone(reg.identity_of(conn_id))
        self.assertEqual(reg.identity_of(conn_id)[0], "alice")

    def test_duplicate_register_sends_error(self):
        gw, _, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, RegisterCommand(username="alice", password="other")))
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)

    def test_duplicate_register_does_not_mark_logged_in(self):
        gw, reg, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, RegisterCommand(username="alice", password="other")))
        self.assertIsNone(reg.identity_of(conn_id))


class TestApiGatewayLogin(unittest.TestCase):

    def test_login_success_sends_logged_in(self):
        gw, _, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, LoginCommand(username="alice", password="secret")))
        self.assertEqual(ws.sent[0]["type"], MSG_LOGGED_IN)

    def test_login_success_includes_elo(self):
        gw, _, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, LoginCommand(username="alice", password="secret")))
        self.assertIn("elo", ws.sent[0])

    def test_login_success_marks_logged_in(self):
        gw, reg, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, LoginCommand(username="alice", password="secret")))
        self.assertEqual(reg.identity_of(conn_id)[0], "alice")

    def test_wrong_password_sends_error(self):
        gw, _, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, LoginCommand(username="alice", password="wrong")))
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)

    def test_wrong_password_does_not_mark_logged_in(self):
        gw, reg, conn_id, ws, auth_svc = _make_gateway()
        run(auth_svc.register("alice", "secret"))
        run(gw.handle_auth(conn_id, LoginCommand(username="alice", password="wrong")))
        self.assertIsNone(reg.identity_of(conn_id))

    def test_unknown_user_sends_error(self):
        gw, _, conn_id, ws, _ = _make_gateway()
        run(gw.handle_auth(conn_id, LoginCommand(username="nobody", password="pw")))
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)


class TestApiGatewayNoAuth(unittest.TestCase):

    def test_handle_no_auth_sends_error(self):
        reg = ConnectionRegistry()
        ws = FakeWS()
        conn_id = "conn-1"
        reg.register(conn_id, ws)

        async def _send(cid, payload):
            await ws.send(json.dumps(payload))

        # ApiGateway requires auth_service — test the no-auth path via
        # the WsGateway/ConnectionRouter "auth not configured" branch instead,
        # which calls handle_no_auth indirectly.  Here we just verify the
        # send callable works correctly when called directly.
        async def _go():
            gw = ApiGateway.__new__(ApiGateway)
            await gw.handle_no_auth(conn_id, _send)

        run(_go())
        self.assertEqual(ws.sent[0]["type"], MSG_ERROR)
        self.assertIn("auth not configured", ws.sent[0]["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
