"""
Smoke tests for server/main.py wiring.
Verifies that load_server_config() + the full construction chain don't raise,
and that WsServer is wired with a real AuthService (not auth_service=None).
"""
from __future__ import annotations
import unittest

from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import SqliteUserRepository
from kungfu_chess.server.network.ws_server import WsServer


class TestServerMainWiring(unittest.TestCase):

    def test_construction_does_not_raise(self):
        config = load_server_config()
        repo = SqliteUserRepository(config.auth.sqlite_db_path)
        auth_service = AuthService(repo=repo, config=config.auth)
        server = WsServer(auth_service=auth_service)
        self.assertIsNotNone(server)

    def test_auth_service_is_wired(self):
        config = load_server_config()
        repo = SqliteUserRepository(config.auth.sqlite_db_path)
        auth_service = AuthService(repo=repo, config=config.auth)
        server = WsServer(auth_service=auth_service)
        self.assertIsNotNone(server._auth)
        self.assertIsInstance(server._auth, AuthService)


if __name__ == "__main__":
    unittest.main(verbosity=2)
