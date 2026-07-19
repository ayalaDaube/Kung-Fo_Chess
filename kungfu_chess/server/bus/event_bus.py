from __future__ import annotations
import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """
    Pure in-process asyncio pub/sub bus.
    Decouples publishers from subscribers using plain topic strings
    (e.g. "score.updated", "move.logged", "game.started").
    Handlers may be plain callables or coroutine functions — both are supported.
    A handler that raises does not prevent other subscribers from receiving the event.
    Must not import from kungfu_chess.server.network or any networking layer.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Callable) -> None:
        """Register handler to be called whenever topic is published."""
        self._handlers[topic].append(handler)

    async def publish(self, topic: str, payload: Any = None) -> None:
        """Deliver payload to every subscriber of topic.
        Awaits coroutine handlers; calls plain callables directly.
        Exceptions are logged and swallowed so all subscribers are reached."""
        for handler in list(self._handlers[topic]):
            try:
                result = handler(payload)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("EventBus handler %r raised on topic %r", handler, topic)
