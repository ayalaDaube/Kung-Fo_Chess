"""
Tests for server-side ActivityLogger and its wiring into ConnectionRouter.

No mock.patch anywhere — uses real objects, real temp files, real routers.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import AuthConfig, RealtimeConfig, LoggingConfig, load_server_config
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_CREATE_ROOM, CMD_JOIN_ROOM, CMD_MOVE,
    CMD_LOGIN, CMD_REGISTER,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ASSIGNED,
    MSG_LOGGED_IN, MSG_REGISTERED, MSG_ERROR,
)
from kungfu_chess.server.session.game_session import GameSession


def run(coro):
    return asyncio.run(coro)


_BOARD = """\
. . . . bK . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . wP . . .
. . . . wK . . .
"""

_RT_CFG = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=5000)
_AUTH_CFG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")
_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


class FakeWebSocket:
    def __init__(self, messages=None):
        self._inbox = list(messages or [])
        self.sent = []

    async def send(self, msg): self.sent.append(msg)
    def __aiter__(self): return self
    async def __anext__(self):
        if not self._inbox:
            raise StopAsyncIteration
        return self._inbox.pop(0)


def _msg(**kwargs) -> str:
    return json.dumps(kwargs)


def _make_engine():
    board = BoardParser().parse(_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_router(log_path: str, auth=None) -> ConnectionRouter:
    counter = [0]

    def _room_id_gen():
        counter[0] += 1
        return f"room-{counter[0]}"

    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
        realtime_config=_RT_CFG,
        auth_service=auth,
        room_id_generator=_room_id_gen,
        activity_logger=ActivityLogger(log_path),
    )


def _read_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestActivityLoggerUnit(unittest.TestCase):

    def test_writes_json_line(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            al = ActivityLogger(path)
            run(al.log("test_event", {"key": "value"}, game_id="room-1"))
            lines = _read_lines(path)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["type"], "test_event")
            self.assertEqual(lines[0]["game_id"], "room-1")
            self.assertEqual(lines[0]["payload"]["key"], "value")
            self.assertIn("ts", lines[0])
        finally:
            os.unlink(path)

    def test_redacts_password_from_payload(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            al = ActivityLogger(path)
            run(al.log("auth_login", {"username": "alice", "password": "s3cr3t"}))
            lines = _read_lines(path)
            self.assertEqual(len(lines), 1)
            payload = lines[0]["payload"]
            self.assertNotIn("password", payload)
            self.assertEqual(payload["username"], "alice")
        finally:
            os.unlink(path)

    def test_no_password_in_file_at_all(self):
        """Critical: the raw password string must not appear anywhere in the log file."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            al = ActivityLogger(path)
            run(al.log("auth_login", {"username": "bob", "password": "my_secret_pw"}))
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("my_secret_pw", content)
        finally:
            os.unlink(path)

    def test_multiple_lines_appended(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            al = ActivityLogger(path)
            run(al.log("event_a"))
            run(al.log("event_b"))
            lines = _read_lines(path)
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["type"], "event_a")
            self.assertEqual(lines[1]["type"], "event_b")
        finally:
            os.unlink(path)

    def test_no_game_id_omitted_from_record(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            al = ActivityLogger(path)
            run(al.log("some_event"))
            lines = _read_lines(path)
            self.assertNotIn("game_id", lines[0])
        finally:
            os.unlink(path)


class TestLoggingConfig(unittest.TestCase):

    def test_load_server_config_has_logging(self):
        cfg = load_server_config()
        self.assertIsInstance(cfg.logging.log_path, str)
        self.assertTrue(len(cfg.logging.log_path) > 0)

    def test_logging_config_default_path(self):
        cfg = load_server_config()
        self.assertEqual(cfg.logging.log_path, "server_activity.log")


class TestActivityLoggerWiredInRouter(unittest.TestCase):

    def test_command_received_logged(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            router = _make_router(path)

            async def _go():
                rid = await router.create_room()
                ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
                await router.handle(ws)

            run(_go())
            lines = _read_lines(path)
            types = [l["type"] for l in lines]
            self.assertIn("command_received", types)
        finally:
            os.unlink(path)

    def test_player_joined_event_logged(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            router = _make_router(path)

            async def _go():
                rid = await router.create_room()
                ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
                await router.handle(ws)

            run(_go())
            lines = _read_lines(path)
            types = [l["type"] for l in lines]
            self.assertIn("player.joined", types)
        finally:
            os.unlink(path)

    def test_auth_login_success_logged(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)
            run(auth.register("alice", "secret"))
            router = _make_router(path, auth=auth)

            ws = FakeWebSocket(messages=[_msg(cmd=CMD_LOGIN, username="alice", password="secret")])
            run(router.handle(ws))

            lines = _read_lines(path)
            auth_lines = [l for l in lines if l["type"] == "auth_login"]
            self.assertEqual(len(auth_lines), 1)
            self.assertEqual(auth_lines[0]["payload"]["outcome"], "success")
            self.assertEqual(auth_lines[0]["payload"]["username"], "alice")
        finally:
            os.unlink(path)

    def test_auth_login_failure_logged(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)
            run(auth.register("alice", "secret"))
            router = _make_router(path, auth=auth)

            ws = FakeWebSocket(messages=[_msg(cmd=CMD_LOGIN, username="alice", password="wrong")])
            run(router.handle(ws))

            lines = _read_lines(path)
            auth_lines = [l for l in lines if l["type"] == "auth_login"]
            self.assertEqual(len(auth_lines), 1)
            self.assertEqual(auth_lines[0]["payload"]["outcome"], "failure")
        finally:
            os.unlink(path)

    def test_failed_login_log_does_not_contain_password(self):
        """Critical: a failed login log line must never contain the submitted password."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)
            run(auth.register("alice", "secret"))
            router = _make_router(path, auth=auth)

            ws = FakeWebSocket(messages=[_msg(cmd=CMD_LOGIN, username="alice", password="super_secret_pw")])
            run(router.handle(ws))

            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("super_secret_pw", content)
        finally:
            os.unlink(path)

    def test_auth_register_success_logged(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)
            router = _make_router(path, auth=auth)

            ws = FakeWebSocket(messages=[_msg(cmd=CMD_REGISTER, username="newuser", password="pw")])
            run(router.handle(ws))

            lines = _read_lines(path)
            reg_lines = [l for l in lines if l["type"] == "auth_register"]
            self.assertEqual(len(reg_lines), 1)
            self.assertEqual(reg_lines[0]["payload"]["outcome"], "success")
        finally:
            os.unlink(path)

    def test_register_log_does_not_contain_password(self):
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            auth = AuthService(repo=InMemoryUserRepository(), config=_AUTH_CFG)
            router = _make_router(path, auth=auth)

            ws = FakeWebSocket(messages=[_msg(cmd=CMD_REGISTER, username="newuser", password="my_reg_pw")])
            run(router.handle(ws))

            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("my_reg_pw", content)
        finally:
            os.unlink(path)

    def test_router_without_logger_still_works(self):
        """ActivityLogger is optional — router without it must not raise."""
        counter = [0]

        def _room_id_gen():
            counter[0] += 1
            return f"room-{counter[0]}"

        router = ConnectionRouter(
            session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
            realtime_config=_RT_CFG,
            room_id_generator=_room_id_gen,
        )

        async def _go():
            rid = await router.create_room()
            ws = FakeWebSocket(messages=[_msg(cmd=CMD_JOIN_ROOM, room_id=rid, username="alice")])
            await router.handle(ws)

        run(_go())  # must not raise


class TestClientActivityLogger(unittest.TestCase):

    def test_writes_json_line(self):
        from kungfu_chess.client.activity_logger import ClientActivityLogger
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            cal = ClientActivityLogger(path)
            run(cal.log("command_sent", {"cmd": "move"}))
            lines = _read_lines(path)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["type"], "command_sent")
            self.assertIn("ts", lines[0])
        finally:
            os.unlink(path)

    def test_redacts_password(self):
        from kungfu_chess.client.activity_logger import ClientActivityLogger
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            cal = ClientActivityLogger(path)
            run(cal.log("auth", {"username": "alice", "password": "secret"}))
            lines = _read_lines(path)
            self.assertNotIn("password", lines[0]["payload"])
            self.assertNotIn("secret", json.dumps(lines[0]))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
