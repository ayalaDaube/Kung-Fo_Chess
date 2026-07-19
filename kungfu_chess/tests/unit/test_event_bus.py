from __future__ import annotations
import asyncio
import unittest
from kungfu_chess.server.bus.event_bus import EventBus


def run(coro):
    return asyncio.run(coro)


class TestEventBusMultipleSubscribers(unittest.TestCase):

    def test_multiple_subscribers_all_called(self):
        bus = EventBus()
        received = []
        bus.subscribe("score.updated", lambda p: received.append(("a", p)))
        bus.subscribe("score.updated", lambda p: received.append(("b", p)))
        run(bus.publish("score.updated", 42))
        self.assertEqual(received, [("a", 42), ("b", 42)])


class TestEventBusNoSubscribers(unittest.TestCase):

    def test_publish_with_no_subscribers_does_not_raise(self):
        bus = EventBus()
        run(bus.publish("game.started", {"room": "x"}))  # must not raise


class TestEventBusMixedHandlers(unittest.TestCase):

    def test_sync_handler_called(self):
        bus = EventBus()
        received = []
        bus.subscribe("move.logged", lambda p: received.append(p))
        run(bus.publish("move.logged", "e4"))
        self.assertEqual(received, ["e4"])

    def test_async_handler_called(self):
        bus = EventBus()
        received = []

        async def handler(payload):
            received.append(payload)

        bus.subscribe("move.logged", handler)
        run(bus.publish("move.logged", "d5"))
        self.assertEqual(received, ["d5"])

    def test_sync_and_async_handlers_together(self):
        bus = EventBus()
        received = []

        async def async_h(p):
            received.append(("async", p))

        bus.subscribe("sound.play", lambda p: received.append(("sync", p)))
        bus.subscribe("sound.play", async_h)
        run(bus.publish("sound.play", "capture.wav"))
        self.assertEqual(received, [("sync", "capture.wav"), ("async", "capture.wav")])


class TestEventBusHandlerException(unittest.TestCase):

    def test_raising_handler_does_not_block_other_subscribers(self):
        bus = EventBus()
        received = []

        def bad_handler(p):
            raise RuntimeError("boom")

        bus.subscribe("game.ended", bad_handler)
        bus.subscribe("game.ended", lambda p: received.append(p))
        run(bus.publish("game.ended", "white_wins"))
        self.assertEqual(received, ["white_wins"])

    def test_raising_async_handler_does_not_block_other_subscribers(self):
        bus = EventBus()
        received = []

        async def bad_async(p):
            raise ValueError("async boom")

        bus.subscribe("game.ended", bad_async)
        bus.subscribe("game.ended", lambda p: received.append(p))
        run(bus.publish("game.ended", "draw"))
        self.assertEqual(received, ["draw"])

    def test_different_topics_are_independent(self):
        bus = EventBus()
        received = []
        bus.subscribe("score.updated", lambda p: received.append(("score", p)))
        bus.subscribe("move.logged",   lambda p: received.append(("move", p)))
        run(bus.publish("score.updated", 5))
        self.assertEqual(received, [("score", 5)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
