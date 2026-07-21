"""
Shared serialization helpers for server → client wire messages.
Imported by connection_router.py and tick_loop.py — defined once here.
"""
from __future__ import annotations
import dataclasses
import json
from typing import Any

from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.server.network.protocol import MSG_SNAPSHOT


def snapshot_to_json(snapshot: GameSnapshot) -> str:
    """Serialise a GameSnapshot to a JSON wire string."""
    return json.dumps({"type": MSG_SNAPSHOT, "data": _convert(snapshot)})


def _convert(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _convert(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k.value) if hasattr(k, "value") else str(k): _convert(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert(i) for i in obj]
    if hasattr(obj, "value"):   # Enum
        return obj.value
    return obj
