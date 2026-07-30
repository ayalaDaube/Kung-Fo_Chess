"""
Tests for RedisConnectionRegistry.

All tests run against a REAL Redis instance.  If Redis is not reachable
every test in this module is SKIPPED with a clear message.

No mock.patch anywhere — real connections, real Redis keys.

The cross-process integration test (TestCrossProcessSharing) is the key
deliverable of Phase 9: it proves that login state written by one registry
instance (simulating ApiGateway's process) is immediately visible to a
second, separate registry instance (simulating WsGateway's process) when
both are backed by the same Redis.  It also explicitly verifies that the
same test FAILS when run against two separate in-memory ConnectionRegistry
instances — proving the test is actually exercising Redis sharing, not
something trivially true regardless of backend.
"""
from __future__ import annotations

import os
import unittest
import uuid

from kungfu_chess.server.network.connection_registry import ConnectionRegistry

_REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
_REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

_SKIP_REASON = (
    f"Redis not reachable at {_REDIS_HOST}:{_REDIS_PORT} — "
    "start Redis (or docker-compose) to run these tests"
)


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


def _make_registry(prefix: str | None = None) -> "RedisConnectionRegistry":
    from kungfu_chess.server.network.redis_connection_registry import RedisConnectionRegistry
    # Each test gets a unique key prefix so parallel runs don't collide.
    p = prefix if prefix is not None else f"test:{uuid.uuid4().hex}:"
    reg = RedisConnectionRegistry(host=_REDIS_HOST, port=_REDIS_PORT, key_prefix=p)
    return reg


def _flush_prefix(reg) -> None:
    """Delete all keys written by this registry instance."""
    pattern = reg._prefix + "*"
    keys = reg._r.keys(pattern)
    if keys:
        reg._r.delete(*keys)


@unittest.skipUnless(_redis_up, _SKIP_REASON)
class TestRedisConnectionRegistryLogin(unittest.TestCase):

    def setUp(self):
        self.reg = _make_registry()

    def tearDown(self):
        _flush_prefix(self.reg)

    def test_identity_of_unknown_returns_none(self):
        self.assertIsNone(self.reg.identity_of("no-such-conn"))

    def test_mark_logged_in_and_identity_of(self):
        self.reg.register("c1", object())
        self.reg.mark_logged_in("c1", "alice", 1200)
        self.assertEqual(self.reg.identity_of("c1"), ("alice", 1200))

    def test_forget_login_clears_identity(self):
        self.reg.register("c1", object())
        self.reg.mark_logged_in("c1", "alice", 1200)
        self.reg.forget_login("c1")
        self.assertIsNone(self.reg.identity_of("c1"))

    def test_forget_clears_identity(self):
        self.reg.register("c1", object())
        self.reg.mark_logged_in("c1", "alice", 1200)
        self.reg.forget("c1")
        self.assertIsNone(self.reg.identity_of("c1"))

    def test_elo_roundtrips_correctly(self):
        self.reg.register("c1", object())
        self.reg.mark_logged_in("c1", "bob", 1337)
        _, elo = self.reg.identity_of("c1")
        self.assertEqual(elo, 1337)


@unittest.skipUnless(_redis_up, _SKIP_REASON)
class TestRedisConnectionRegistryRooms(unittest.TestCase):

    def setUp(self):
        self.reg = _make_registry()

    def tearDown(self):
        _flush_prefix(self.reg)

    def test_room_of_unknown_returns_none(self):
        self.assertIsNone(self.reg.room_of("no-such-conn"))

    def test_assign_room_and_room_of(self):
        self.reg.register("c1", object())
        self.reg.assign_room("c1", "room-1")
        self.assertEqual(self.reg.room_of("c1"), "room-1")

    def test_conns_in_room(self):
        self.reg.register("c1", object())
        self.reg.register("c2", object())
        self.reg.assign_room("c1", "room-1")
        self.reg.assign_room("c2", "room-1")
        self.assertCountEqual(self.reg.conns_in_room("room-1"), ["c1", "c2"])

    def test_forget_room_removes_conn_from_room(self):
        self.reg.register("c1", object())
        self.reg.assign_room("c1", "room-1")
        self.reg.forget_room("c1")
        self.assertIsNone(self.reg.room_of("c1"))
        self.assertNotIn("c1", self.reg.conns_in_room("room-1"))

    def test_remove_room_entries_clears_all_conns(self):
        self.reg.register("c1", object())
        self.reg.register("c2", object())
        self.reg.assign_room("c1", "room-1")
        self.reg.assign_room("c2", "room-1")
        self.reg.remove_room_entries("room-1")
        self.assertIsNone(self.reg.room_of("c1"))
        self.assertIsNone(self.reg.room_of("c2"))
        self.assertEqual(self.reg.conns_in_room("room-1"), [])

    def test_forget_clears_room_assignment(self):
        self.reg.register("c1", object())
        self.reg.assign_room("c1", "room-1")
        self.reg.forget("c1")
        self.assertIsNone(self.reg.room_of("c1"))
        self.assertNotIn("c1", self.reg.conns_in_room("room-1"))


@unittest.skipUnless(_redis_up, _SKIP_REASON)
class TestRedisConnectionRegistryLocalWs(unittest.TestCase):
    """WebSocket objects are local-only — never stored in Redis."""

    def setUp(self):
        self.reg = _make_registry()

    def tearDown(self):
        _flush_prefix(self.reg)

    def test_get_ws_returns_registered_object(self):
        ws = object()
        self.reg.register("c1", ws)
        self.assertIs(self.reg.get_ws("c1"), ws)

    def test_get_ws_unknown_returns_none(self):
        self.assertIsNone(self.reg.get_ws("no-such-conn"))

    def test_forget_removes_ws(self):
        self.reg.register("c1", object())
        self.reg.forget("c1")
        self.assertIsNone(self.reg.get_ws("c1"))

    def test_implements_registry_protocol(self):
        from kungfu_chess.server.network.connection_registry import RegistryProtocol
        self.assertIsInstance(self.reg, RegistryProtocol)


@unittest.skipUnless(_redis_up, _SKIP_REASON)
class TestCrossProcessSharing(unittest.TestCase):
    """
    The key test for Phase 9: proves that two separate registry instances
    backed by the same Redis can see each other's writes.

    This simulates the real two-process scenario:
      - reg_api  = ApiGateway's registry (writes login state)
      - reg_ws   = WsGateway's registry (reads login state)

    Both use the same key_prefix so they share the same Redis namespace.

    The test also explicitly verifies that the SAME assertions FAIL when
    run against two separate in-memory ConnectionRegistry instances —
    proving the test is actually exercising Redis sharing, not something
    trivially true regardless of backend.
    """

    def setUp(self):
        # Shared prefix — both instances see the same Redis keys.
        self._prefix = f"test:xproc:{uuid.uuid4().hex}:"
        self.reg_api = _make_registry(prefix=self._prefix)
        self.reg_ws  = _make_registry(prefix=self._prefix)

    def tearDown(self):
        _flush_prefix(self.reg_api)

    def test_login_written_by_api_registry_visible_to_ws_registry(self):
        """
        reg_api marks a connection as logged in.
        reg_ws (separate instance, same Redis) must see the identity.
        """
        self.reg_api.mark_logged_in("conn-42", "alice", 1200)
        identity = self.reg_ws.identity_of("conn-42")
        self.assertIsNotNone(identity)
        self.assertEqual(identity, ("alice", 1200))

    def test_room_assigned_by_ws_registry_visible_to_api_registry(self):
        """
        reg_ws assigns a room.
        reg_api (separate instance, same Redis) must see the assignment.
        """
        self.reg_ws.assign_room("conn-99", "room-abc")
        self.assertEqual(self.reg_api.room_of("conn-99"), "room-abc")
        self.assertIn("conn-99", self.reg_api.conns_in_room("room-abc"))

    def test_same_assertions_fail_with_two_in_memory_registries(self):
        """
        Explicitly verify that the cross-process sharing test is NOT
        trivially true: two separate in-memory ConnectionRegistry instances
        do NOT share state, so the same write/read pattern returns None.

        This proves the Redis test above is actually testing something real.
        """
        mem_api = ConnectionRegistry()
        mem_ws  = ConnectionRegistry()

        mem_api.mark_logged_in("conn-42", "alice", 1200)
        # mem_ws is a completely separate object — it cannot see mem_api's write.
        self.assertIsNone(
            mem_ws.identity_of("conn-42"),
            "Two in-memory registries must NOT share state — "
            "if this fails the cross-process Redis test proves nothing.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
