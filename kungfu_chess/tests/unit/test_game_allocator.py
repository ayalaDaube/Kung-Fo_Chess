"""
Tests for RoomDirectory and GameAllocator.

RoomDirectory tests run against a REAL Redis instance — skipped with a
clear message if Redis is not reachable.  No fake-Redis stand-in.

GameAllocator tests are pure-Python (no Redis needed).

The "lookup path is real" tests prove that the RoomDirectory wiring in
RoomManager is genuine: create_room writes an entry, cancel_room removes
it, and passing no allocator writes nothing.
"""
from __future__ import annotations

import asyncio
import os
import unittest
import uuid

from kungfu_chess.server.allocator.game_allocator import GameAllocator
from kungfu_chess.server.config import AllocatorConfig

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


def _make_directory(prefix=None):
    from kungfu_chess.server.allocator.room_directory import RoomDirectory
    p = prefix if prefix is not None else f"test:{uuid.uuid4().hex}:"
    return RoomDirectory(host=_REDIS_HOST, port=_REDIS_PORT, key_prefix=p)


def _flush(directory):
    keys = directory._r.keys(directory._ns + "*")
    if keys:
        directory._r.delete(*keys)


# ── RoomDirectory ─────────────────────────────────────────────────────────────

@unittest.skipUnless(_redis_up, _SKIP_REASON)
class TestRoomDirectory(unittest.TestCase):

    def setUp(self):
        self.rd = _make_directory()

    def tearDown(self):
        _flush(self.rd)

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.rd.get("no-such-room"))

    def test_set_and_get(self):
        self.rd.set("room-1", "ws://shard-a:8765")
        self.assertEqual(self.rd.get("room-1"), "ws://shard-a:8765")

    def test_overwrite_updates_address(self):
        self.rd.set("room-1", "ws://shard-a:8765")
        self.rd.set("room-1", "ws://shard-b:8765")
        self.assertEqual(self.rd.get("room-1"), "ws://shard-b:8765")

    def test_delete_removes_entry(self):
        self.rd.set("room-1", "ws://shard-a:8765")
        self.rd.delete("room-1")
        self.assertIsNone(self.rd.get("room-1"))

    def test_delete_nonexistent_does_not_raise(self):
        self.rd.delete("ghost-room")

    def test_multiple_rooms_isolated(self):
        self.rd.set("room-a", "ws://shard-1:8765")
        self.rd.set("room-b", "ws://shard-2:8765")
        self.assertEqual(self.rd.get("room-a"), "ws://shard-1:8765")
        self.assertEqual(self.rd.get("room-b"), "ws://shard-2:8765")


# ── GameAllocator ─────────────────────────────────────────────────────────────

class TestGameAllocator(unittest.TestCase):
    """Pure-Python — no Redis needed."""

    def _make(self, address="ws://localhost:8765"):
        return GameAllocator(config=AllocatorConfig(shard_address=address))

    def test_allocate_shard_returns_configured_address(self):
        alloc = self._make("ws://shard-x:9000")
        self.assertEqual(alloc.allocate_shard("any-room"), "ws://shard-x:9000")

    def test_allocate_shard_always_returns_same_address_today(self):
        """
        Documents that today's single-shard allocator always returns the same
        address regardless of room_id.  Intentional — there is only one shard.
        When a second shard is added, only allocate_shard's internals change.
        """
        alloc = self._make("ws://localhost:8765")
        addresses = {alloc.allocate_shard(f"room-{i}") for i in range(10)}
        self.assertEqual(len(addresses), 1,
                         "Single-shard allocator must always return the same address")

    def test_address_comes_from_config_not_hardcoded(self):
        alloc_a = self._make("ws://shard-a:8765")
        alloc_b = self._make("ws://shard-b:8765")
        self.assertNotEqual(
            alloc_a.allocate_shard("room-1"),
            alloc_b.allocate_shard("room-1"),
        )


# ── Integration: lookup path is real ─────────────────────────────────────────

@unittest.skipUnless(_redis_up, _SKIP_REASON)
class TestRoomDirectoryLookupIsReal(unittest.TestCase):
    """
    Proves the RoomDirectory wiring in RoomManager is genuine, not bypassed.
    """

    def setUp(self):
        self.rd = _make_directory()

    def tearDown(self):
        _flush(self.rd)

    def _make_room_manager(self, allocator, directory):
        from kungfu_chess.server.bus.event_bus import EventBus
        from kungfu_chess.server.config import RealtimeConfig, load_server_config
        from kungfu_chess.server.network.connection_registry import ConnectionRegistry
        from kungfu_chess.server.session.game_session import GameSession
        from kungfu_chess.server.session.room_manager import RoomManager
        from kungfu_chess.engine.game_engine import GameEngine
        from kungfu_chess.io.board_parser import BoardParser
        from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
        from kungfu_chess.rules.rule_engine import RuleEngine

        _BOARD = (
            ". . . . bK . . .\n"
            ". . . . .  . . .\n"
            ". . . . .  . . .\n"
            ". . . . .  . . .\n"
            ". . . . .  . . .\n"
            ". . . . .  . . .\n"
            ". . . . .  . . .\n"
            ". . . . wK . . .\n"
        )

        def _engine_factory():
            board = BoardParser().parse(_BOARD)
            return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())

        cfg = load_server_config()
        rt = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=cfg.realtime.auto_resign_ms)
        reg = ConnectionRegistry()

        async def _send(cid, payload): pass
        async def _send_to_others(rid, exc, payload): pass
        def _make_broadcast(rid):
            async def _bc(msg): pass
            return _bc

        return RoomManager(
            session_factory=lambda: GameSession(
                bus=EventBus(),
                piece_scores={"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0},
                engine_factory=_engine_factory,
            ),
            realtime_config=rt,
            registry=reg,
            room_id_generator=lambda: f"test-{uuid.uuid4().hex[:6]}",
            send=_send,
            send_to_others=_send_to_others,
            make_broadcast=_make_broadcast,
            game_allocator=allocator,
            room_directory=directory,
        )

    def test_create_room_writes_directory_entry(self):
        """create_room must write a RoomDirectory entry when allocator is wired."""
        alloc = GameAllocator(config=AllocatorConfig(shard_address="ws://localhost:8765"))
        rm = self._make_room_manager(alloc, self.rd)

        rid = asyncio.run(rm.create_room())

        shard = self.rd.get(rid)
        self.assertIsNotNone(shard,
            "RoomDirectory must have an entry after create_room")
        self.assertEqual(shard, "ws://localhost:8765")

    def test_create_room_without_allocator_does_not_write_directory(self):
        """
        Without an allocator, no directory entry is written.
        This proves the test above is testing something real — the write is
        conditional on the allocator being present, not always happening.
        """
        rm = self._make_room_manager(allocator=None, directory=self.rd)

        rid = asyncio.run(rm.create_room())

        self.assertIsNone(self.rd.get(rid),
            "Without an allocator, RoomDirectory must NOT be written")

    def test_cancel_room_removes_directory_entry(self):
        """cancel_room must delete the RoomDirectory entry."""
        alloc = GameAllocator(config=AllocatorConfig(shard_address="ws://localhost:8765"))
        rm = self._make_room_manager(alloc, self.rd)

        rid = asyncio.run(rm.create_room())
        self.assertIsNotNone(self.rd.get(rid))

        rm.cancel_room(rid)
        self.assertIsNone(self.rd.get(rid),
            "RoomDirectory entry must be removed after cancel_room")


if __name__ == "__main__":
    unittest.main(verbosity=2)
