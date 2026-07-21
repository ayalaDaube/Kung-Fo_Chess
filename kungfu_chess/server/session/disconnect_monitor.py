"""
Per-player disconnect monitor.

Starts a one-shot asyncio.Task that fires after auto_resign_ms unless
cancel() is called first (reconnect path).  Never touches a WebSocket.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

OnResignFn = Callable[[], Awaitable[None]]


class DisconnectMonitor:
    """
    Fires on_resign exactly once after delay_ms unless cancelled first.
    Lifecycle mirrors TickLoop: start() / cancel(), both idempotent.
    """

    def __init__(self, delay_ms: int, on_resign: OnResignFn) -> None:
        self._delay_s = delay_ms / 1000.0
        self._on_resign = on_resign
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Arm the timer.  Must be called from within a running event loop."""
        if self._task is not None:
            return
        self._task = asyncio.get_running_loop().create_task(self._run())

    def cancel(self) -> None:
        """Disarm the timer without firing.  Idempotent."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @property
    def armed(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self._delay_s)
            await self._on_resign()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("DisconnectMonitor on_resign raised")
