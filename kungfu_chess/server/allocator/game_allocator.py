"""
GameAllocator — decides which Game Server Shard hosts a new room.

SRP: this class only makes the allocation decision.  It does not store
anything (that is RoomDirectory's job), does not manage connections, and
does not know about game logic.

Today there is exactly one shard, so allocate_shard() always returns the
single configured address.  This is intentional and documented — it is NOT
a bug or a placeholder no-op.  The method is a genuine decision point:
when a second shard is added, only this method's internals change (e.g. to
pick the least-loaded shard from a Redis health-check set).  No caller
changes are needed.

The shard address comes from AllocatorConfig — never hardcoded.
"""
from __future__ import annotations

import logging

from kungfu_chess.server.config import AllocatorConfig

logger = logging.getLogger(__name__)


class GameAllocator:
    """
    Allocates a Game Server Shard for a new room.

    Parameters
    ----------
    config
        AllocatorConfig carrying the single shard address (today) or the
        selection strategy parameters (future).
    """

    def __init__(self, config: AllocatorConfig) -> None:
        self._config = config

    def allocate_shard(self, room_id: str) -> str:
        """
        Return the shard address that should host room_id.

        Today: always returns the single configured shard address.
        This is intentional — there is only one shard.  The method
        exists as a real decision point so callers never bypass it.

        Future: inspect a Redis shard-health set and pick the least-loaded
        shard, or use consistent hashing on room_id.  That change happens
        here only.
        """
        logger.debug("Allocating shard for room %r -> %s", room_id, self._config.shard_address)
        return self._config.shard_address
