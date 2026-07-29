"""
EloCache — Redis-backed cache for (username -> elo) lookups.

SRP: this class only reads/writes a single Redis key pattern.
     It knows nothing about WebSockets, AuthService, or game logic.

Fail-open: every public method catches all Redis exceptions and returns
None / does nothing, so the caller falls back to Postgres transparently.
The server never crashes because Redis is temporarily unreachable.
"""
from __future__ import annotations

import logging
import socket
from typing import Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "elo:"


def _redis_reachable(host: str, port: int, timeout: float = 0.3) -> bool:
    """
    Raw TCP probe — returns True only if a connection succeeds within timeout.

    Uses getaddrinfo so we try every resolved address (IPv4 + IPv6) but cap
    the total wall time at ``timeout`` seconds.  This avoids the Windows
    localhost->IPv6->IPv4 fallback that makes redis-py hang for 9+ seconds
    when Redis is not running.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception:
        return False
    deadline = socket.getdefaulttimeout()  # save
    for _family, _type, _proto, _canon, sockaddr in infos:
        try:
            with socket.create_connection(sockaddr, timeout=timeout):
                return True
        except Exception:
            continue
    return False


class EloCache:
    """
    Thin Redis wrapper that caches username -> elo with a TTL.

    Parameters
    ----------
    host, port
        Redis connection details — come from RedisConfig, never hardcoded.
    ttl_seconds
        How long a cached entry lives before expiring.
    """

    def __init__(self, host: str, port: int, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._client = None
        if not _redis_reachable(host, port):
            logger.warning("Redis unreachable at %s:%s — ELO cache disabled", host, port)
            return
        try:
            import redis
            self._client = redis.Redis(
                host=host, port=port,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception:
            logger.warning("Redis unavailable at %s:%s — ELO cache disabled", host, port)

    def get(self, username: str) -> Optional[int]:
        """Return cached ELO for username, or None on miss / Redis error."""
        if self._client is None:
            return None
        try:
            val = self._client.get(f"{_KEY_PREFIX}{username}")
            return int(val) if val is not None else None
        except Exception:
            logger.debug("Redis get failed for %r — falling back to DB", username)
            return None

    def set(self, username: str, elo: int) -> None:
        """Cache username -> elo with TTL. Silently ignores Redis errors."""
        if self._client is None:
            return
        try:
            self._client.set(f"{_KEY_PREFIX}{username}", elo, ex=self._ttl)
        except Exception:
            logger.debug("Redis set failed for %r — cache miss on next read", username)

    def invalidate(self, username: str) -> None:
        """Remove a cached entry (call after ELO update). Silently ignores errors."""
        if self._client is None:
            return
        try:
            self._client.delete(f"{_KEY_PREFIX}{username}")
        except Exception:
            logger.debug("Redis delete failed for %r", username)
