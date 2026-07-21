"""
Smoke tests for server/main.py wiring.
Verifies ConnectionRouter construction, auth wiring, and room management.
"""
from __future__ import annotations
import asyncio
import unittest

from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import SqliteUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.session.game_session import GameSession


def _build_router() -> ConnectionRouter:
    config = load_server_config()
    repo = SqliteUserRepository(config.auth.sqlite_db_path)
    auth_service = AuthService(repo=repo, config=config.auth)

    def _session_factory() -> GameSession:
        return GameSession(bus=EventBus())

    return ConnectionRouter(
        session_factory=_session_factory,
        realtime_config=config.realtime,
        auth_service=auth_service,
    )


class TestConnectionRouterWiring(unittest.TestCase):

    def test_construction_does_not_raise(self):
        self.assertIsNotNone(_build_router())

    def test_auth_service_is_wired(self):
        router = _build_router()
        self.assertIsInstance(router._auth, AuthService)

    def test_realtime_config_is_wired(self):
        config = load_server_config()
        router = _build_router()
        self.assertEqual(router._realtime_config.tick_interval_ms,
                         config.realtime.tick_interval_ms)

    def test_no_rooms_initially(self):
        router = _build_router()
        self.assertEqual(router.room_ids(), [])


class TestConnectionRouterRooms(unittest.TestCase):

    def setUp(self):
        self.router = _build_router()

    def test_create_room_returns_id(self):
        rid = asyncio.run(self.router.create_room("test-room"))
        self.assertEqual(rid, "test-room")

    def test_create_room_appears_in_room_ids(self):
        asyncio.run(self.router.create_room("room-1"))
        self.assertIn("room-1", self.router.room_ids())

    def test_session_for_returns_game_session(self):
        asyncio.run(self.router.create_room("room-2"))
        session = self.router.session_for("room-2")
        self.assertIsInstance(session, GameSession)

    def test_session_for_unknown_room_returns_none(self):
        self.assertIsNone(self.router.session_for("no-such-room"))

    def test_cancel_room_removes_it(self):
        asyncio.run(self.router.create_room("room-3"))
        self.router.cancel_room("room-3")
        self.assertNotIn("room-3", self.router.room_ids())

    def test_cancel_room_returns_true_when_exists(self):
        asyncio.run(self.router.create_room("room-4"))
        self.assertTrue(self.router.cancel_room("room-4"))

    def test_cancel_room_returns_false_when_missing(self):
        self.assertFalse(self.router.cancel_room("ghost-room"))

    def test_create_room_sets_game_id_on_session(self):
        asyncio.run(self.router.create_room("room-5"))
        session = self.router.session_for("room-5")
        self.assertEqual(session.game_id, "room-5")

    def test_create_room_auto_generates_id_when_none(self):
        rid = asyncio.run(self.router.create_room())
        self.assertIn(rid, self.router.room_ids())
        self.assertTrue(len(rid) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
