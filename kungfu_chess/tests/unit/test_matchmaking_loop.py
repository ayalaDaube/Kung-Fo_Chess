"""
Tests for MatchmakingLoop and DisconnectMonitor.
Same style as test_tick_loop.py — no mock.patch.
"""
from __future__ import annotations
import asyncio
import unittest

from kungfu_chess.server.config import MatchmakingConfig
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker, MatchResult, QueueEntry
from kungfu_chess.server.matchmaking.matchmaking_loop import MatchmakingLoop
from kungfu_chess.server.session.disconnect_monitor import DisconnectMonitor

_MM_CFG = MatchmakingConfig(
    elo_range=200,
    elo_widen_step=50,
    widen_interval_ms=20,   # fast for tests
    timeout_ms=100,
)


def run(coro):
    return asyncio.run(coro)


# ── MatchmakingLoop ───────────────────────────────────────────────────────────

class TestMatchmakingLoop(unittest.TestCase):

    def test_not_running_before_start(self):
        mm = Matchmaker(_MM_CFG)
        loop = MatchmakingLoop(mm, _MM_CFG, on_match=lambda m: None, on_timeout=lambda e: None)
        self.assertFalse(loop.running)

    def test_running_after_start(self):
        mm = Matchmaker(_MM_CFG)

        async def _run():
            loop = MatchmakingLoop(mm, _MM_CFG,
                                   on_match=lambda m: asyncio.sleep(0),
                                   on_timeout=lambda e: asyncio.sleep(0))
            loop.start()
            self.assertTrue(loop.running)
            loop.stop()

        run(_run())

    def test_stop_is_idempotent(self):
        mm = Matchmaker(_MM_CFG)

        async def _run():
            loop = MatchmakingLoop(mm, _MM_CFG,
                                   on_match=lambda m: asyncio.sleep(0),
                                   on_timeout=lambda e: asyncio.sleep(0))
            loop.start()
            loop.stop()
            loop.stop()
            self.assertFalse(loop.running)

        run(_run())

    def test_start_is_idempotent(self):
        mm = Matchmaker(_MM_CFG)

        async def _run():
            loop = MatchmakingLoop(mm, _MM_CFG,
                                   on_match=lambda m: asyncio.sleep(0),
                                   on_timeout=lambda e: asyncio.sleep(0))
            loop.start()
            first_task = loop._task
            loop.start()
            self.assertIs(loop._task, first_task)
            loop.stop()

        run(_run())

    def test_on_match_called_when_pair_found(self):
        mm = Matchmaker(_MM_CFG)
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1200, "c2", 0)
        matches: list[MatchResult] = []

        async def _on_match(m: MatchResult):
            matches.append(m)

        async def _run():
            loop = MatchmakingLoop(mm, _MM_CFG,
                                   on_match=_on_match,
                                   on_timeout=lambda e: asyncio.sleep(0))
            loop.start()
            await asyncio.sleep(0.06)   # 3 ticks at 20 ms
            loop.stop()

        run(_run())
        self.assertEqual(len(matches), 1)
        usernames = {matches[0].entry_a.username, matches[0].entry_b.username}
        self.assertEqual(usernames, {"alice", "bob"})

    def test_on_timeout_called_for_expired_entry(self):
        mm = Matchmaker(_MM_CFG)
        mm.enqueue("alice", 1200, "c1", 0)   # will time out at 100 ms
        timed_out: list[QueueEntry] = []

        async def _on_timeout(e: QueueEntry):
            timed_out.append(e)

        async def _run():
            loop = MatchmakingLoop(mm, _MM_CFG,
                                   on_match=lambda m: asyncio.sleep(0),
                                   on_timeout=_on_timeout)
            loop.start()
            await asyncio.sleep(0.15)   # past 100 ms timeout
            loop.stop()

        run(_run())
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(timed_out[0].username, "alice")


# ── DisconnectMonitor ─────────────────────────────────────────────────────────

class TestDisconnectMonitor(unittest.TestCase):

    def test_not_armed_before_start(self):
        monitor = DisconnectMonitor(delay_ms=100, on_resign=lambda: asyncio.sleep(0))
        self.assertFalse(monitor.armed)

    def test_armed_after_start(self):
        async def _run():
            monitor = DisconnectMonitor(delay_ms=500, on_resign=lambda: asyncio.sleep(0))
            monitor.start()
            self.assertTrue(monitor.armed)
            monitor.cancel()

        run(_run())

    def test_cancel_is_idempotent(self):
        async def _run():
            monitor = DisconnectMonitor(delay_ms=500, on_resign=lambda: asyncio.sleep(0))
            monitor.start()
            monitor.cancel()
            monitor.cancel()
            self.assertFalse(monitor.armed)

        run(_run())

    def test_start_is_idempotent(self):
        async def _run():
            monitor = DisconnectMonitor(delay_ms=500, on_resign=lambda: asyncio.sleep(0))
            monitor.start()
            first_task = monitor._task
            monitor.start()
            self.assertIs(monitor._task, first_task)
            monitor.cancel()

        run(_run())

    def test_on_resign_fires_after_delay(self):
        fired: list[bool] = []

        async def _resign():
            fired.append(True)

        async def _run():
            monitor = DisconnectMonitor(delay_ms=30, on_resign=_resign)
            monitor.start()
            await asyncio.sleep(0.08)

        run(_run())
        self.assertEqual(fired, [True])

    def test_cancel_prevents_resign(self):
        fired: list[bool] = []

        async def _resign():
            fired.append(True)

        async def _run():
            monitor = DisconnectMonitor(delay_ms=50, on_resign=_resign)
            monitor.start()
            await asyncio.sleep(0.01)   # cancel well before delay
            monitor.cancel()
            await asyncio.sleep(0.08)   # wait past original delay

        run(_run())
        self.assertEqual(fired, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
