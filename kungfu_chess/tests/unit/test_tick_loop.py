"""
Tests for TickLoop.
Uses a fake GameSession and fake broadcast to avoid real engine/network.
No patching.
"""
from __future__ import annotations
import asyncio
import unittest

from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.session.tick_loop import TickLoop


class FakeSession:
    def __init__(self):
        self.tick_calls: list[int] = []
        self.game_id = "test-room"

    def tick(self, ms: int) -> list:
        self.tick_calls.append(ms)
        return []

    def build_snapshot(self):
        from kungfu_chess.model.game_state import GameSnapshot
        return GameSnapshot(
            board_width=8, board_height=8,
            pieces=[], selected_cell=None,
            game_over=False, airborne_pos=None,
        )


def run(coro):
    return asyncio.run(coro)


from kungfu_chess.server.config import load_server_config as _load
_DEFAULT_AUTO_RESIGN_MS = _load().realtime.auto_resign_ms

_CFG_10  = RealtimeConfig(tick_interval_ms=10, auto_resign_ms=_DEFAULT_AUTO_RESIGN_MS)
_CFG_20  = RealtimeConfig(tick_interval_ms=20, auto_resign_ms=_DEFAULT_AUTO_RESIGN_MS)


class TestTickLoopLifecycle(unittest.TestCase):

    def test_not_running_before_start(self):
        session = FakeSession()
        broadcasts = []
        loop = TickLoop(
            session=session,
            broadcast=lambda msg: broadcasts.append(msg) or asyncio.sleep(0),
            config=_CFG_10,
        )
        self.assertFalse(loop.running)

    def test_running_after_start(self):
        session = FakeSession()
        broadcasts = []

        async def _broadcast(msg): broadcasts.append(msg)

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            self.assertTrue(loop.running)
            loop.stop()

        run(_run())

    def test_stop_is_idempotent(self):
        session = FakeSession()

        async def _broadcast(msg): pass

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            loop.stop()
            loop.stop()   # second stop must not raise
            self.assertFalse(loop.running)

        run(_run())

    def test_start_is_idempotent(self):
        session = FakeSession()

        async def _broadcast(msg): pass

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            task_first = loop._task
            loop.start()   # second start must not create a new task
            self.assertIs(loop._task, task_first)
            loop.stop()

        run(_run())

    def test_tick_called_after_interval(self):
        session = FakeSession()
        broadcasts = []

        async def _broadcast(msg): broadcasts.append(msg)

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            await asyncio.sleep(0.035)   # ~3 ticks at 10 ms
            loop.stop()

        run(_run())
        self.assertGreaterEqual(len(session.tick_calls), 1)

    def test_broadcast_called_after_tick(self):
        session = FakeSession()
        broadcasts = []

        async def _broadcast(msg): broadcasts.append(msg)

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            await asyncio.sleep(0.035)
            loop.stop()

        run(_run())
        self.assertGreaterEqual(len(broadcasts), 1)

    def test_tick_interval_from_config(self):
        """Tick interval must come from config, not a hardcoded literal."""
        session = FakeSession()

        async def _broadcast(msg): pass

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_20)
        self.assertAlmostEqual(loop._interval_s, 0.020, places=5)

    def test_no_duplicate_broadcast_when_snapshot_unchanged(self):
        """
        TickLoop must NOT broadcast on ticks where the snapshot JSON is
        identical to the last broadcast.  FakeSession.build_snapshot() always
        returns the same value, so after the first broadcast every subsequent
        tick must be suppressed.
        """
        session = FakeSession()
        broadcasts = []

        async def _broadcast(msg): broadcasts.append(msg)

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            await asyncio.sleep(0.055)  # ~5 ticks at 10 ms
            loop.stop()

        run(_run())
        # Snapshot never changes, so exactly 1 broadcast should have occurred.
        self.assertEqual(len(broadcasts), 1)

    def test_broadcast_resumes_when_snapshot_changes(self):
        """
        After a period of no change, a new distinct snapshot must be broadcast.
        """
        session = FakeSession()
        broadcasts = []
        call_count = [0]

        # Return a different snapshot starting from the 2nd build_snapshot call.
        original_build = session.build_snapshot
        def _varying_snapshot():
            call_count[0] += 1
            if call_count[0] >= 2:
                from kungfu_chess.model.game_state import GameSnapshot
                return GameSnapshot(
                    board_width=8, board_height=8,
                    pieces=[], selected_cell=None,
                    game_over=True, airborne_pos=None,
                )
            return original_build()
        session.build_snapshot = _varying_snapshot

        async def _broadcast(msg): broadcasts.append(msg)

        loop = TickLoop(session=session, broadcast=_broadcast, config=_CFG_10)

        async def _run():
            loop.start()
            await asyncio.sleep(0.08)  # ~8 ticks at 10 ms — enough margin on Windows
            loop.stop()

        run(_run())
        # Tick 1: initial snapshot broadcast. Tick 2+: changed snapshot broadcast once.
        self.assertGreaterEqual(len(broadcasts), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
