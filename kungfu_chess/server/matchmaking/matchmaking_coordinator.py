"""
MatchmakingCoordinator — handles all matchmaking commands and callbacks.

Owns _handle_find_match, _handle_cancel_match, _on_match, _on_match_timeout.
Depends on RoomManager (injected) to create rooms on a match.
"""
from __future__ import annotations
import logging
import time
from typing import Callable, Awaitable

from kungfu_chess.server.config import MatchmakingConfig
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker, MatchResult, QueueEntry
from kungfu_chess.server.matchmaking.matchmaking_loop import MatchmakingLoop
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    MSG_ERROR, MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
)
from kungfu_chess.server.session.room_manager import RoomManager

logger = logging.getLogger(__name__)

SendFn = Callable[[str, dict], Awaitable[None]]
JoinRoomFn = Callable[[str, str, str, dict | None], Awaitable[None]]


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


class MatchmakingCoordinator:
    """
    Drives matchmaking: queuing, cancellation, match callbacks, and timeouts.
    """

    def __init__(
        self,
        config: MatchmakingConfig,
        room_manager: RoomManager,
        registry: ConnectionRegistry,
        send: SendFn,
        join_room: JoinRoomFn,
        disconnect_monitors: dict,
    ) -> None:
        self._room_manager = room_manager
        self._registry = registry
        self._send = send
        self._join_room = join_room
        self._disconnect_monitors = disconnect_monitors

        self._matchmaker = Matchmaker(config)
        self._loop = MatchmakingLoop(
            matchmaker=self._matchmaker,
            config=config,
            on_match=self._on_match,
            on_timeout=self._on_match_timeout,
        )

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def matchmaker(self) -> Matchmaker:
        return self._matchmaker

    @property
    def loop(self) -> MatchmakingLoop:
        return self._loop

    async def handle_find_match(self, conn_id: str) -> None:
        identity = self._registry.identity_of(conn_id)
        if identity is None:
            await self._send(conn_id, {"type": MSG_ERROR, "reason": "must be logged in to find a match"})
            return
        username, elo = identity
        self._matchmaker.enqueue(username, elo, conn_id, _now_ms())

    async def handle_cancel_match(self, conn_id: str) -> None:
        identity = self._registry.identity_of(conn_id)
        if identity is not None:
            self._matchmaker.cancel(identity[0])

    def cancel_by_identity(self, conn_id: str) -> None:
        """Cancel queue entry for conn_id if logged in (called on disconnect)."""
        identity = self._registry.identity_of(conn_id)
        if identity is not None:
            self._matchmaker.cancel(identity[0])

    # ── callbacks ─────────────────────────────────────────────────────────────

    async def _on_match(self, match: MatchResult) -> None:
        rid = await self._room_manager.create_room()
        for entry in (match.entry_a, match.entry_b):
            if self._registry.get_ws(entry.conn_id) is not None:
                await self._join_room(entry.conn_id, rid, entry.username, self._disconnect_monitors)
                await self._send(entry.conn_id, {
                    "type": MSG_MATCH_FOUND,
                    "room_id": rid,
                    "opponent": (
                        match.entry_b.username
                        if entry is match.entry_a
                        else match.entry_a.username
                    ),
                })

    async def _on_match_timeout(self, entry: QueueEntry) -> None:
        if self._registry.get_ws(entry.conn_id) is not None:
            await self._send(entry.conn_id, {"type": MSG_MATCH_TIMEOUT})
