"""
Tests for client-side logging.

Uses a real logger writing to a real temp file — no mock.patch.
Verifies that key events (login, move sent, snapshot received,
disconnect/reconnect) produce log entries with the expected content.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import unittest

import websockets

from kungfu_chess.client.logger import setup_client_logging
from kungfu_chess.client.snapshot_receiver import SnapshotReceiver
from kungfu_chess.config_loader import load_config
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.engine.snapshot_builder import build_snapshot
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_CREATE_ROOM, CMD_JOIN_ROOM, CMD_MOVE,
    MSG_ASSIGNED, MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_SNAPSHOT,
    MSG_OPPONENT_DISCONNECTED, MSG_OPPONENT_RECONNECTED,
)
from kungfu_chess.server.network.serialization import snapshot_to_json
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18870

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

_RT_CFG = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=500)
_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def _make_router() -> ConnectionRouter:
    def _engine():
        board = BoardParser().parse(_BOARD)
        return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())
    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_engine),
        realtime_config=_RT_CFG,
    )


def _log_contents(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


class _LogFixture:
    """Context manager: installs a fresh FileHandler on kungfu_chess.client, tears it down after."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._handler: logging.FileHandler | None = None

    def __enter__(self) -> "_LogFixture":
        client_logger = logging.getLogger("kungfu_chess.client")
        self._handler = logging.FileHandler(self._path, encoding="utf-8")
        self._handler.setLevel(logging.DEBUG)
        self._handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        client_logger.setLevel(logging.DEBUG)
        client_logger.addHandler(self._handler)
        return self

    def __exit__(self, *_) -> None:
        client_logger = logging.getLogger("kungfu_chess.client")
        if self._handler:
            self._handler.flush()
            self._handler.close()
            client_logger.removeHandler(self._handler)

    def read(self) -> str:
        if self._handler:
            self._handler.flush()
        return _log_contents(self._path)


class TestClientLoggingConfig(unittest.TestCase):

    def test_client_log_path_in_config(self):
        """GameConfig exposes client_log_path from config (not hardcoded)."""
        cfg = load_config()
        self.assertIsInstance(cfg.client_log_path, str)
        self.assertTrue(len(cfg.client_log_path) > 0)

    def test_setup_client_logging_creates_file_handler(self):
        """setup_client_logging attaches a FileHandler to kungfu_chess.client."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            setup_client_logging(path)
            client_logger = logging.getLogger("kungfu_chess.client")
            handlers = [h for h in client_logger.handlers
                        if isinstance(h, logging.FileHandler)]
            self.assertTrue(any(h.baseFilename == path for h in handlers),
                            "No FileHandler found for the given path")
        finally:
            # Clean up handler so it doesn't bleed into other tests.
            client_logger = logging.getLogger("kungfu_chess.client")
            for h in list(client_logger.handlers):
                if isinstance(h, logging.FileHandler) and h.baseFilename == path:
                    h.close()
                    client_logger.removeHandler(h)
            os.unlink(path)

    def test_setup_client_logging_idempotent(self):
        """Calling setup_client_logging twice does not add duplicate handlers."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            setup_client_logging(path)
            setup_client_logging(path)
            client_logger = logging.getLogger("kungfu_chess.client")
            count = sum(
                1 for h in client_logger.handlers
                if isinstance(h, logging.FileHandler) and h.baseFilename == path
            )
            self.assertEqual(count, 1)
        finally:
            client_logger = logging.getLogger("kungfu_chess.client")
            for h in list(client_logger.handlers):
                if isinstance(h, logging.FileHandler) and h.baseFilename == path:
                    h.close()
                    client_logger.removeHandler(h)
            os.unlink(path)

    def test_debug_records_do_not_propagate_to_root(self):
        """Bug D: DEBUG records from kungfu_chess.client must reach the file
        handler but must NOT propagate to a root handler attached in this test."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        root_records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                root_records.append(record)

        root_handler = _Capture(level=logging.DEBUG)
        root_logger = logging.getLogger()
        root_logger.addHandler(root_handler)
        try:
            setup_client_logging(path)
            logging.getLogger("kungfu_chess.client.test_propagate").debug("should not propagate")
            # Flush the file handler so the write is visible.
            client_logger = logging.getLogger("kungfu_chess.client")
            for h in client_logger.handlers:
                if isinstance(h, logging.FileHandler) and h.baseFilename == path:
                    h.flush()
            file_contents = _log_contents(path)
            # Record reached the file.
            self.assertIn("should not propagate", file_contents)
            # Record did NOT reach the root handler.
            leaked = [r for r in root_records
                      if r.name.startswith("kungfu_chess.client")]
            self.assertEqual(leaked, [],
                             "DEBUG record propagated to root — propagate not disabled")
        finally:
            root_logger.removeHandler(root_handler)
            client_logger = logging.getLogger("kungfu_chess.client")
            for h in list(client_logger.handlers):
                if isinstance(h, logging.FileHandler) and h.baseFilename == path:
                    h.close()
                    client_logger.removeHandler(h)
            # Re-enable propagation so other tests are unaffected.
            client_logger.propagate = True
            os.unlink(path)


class TestSnapshotReceiverLogging(unittest.TestCase):

    def test_snapshot_received_logged(self):
        """Feeding a valid snapshot produces a log entry."""
        board = BoardParser().parse(_BOARD)
        snap = build_snapshot(board, RealTimeArbiter(), selected_cell=None, game_over=False)
        wire = snapshot_to_json(snap)

        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                recv = SnapshotReceiver()
                recv.feed(wire)
                content = fix.read()
            self.assertIn("Snapshot received", content)
        finally:
            os.unlink(path)

    def test_opponent_disconnected_logged(self):
        """MSG_OPPONENT_DISCONNECTED produces an info log entry."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                recv = SnapshotReceiver()
                recv.feed(json.dumps({
                    "type": MSG_OPPONENT_DISCONNECTED,
                    "username": "alice",
                    "auto_resign_ms": 3000,
                }))
                content = fix.read()
            self.assertIn("Opponent disconnected", content)
            self.assertIn("alice", content)
        finally:
            os.unlink(path)

    def test_opponent_reconnected_logged(self):
        """MSG_OPPONENT_RECONNECTED produces an info log entry."""
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                recv = SnapshotReceiver()
                recv.feed(json.dumps({
                    "type": MSG_OPPONENT_RECONNECTED,
                    "username": "alice",
                }))
                content = fix.read()
            self.assertIn("Opponent reconnected", content)
        finally:
            os.unlink(path)

    def test_game_over_snapshot_logged(self):
        """A game-over snapshot produces a log entry mentioning game_over."""
        board = BoardParser().parse(_BOARD)
        snap = build_snapshot(board, RealTimeArbiter(), selected_cell=None, game_over=True)
        wire = snapshot_to_json(snap)

        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                recv = SnapshotReceiver()
                recv.feed(wire)
                content = fix.read()
            self.assertIn("game_over=True", content)
        finally:
            os.unlink(path)


class TestPregameLogging(unittest.TestCase):
    """Login and room-join events produce log entries via real sockets."""

    def test_login_success_logged(self):
        from kungfu_chess.client.pregame import login_or_register
        from kungfu_chess.server.auth.auth_service import AuthService
        from kungfu_chess.server.auth.db import InMemoryUserRepository
        from kungfu_chess.server.config import AuthConfig

        auth_cfg = AuthConfig(default_starting_elo=1200, elo_k_factor=32,
                              sqlite_db_path=":memory:")
        repo = InMemoryUserRepository()
        auth = AuthService(repo=repo, config=auth_cfg)
        asyncio.run(auth.register("testuser", "pw"))

        router = ConnectionRouter(
            session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES,
                                                engine_factory=lambda: GameEngine(
                                                    BoardParser().parse(_BOARD),
                                                    RuleEngine(), RealTimeArbiter())),
            realtime_config=_RT_CFG,
            auth_service=auth,
        )

        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                async def _run():
                    async with websockets.serve(router.handle, _HOST, _PORT):
                        ws = await websockets.connect(f"ws://{_HOST}:{_PORT}")
                        ok = await login_or_register(ws, "testuser", "pw")
                        await ws.close()
                        return ok
                ok = asyncio.run(_run())
                content = fix.read()

            self.assertTrue(ok)
            self.assertIn("Logged in", content)
            self.assertIn("testuser", content)
        finally:
            os.unlink(path)

    def test_login_failure_logged(self):
        from kungfu_chess.client.pregame import login_or_register
        from kungfu_chess.server.auth.auth_service import AuthService
        from kungfu_chess.server.auth.db import InMemoryUserRepository
        from kungfu_chess.server.config import AuthConfig

        auth_cfg = AuthConfig(default_starting_elo=1200, elo_k_factor=32,
                              sqlite_db_path=":memory:")
        repo = InMemoryUserRepository()
        auth = AuthService(repo=repo, config=auth_cfg)
        asyncio.run(auth.register("testuser2", "correct"))

        router = ConnectionRouter(
            session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES,
                                                engine_factory=lambda: GameEngine(
                                                    BoardParser().parse(_BOARD),
                                                    RuleEngine(), RealTimeArbiter())),
            realtime_config=_RT_CFG,
            auth_service=auth,
        )

        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                async def _run():
                    async with websockets.serve(router.handle, _HOST, _PORT + 1):
                        ws = await websockets.connect(f"ws://{_HOST}:{_PORT + 1}")
                        ok = await login_or_register(ws, "testuser2", "wrong")
                        await ws.close()
                        return ok
                ok = asyncio.run(_run())
                content = fix.read()

            self.assertFalse(ok)
            self.assertIn("Auth failed", content)
        finally:
            os.unlink(path)

    def test_room_joined_logged(self):
        from kungfu_chess.client.pregame import room_flow

        router = _make_router()

        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            path = f.name
        try:
            with _LogFixture(path) as fix:
                async def _run():
                    async with websockets.serve(router.handle, _HOST, _PORT + 2):
                        ws = await websockets.connect(f"ws://{_HOST}:{_PORT + 2}")
                        result = await room_flow(ws, "alice",
                                                 read=lambda: "",
                                                 write=lambda _: None)
                        await ws.close()
                        return result
                result = asyncio.run(_run())
                content = fix.read()

            self.assertIsNotNone(result)
            self.assertIn("Room joined", content)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
