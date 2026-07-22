"""
ActivityLogger — pure JSON-lines sink for server-side structured logging.

SRP: this class only serialises a record and appends it to a file.
It knows nothing about WebSockets, GameSession, or AuthService.

Every write is dispatched via asyncio.to_thread so it never blocks the
event loop (same reasoning as the SQLite calls in auth_service.py).

Password redaction: any payload dict that contains a "password" key has
that key removed before serialisation.  Callers do not need to remember
to strip it — the logger enforces this unconditionally.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any


_REDACTED_KEYS = frozenset({"password", "passwd", "pwd"})


def _redact(payload: Any) -> Any:
    """Return a copy of payload with password-like keys removed (one level deep)."""
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items() if k.lower() not in _REDACTED_KEYS}
    return payload


class ActivityLogger:
    """
    Appends one JSON object per line to a log file.

    Parameters
    ----------
    log_path
        Path to the log file.  Parent directory must exist.
        Comes from LoggingConfig — never hardcoded by callers.
    """

    def __init__(self, log_path: str) -> None:
        self._log_path = log_path
        # Ensure the parent directory exists.
        parent = os.path.dirname(os.path.abspath(log_path))
        os.makedirs(parent, exist_ok=True)

    # ── public API ────────────────────────────────────────────────────────────

    async def log(
        self,
        event_type: str,
        payload: Any = None,
        *,
        game_id: str | None = None,
    ) -> None:
        """
        Append one JSON line.  Runs the file write in a thread so the
        event loop is never blocked.
        """
        record = self._build_record(event_type, payload, game_id=game_id)
        line = json.dumps(record, default=str) + "\n"
        await asyncio.to_thread(self._write, line)

    # ── sync helpers (called only from worker threads) ────────────────────────

    def _build_record(
        self,
        event_type: str,
        payload: Any,
        *,
        game_id: str | None,
    ) -> dict:
        record: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
        }
        if game_id is not None:
            record["game_id"] = game_id
        if payload is not None:
            record["payload"] = _redact(payload)
        return record

    def _write(self, line: str) -> None:
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
