"""
ClientActivityLogger — JSON-lines sink for client-side structured logging.

Mirrors the server-side ActivityLogger: one JSON object per line, no
plaintext passwords, async writes via asyncio.to_thread.

SRP: this class only serialises and appends; it does not know about
WebSockets, rendering, or game rules.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

_REDACTED_KEYS = frozenset({"password", "passwd", "pwd"})


def _redact(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items() if k.lower() not in _REDACTED_KEYS}
    return payload


class ClientActivityLogger:
    """
    Appends one JSON object per line to a log file.

    Parameters
    ----------
    log_path
        Path to the log file.  Comes from GameConfig.client_log_path —
        never hardcoded by callers.
    """

    def __init__(self, log_path: str) -> None:
        self._log_path = log_path
        parent = os.path.dirname(os.path.abspath(log_path))
        os.makedirs(parent, exist_ok=True)

    async def log(self, event_type: str, payload: Any = None) -> None:
        """Append one JSON line without blocking the event loop."""
        record: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
        }
        if payload is not None:
            record["payload"] = _redact(payload)
        line = json.dumps(record, default=str) + "\n"
        await asyncio.to_thread(self._write, line)

    def _write(self, line: str) -> None:
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
