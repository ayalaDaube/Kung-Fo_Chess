"""
Tests for EloCache (Redis-backed) and its fail-open behavior.

The fail-open test is the critical one: login must succeed even when Redis
is completely unreachable.  Uses a real (but unreachable) Redis address to
prove the code path, not a mock.

No mock.patch anywhere.
"""
from __future__ import annotations

import asyncio
import os
import unittest

from kungfu_chess.server.auth.elo_cache import EloCache
from kungfu_chess.server.auth.auth_service import AuthService, LoginStatus, RegisterStatus
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.config import AuthConfig

_AUTH_CFG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")

_REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
_REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))


def _redis_available() -> bool:
    try:
        import redis
        r = redis.Redis(
            host=_REDIS_HOST, port=_REDIS_PORT,
            socket_connect_timeout=1, socket_timeout=1,
        )
        r.ping()
        return True
    except Exception:
        return False


_redis_up = _redis_available()


class TestEloCacheFailOpen(unittest.TestCase):
    """
    Login must succeed even when Redis is completely unreachable.
    Uses a deliberately bad host/port so no real Redis is needed.
    """

    def _make_service_with_dead_redis(self) -> AuthService:
        dead_cache = EloCache(host="127.0.0.1", port=19999, ttl_seconds=60)
        return AuthService(
            repo=InMemoryUserRepository(),
            config=_AUTH_CFG,
            elo_cache=dead_cache,
        )

    def test_login_succeeds_when_redis_unreachable(self):
        svc = self._make_service_with_dead_redis()
        asyncio.run(svc.register("alice", "secret"))
        result = asyncio.run(svc.login("alice", "secret"))
        self.assertEqual(result.status, LoginStatus.SUCCESS)
        self.assertIsNotNone(result.user)

    def test_register_succeeds_when_redis_unreachable(self):
        svc = self._make_service_with_dead_redis()
        result = asyncio.run(svc.register("bob", "pw"))
        self.assertEqual(result.status, RegisterStatus.SUCCESS)

    def test_wrong_password_still_rejected_when_redis_unreachable(self):
        svc = self._make_service_with_dead_redis()
        asyncio.run(svc.register("carol", "correct"))
        result = asyncio.run(svc.login("carol", "wrong"))
        self.assertEqual(result.status, LoginStatus.INVALID_CREDENTIALS)

    def test_cache_get_returns_none_when_unreachable(self):
        cache = EloCache(host="127.0.0.1", port=19999, ttl_seconds=60)
        self.assertIsNone(cache.get("anyone"))

    def test_cache_set_does_not_raise_when_unreachable(self):
        cache = EloCache(host="127.0.0.1", port=19999, ttl_seconds=60)
        cache.set("anyone", 1200)  # must not raise

    def test_cache_invalidate_does_not_raise_when_unreachable(self):
        cache = EloCache(host="127.0.0.1", port=19999, ttl_seconds=60)
        cache.invalidate("anyone")  # must not raise


@unittest.skipUnless(_redis_up, f"Redis not reachable at {_REDIS_HOST}:{_REDIS_PORT} — start docker-compose")
class TestEloCacheWithRealRedis(unittest.TestCase):
    """
    Functional tests against a real Redis instance.
    Skipped cleanly when Redis is not running.
    """

    def setUp(self):
        self.cache = EloCache(host=_REDIS_HOST, port=_REDIS_PORT, ttl_seconds=5)
        # Clean up any leftover keys from previous runs.
        self.cache.invalidate("testuser")

    def test_set_and_get(self):
        self.cache.set("testuser", 1350)
        self.assertEqual(self.cache.get("testuser"), 1350)

    def test_get_miss_returns_none(self):
        self.assertIsNone(self.cache.get("no_such_user"))

    def test_invalidate_removes_entry(self):
        self.cache.set("testuser", 1400)
        self.cache.invalidate("testuser")
        self.assertIsNone(self.cache.get("testuser"))

    def test_login_populates_cache(self):
        repo = InMemoryUserRepository()
        svc = AuthService(repo=repo, config=_AUTH_CFG, elo_cache=self.cache)
        asyncio.run(svc.register("cacheuser", "pw"))
        self.cache.invalidate("cacheuser")  # ensure cold start
        asyncio.run(svc.login("cacheuser", "pw"))
        self.assertEqual(self.cache.get("cacheuser"), _AUTH_CFG.default_starting_elo)

    def test_elo_update_invalidates_cache(self):
        from kungfu_chess.server.auth.elo_service import EloService
        repo = InMemoryUserRepository()
        svc = AuthService(repo=repo, config=_AUTH_CFG, elo_cache=self.cache)
        elo_svc = EloService(repo=repo, config=_AUTH_CFG, elo_cache=self.cache)
        asyncio.run(svc.register("winner", "pw"))
        asyncio.run(svc.register("loser", "pw"))
        # Populate cache
        asyncio.run(svc.login("winner", "pw"))
        asyncio.run(svc.login("loser", "pw"))
        self.assertIsNotNone(self.cache.get("winner"))
        # ELO update must invalidate both entries
        asyncio.run(elo_svc.apply_elo_update("winner", "loser"))
        self.assertIsNone(self.cache.get("winner"))
        self.assertIsNone(self.cache.get("loser"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
