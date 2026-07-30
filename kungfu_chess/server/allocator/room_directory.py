"""
RoomDirectory — Redis-backed room_id -> shard_address mapping.

SRP: this class only stores and looks up which shard address hosts a given
room.  It makes no decisions about which shard to use — that is
GameAllocator's job.  It knows nothing about gateways, connections, or game
logic.

Key pattern:  room_dir:{room_id}  ->  shard_address (string)

All Redis calls are synchronous (redis-py), same pattern as EloCache and
RedisConnectionRegistry.
"""
from __future__ import annotations

import logging
from typing import Optional

from kungfu_chess.server.auth.elo_cache import _redis_reachable

logger = logging.getLogger(__name__)

_KEY_PREFIX = "room_dir:{}"


class RoomDirectory:
    """
    Stores and retrieves the shard address that hosts each room.

    Fail-open: if Redis is unreachable at construction time, set/get/delete
    become no-ops (get returns None), so RoomManager falls back to its local
    allocator transparently — same pattern as EloCache.

    Parameters
    ----------
    host, port
        Redis connection details — from RedisConfig, never hardcoded.
    key_prefix
        Optional namespace prefix for test isolation.
    """

    def __init__(self, host: str, port: int, key_prefix: str = "") -> None:
        self._r = None
        self._ns = key_prefix
        if not _redis_reachable(host, port):
            logger.warning("Redis unreachable at %s:%s — RoomDirectory disabled", host, port)
            return
        try:
            import redis
            self._r = redis.Redis(
                host=host, port=port,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        except Exception:
            logger.warning("Redis unavailable at %s:%s — RoomDirectory disabled", host, port)

    def _key(self, room_id: str) -> str:
        return self._ns + _KEY_PREFIX.format(room_id)

    def set(self, room_id: str, shard_address: str) -> None:
        """Record that room_id is hosted on shard_address."""
        if self._r is None:
            return
        self._r.set(self._key(room_id), shard_address)

    def get(self, room_id: str) -> Optional[str]:
        """Return the shard address for room_id, or None if not found."""
        if self._r is None:
            return None
        return self._r.get(self._key(room_id))

    def delete(self, room_id: str) -> None:
        """Remove the directory entry for room_id (call when room is torn down)."""
        if self._r is None:
            return
        self._r.delete(self._key(room_id))
