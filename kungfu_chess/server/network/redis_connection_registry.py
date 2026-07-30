"""
RedisConnectionRegistry — Redis-backed implementation of the ConnectionRegistry
interface.

Stores all shareable state in Redis so that two separate processes (ApiGateway
and WsGateway) can read each other's writes without sharing a Python object:

  conn:{conn_id}:identity  -> "username:elo"   (login state)
  conn:{conn_id}:room      -> room_id           (room assignment)
  room:{room_id}:conns     -> Redis set of conn_ids

WebSocket objects are NOT stored in Redis — they are live Python objects that
only exist in the process that owns the TCP connection.  get_ws() returns from
a local dict; register()/forget() maintain that dict locally.

SRP: this class only implements the registry interface.  It knows nothing about
gateways, rooms, auth logic, or game state.

All Redis calls are synchronous (redis-py).  Callers in async code must wrap
with asyncio.to_thread if needed — same pattern as EloCache.  In practice,
WsGateway and ApiGateway call registry methods from within their async handlers,
but registry operations are fast key lookups that complete in <1ms on a local
Redis, so the blocking overhead is negligible for this phase.  A future phase
can add async wrapping if profiling shows it matters.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PREFIX_IDENTITY = "conn:{}:identity"   # -> "username\x00elo"
_PREFIX_ROOM     = "conn:{}:room"       # -> room_id
_PREFIX_CONNS    = "room:{}:conns"      # -> Redis set of conn_ids
_SEP = "\x00"


class RedisConnectionRegistry:
    """
    Redis-backed ConnectionRegistry.

    Parameters
    ----------
    host, port
        Redis connection details — from RedisConfig, never hardcoded.
    key_prefix
        Optional namespace prefix so multiple test runs or deployments
        don't collide on the same Redis instance.
    """

    def __init__(self, host: str, port: int, key_prefix: str = "") -> None:
        import redis
        self._r = redis.Redis(
            host=host, port=port,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        self._prefix = key_prefix
        # WebSocket objects live only in this process — never go to Redis.
        self._local_ws: dict[str, Any] = {}

    # ── key helpers ───────────────────────────────────────────────────────────

    def _k_identity(self, conn_id: str) -> str:
        return self._prefix + _PREFIX_IDENTITY.format(conn_id)

    def _k_room(self, conn_id: str) -> str:
        return self._prefix + _PREFIX_ROOM.format(conn_id)

    def _k_conns(self, room_id: str) -> str:
        return self._prefix + _PREFIX_CONNS.format(room_id)

    # ── connection lifecycle ──────────────────────────────────────────────────

    def register(self, conn_id: str, ws: Any) -> None:
        """Store ws locally; announce conn_id existence via a Redis key."""
        self._local_ws[conn_id] = ws

    def forget(self, conn_id: str) -> None:
        self._local_ws.pop(conn_id, None)
        room_id = self.room_of(conn_id)
        if room_id is not None:
            self._r.srem(self._k_conns(room_id), conn_id)
        self._r.delete(self._k_identity(conn_id), self._k_room(conn_id))

    def get_ws(self, conn_id: str) -> Any | None:
        return self._local_ws.get(conn_id)

    def all_conn_ids(self) -> list[str]:
        return list(self._local_ws.keys())

    # ── login state ───────────────────────────────────────────────────────────

    def mark_logged_in(self, conn_id: str, username: str, elo: int) -> None:
        self._r.set(self._k_identity(conn_id), f"{username}{_SEP}{elo}")

    def identity_of(self, conn_id: str) -> tuple[str, int] | None:
        val = self._r.get(self._k_identity(conn_id))
        if val is None:
            return None
        username, elo_str = val.split(_SEP, 1)
        return username, int(elo_str)

    def forget_login(self, conn_id: str) -> None:
        self._r.delete(self._k_identity(conn_id))

    # ── room assignment ───────────────────────────────────────────────────────

    def assign_room(self, conn_id: str, room_id: str) -> None:
        old_room = self.room_of(conn_id)
        if old_room is not None and old_room != room_id:
            self._r.srem(self._k_conns(old_room), conn_id)
        self._r.set(self._k_room(conn_id), room_id)
        self._r.sadd(self._k_conns(room_id), conn_id)

    def room_of(self, conn_id: str) -> str | None:
        return self._r.get(self._k_room(conn_id))

    def forget_room(self, conn_id: str) -> None:
        room_id = self.room_of(conn_id)
        if room_id is not None:
            self._r.srem(self._k_conns(room_id), conn_id)
        self._r.delete(self._k_room(conn_id))

    def conns_in_room(self, room_id: str) -> list[str]:
        return list(self._r.smembers(self._k_conns(room_id)))

    def remove_room_entries(self, room_id: str) -> None:
        members = self._r.smembers(self._k_conns(room_id))
        pipe = self._r.pipeline()
        for conn_id in members:
            pipe.delete(self._k_room(conn_id))
        pipe.delete(self._k_conns(room_id))
        pipe.execute()
