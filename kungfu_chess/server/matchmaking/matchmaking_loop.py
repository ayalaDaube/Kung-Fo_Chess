"""
Async matchmaking loop — mirrors TickLoop exactly.

Owns one asyncio.Task that fires every widen_interval_ms.
On each tick it calls matchmaker.find_match() and matchmaker.sweep_timeouts(),
then invokes the injected callbacks.  Never touches a WebSocket directly.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Awaitable, Callable

from kungfu_chess.server.config import MatchmakingConfig
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker, QueueEntry, MatchResult

logger = logging.getLogger(__name__)

OnMatchFn   = Callable[[MatchResult], Awaitable[None]]
OnTimeoutFn = Callable[[QueueEntry],  Awaitable[None]]


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


class MatchmakingLoop:
    """
    Drives the Matchmaker forward in real time.
    Decoupled from networking: receives callbacks so it never touches
    WebSocket objects directly.
    """

    def __init__(
        self,
        matchmaker: Matchmaker,
        config: MatchmakingConfig,
        on_match: OnMatchFn,
        on_timeout: OnTimeoutFn,
    ) -> None:
        self._matchmaker = matchmaker
        self._interval_s = config.widen_interval_ms / 1000.0
        self._on_match = on_match
        self._on_timeout = on_timeout
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Start the loop task.  Must be called from within a running event loop."""
        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._run())

    def stop(self) -> None:
        """Cancel the loop task.  Idempotent."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_s)
                now = _now_ms()
                match = self._matchmaker.find_match(now)
                if match is not None:
                    await self._on_match(match)
                for entry in self._matchmaker.sweep_timeouts(now):
                    await self._on_timeout(entry)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("MatchmakingLoop error")
