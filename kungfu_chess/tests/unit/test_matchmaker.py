"""
Tests for Matchmaker — pure logic, fake timestamps, no asyncio.
"""
from __future__ import annotations
import unittest

from kungfu_chess.server.config import MatchmakingConfig
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker

_CFG = MatchmakingConfig(
    elo_range=100,
    elo_widen_step=50,
    widen_interval_ms=5000,
    timeout_ms=60000,
)


def _mm() -> Matchmaker:
    return Matchmaker(_CFG)


class TestEnqueueCancel(unittest.TestCase):

    def test_enqueue_increases_queue_size(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        self.assertEqual(mm.queue_size(), 1)

    def test_cancel_removes_player(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.cancel("alice")
        self.assertEqual(mm.queue_size(), 0)

    def test_cancel_returns_true_when_present(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        self.assertTrue(mm.cancel("alice"))

    def test_cancel_returns_false_when_absent(self):
        mm = _mm()
        self.assertFalse(mm.cancel("nobody"))

    def test_enqueue_replaces_existing_entry(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("alice", 1300, "c2", 1000)
        self.assertEqual(mm.queue_size(), 1)


class TestFindMatch(unittest.TestCase):

    def test_no_match_when_queue_empty(self):
        mm = _mm()
        self.assertIsNone(mm.find_match(0))

    def test_no_match_single_player(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        self.assertIsNone(mm.find_match(0))

    def test_match_within_elo_range(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1250, "c2", 0)
        result = mm.find_match(0)
        self.assertIsNotNone(result)
        usernames = {result.entry_a.username, result.entry_b.username}
        self.assertEqual(usernames, {"alice", "bob"})

    def test_match_removes_both_from_queue(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1250, "c2", 0)
        mm.find_match(0)
        self.assertEqual(mm.queue_size(), 0)

    def test_no_match_outside_elo_range(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1400, "c2", 0)   # 200 apart, range=100
        self.assertIsNone(mm.find_match(0))

    def test_match_after_widening(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1400, "c2", 0)   # 200 apart
        # After 2 widen intervals (10 000 ms): range = 100 + 2*50 = 200 — exactly matches
        result = mm.find_match(10_000)
        self.assertIsNotNone(result)

    def test_no_match_before_sufficient_widening(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1400, "c2", 0)   # 200 apart
        # After 1 widen interval: range = 150 — still not enough
        self.assertIsNone(mm.find_match(5_000))

    def test_third_player_unmatched_stays_in_queue(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1250, "c2", 0)
        mm.enqueue("carol", 1800, "c3", 0)
        mm.find_match(0)
        self.assertEqual(mm.queue_size(), 1)


class TestSweepTimeouts(unittest.TestCase):

    def test_no_timeouts_before_limit(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        timed_out = mm.sweep_timeouts(59_999)
        self.assertEqual(timed_out, [])
        self.assertEqual(mm.queue_size(), 1)

    def test_timeout_at_limit(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        timed_out = mm.sweep_timeouts(60_000)
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(timed_out[0].username, "alice")
        self.assertEqual(mm.queue_size(), 0)

    def test_only_expired_entries_removed(self):
        mm = _mm()
        mm.enqueue("alice", 1200, "c1", 0)
        mm.enqueue("bob",   1200, "c2", 50_000)   # joined later
        timed_out = mm.sweep_timeouts(60_000)
        self.assertEqual(len(timed_out), 1)
        self.assertEqual(timed_out[0].username, "alice")
        self.assertEqual(mm.queue_size(), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
