"""
Pure, synchronous matchmaking queue.

No asyncio, no sockets — all state is plain Python so the logic is
trivially unit-testable with fake timestamps.

Responsibilities:
  - Hold a queue of waiting players.
  - find_match(now_ms): pair two players whose ELO windows overlap,
    widening each player's window by elo_widen_step every widen_interval_ms.
  - sweep_timeouts(now_ms): remove players who have waited longer than timeout_ms.
  - enqueue / cancel: add/remove a single player.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from kungfu_chess.server.config import MatchmakingConfig


@dataclass
class QueueEntry:
    username: str
    elo: int
    conn_id: str
    joined_at_ms: int


@dataclass
class MatchResult:
    entry_a: QueueEntry
    entry_b: QueueEntry


class Matchmaker:
    """
    Synchronous matchmaking queue.  All methods are pure functions of
    the injected now_ms timestamp — no wall-clock calls inside.
    """

    def __init__(self, config: MatchmakingConfig) -> None:
        self._config = config
        self._queue: list[QueueEntry] = []

    # ── public API ────────────────────────────────────────────────────────────

    def enqueue(self, username: str, elo: int, conn_id: str, joined_at_ms: int) -> None:
        """Add a player to the queue.  Replaces any existing entry for the same username."""
        self.cancel(username)
        self._queue.append(QueueEntry(username=username, elo=elo,
                                      conn_id=conn_id, joined_at_ms=joined_at_ms))

    def cancel(self, username: str) -> bool:
        """Remove a player from the queue.  Returns True if they were present."""
        before = len(self._queue)
        self._queue = [e for e in self._queue if e.username != username]
        return len(self._queue) < before

    def find_match(self, now_ms: int) -> MatchResult | None:
        """
        Scan the queue for the first pair whose current ELO windows overlap.
        Each player's window widens by elo_widen_step every widen_interval_ms.
        Returns a MatchResult and removes both entries, or None if no pair found.
        """
        for i, a in enumerate(self._queue):
            range_a = self._current_range(a, now_ms)
            for j in range(i + 1, len(self._queue)):
                b = self._queue[j]
                range_b = self._current_range(b, now_ms)
                if abs(a.elo - b.elo) <= max(range_a, range_b):
                    self._queue = [e for k, e in enumerate(self._queue) if k not in (i, j)]
                    return MatchResult(entry_a=a, entry_b=b)
        return None

    def sweep_timeouts(self, now_ms: int) -> list[QueueEntry]:
        """Remove and return all entries that have exceeded timeout_ms."""
        timed_out = [e for e in self._queue
                     if now_ms - e.joined_at_ms >= self._config.timeout_ms]
        self._queue = [e for e in self._queue
                       if now_ms - e.joined_at_ms < self._config.timeout_ms]
        return timed_out

    def queue_size(self) -> int:
        return len(self._queue)

    # ── internal ──────────────────────────────────────────────────────────────

    def _current_range(self, entry: QueueEntry, now_ms: int) -> int:
        elapsed = now_ms - entry.joined_at_ms
        steps = elapsed // self._config.widen_interval_ms
        return self._config.elo_range + steps * self._config.elo_widen_step
