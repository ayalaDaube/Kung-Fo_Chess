"""
Integration tests for PostgresUserRepository.

These tests run against a REAL PostgreSQL instance — the same one started
by docker-compose.  If Postgres is not reachable (no Docker running locally)
every test in this module is SKIPPED with a clear message rather than failing.

No mock.patch anywhere — real connections, real SQL.
"""
from __future__ import annotations

import os
import unittest

# ── connection details from env (same vars docker-compose passes to server) ──

_PG_HOST = os.environ.get("POSTGRES_HOST", "localhost")
_PG_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
_PG_USER = os.environ.get("POSTGRES_USER", "kungfu")
_PG_PASS = os.environ.get("POSTGRES_PASSWORD", "changeme")
_PG_DB   = os.environ.get("POSTGRES_DB", "kungfu_chess")


def _pg_available() -> bool:
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=_PG_HOST, port=_PG_PORT,
            user=_PG_USER, password=_PG_PASS,
            dbname=_PG_DB,
            connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:
        return False


_SKIP_REASON = (
    f"PostgreSQL not reachable at {_PG_HOST}:{_PG_PORT} — "
    "start docker-compose to run these tests"
)

_pg_up = _pg_available()


def _make_repo():
    from kungfu_chess.server.auth.db import PostgresUserRepository
    repo = PostgresUserRepository(
        host=_PG_HOST, port=_PG_PORT,
        user=_PG_USER, password=_PG_PASS,
        dbname=_PG_DB,
    )
    # Wipe the users table before each test for isolation.
    import psycopg2
    conn = psycopg2.connect(
        host=_PG_HOST, port=_PG_PORT,
        user=_PG_USER, password=_PG_PASS,
        dbname=_PG_DB,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE users")
    conn.close()
    return repo


@unittest.skipUnless(_pg_up, _SKIP_REASON)
class TestPostgresUserRepository(unittest.TestCase):

    def setUp(self):
        self.repo = _make_repo()

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.repo.get_user_by_username("nobody"))

    def test_create_and_retrieve(self):
        self.repo.create_user("alice", "hash123", 1200)
        user = self.repo.get_user_by_username("alice")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.password_hash, "hash123")
        self.assertEqual(user.elo, 1200)

    def test_create_duplicate_raises_value_error(self):
        self.repo.create_user("bob", "hash", 1200)
        with self.assertRaises(ValueError):
            self.repo.create_user("bob", "other", 1000)

    def test_update_elo(self):
        self.repo.create_user("carol", "hash", 1200)
        self.repo.update_elo("carol", 1350)
        self.assertEqual(self.repo.get_user_by_username("carol").elo, 1350)

    def test_implements_protocol(self):
        from kungfu_chess.server.auth.db import UserRepository
        self.assertIsInstance(self.repo, UserRepository)

    def test_multiple_users_isolated(self):
        self.repo.create_user("u1", "h1", 1100)
        self.repo.create_user("u2", "h2", 1300)
        self.assertEqual(self.repo.get_user_by_username("u1").elo, 1100)
        self.assertEqual(self.repo.get_user_by_username("u2").elo, 1300)

    def test_update_elo_does_not_affect_other_users(self):
        self.repo.create_user("x", "hx", 1200)
        self.repo.create_user("y", "hy", 1200)
        self.repo.update_elo("x", 1250)
        self.assertEqual(self.repo.get_user_by_username("y").elo, 1200)


@unittest.skipUnless(_pg_up, _SKIP_REASON)
class TestPostgresWithAuthService(unittest.TestCase):
    """
    Smoke-test AuthService wired to PostgresUserRepository — register/login
    round-trip against a real Postgres, matching the existing SQLite test style.
    """

    def setUp(self):
        from kungfu_chess.server.auth.auth_service import AuthService
        from kungfu_chess.server.config import AuthConfig
        self.repo = _make_repo()
        cfg = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")
        self.svc = AuthService(repo=self.repo, config=cfg)

    def test_register_and_login_success(self):
        import asyncio
        from kungfu_chess.server.auth.auth_service import RegisterStatus, LoginStatus
        asyncio.run(self.svc.register("pguser", "pgpass"))
        result = asyncio.run(self.svc.login("pguser", "pgpass"))
        self.assertEqual(result.status, LoginStatus.SUCCESS)
        self.assertEqual(result.user.username, "pguser")

    def test_duplicate_register_returns_duplicate_status(self):
        import asyncio
        from kungfu_chess.server.auth.auth_service import RegisterStatus
        asyncio.run(self.svc.register("dup", "pw"))
        result = asyncio.run(self.svc.register("dup", "pw2"))
        self.assertEqual(result.status, RegisterStatus.DUPLICATE)

    def test_wrong_password_returns_invalid_credentials(self):
        import asyncio
        from kungfu_chess.server.auth.auth_service import LoginStatus
        asyncio.run(self.svc.register("pguser2", "correct"))
        result = asyncio.run(self.svc.login("pguser2", "wrong"))
        self.assertEqual(result.status, LoginStatus.INVALID_CREDENTIALS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
