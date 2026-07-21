"""
Per-room real-time tick loop.

Owns exactly one asyncio.Task that periodically calls session.tick(ms)
and broadcasts the resulting snapshot to all connections in the room.
Lifecycle: start() on session creation, stop() on session end.
Tick interval comes from RealtimeConfig — no hardcoded literals here.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Callable, Awaitable

from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.server.network.serialization import snapshot_to_json

logger = logging.getLogger(__name__)

# Broadcast callable: given a snapshot JSON string, sends it to all room connections.
BroadcastFn = Callable[[str], Awaitable[None]]


class TickLoop:
    """
    Drives one GameSession forward in real time.
    Decoupled from networking: receives a broadcast callable so it never
    touches WebSocket objects directly.
    """

    def __init__(
        self,
        session: GameSession,
        broadcast: BroadcastFn,
        config: RealtimeConfig,
    ) -> None:
        self._session = session
        self._broadcast = broadcast
        self._interval_s = config.tick_interval_ms / 1000.0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the tick task. Must be called from within a running event loop."""
        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._run())

    def stop(self) -> None:
        """Cancel the tick task. Idempotent."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        interval_ms = int(self._interval_s * 1000)
        try:
            while True:
                await asyncio.sleep(self._interval_s)
                self._session.tick(interval_ms)
                snapshot_json = snapshot_to_json(self._session.build_snapshot())
                await self._broadcast(snapshot_json)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Tick loop error in game %r", self._session.game_id)
