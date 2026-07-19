"""
Single entry point for all client↔server message parsing.
Defines typed Command structures and validates untrusted input before
anything touches GameEngine. No other file does ad-hoc dict access on
incoming messages.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Final, Union

from kungfu_chess.model.position import Position

# ── command-name constants ────────────────────────────────────────────────────
CMD_MOVE: Final = "move"
CMD_JUMP: Final = "jump"

_KNOWN_COMMANDS: frozenset[str] = frozenset({CMD_MOVE, CMD_JUMP})


# ── typed command structures ──────────────────────────────────────────────────
@dataclass(frozen=True)
class MoveCommand:
    from_pos: Position
    to_pos: Position


@dataclass(frozen=True)
class JumpCommand:
    pos: Position


@dataclass(frozen=True)
class ProtocolError:
    reason: str


Command = Union[MoveCommand, JumpCommand]
ParseResult = Union[Command, ProtocolError]


# ── parser ────────────────────────────────────────────────────────────────────
def _parse_pos(raw: object, field: str) -> Position | ProtocolError:
    if not isinstance(raw, dict):
        return ProtocolError(f"'{field}' must be an object")
    row, col = raw.get("row"), raw.get("col")
    if not isinstance(row, int) or not isinstance(col, int):
        return ProtocolError(f"'{field}' must have integer 'row' and 'col'")
    return Position(row=row, col=col)


def parse_incoming_message(raw: str) -> ParseResult:
    """
    Validates and parses a raw JSON string from a client.
    Returns a typed Command on success, or ProtocolError describing the problem.
    This is the only place that touches untrusted input.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ProtocolError("message is not valid JSON")

    if not isinstance(data, dict):
        return ProtocolError("message must be a JSON object")

    cmd = data.get("cmd")
    if cmd not in _KNOWN_COMMANDS:
        return ProtocolError(f"unknown command: {cmd!r}")

    if cmd == CMD_MOVE:
        from_pos = _parse_pos(data.get("from"), "from")
        if isinstance(from_pos, ProtocolError):
            return from_pos
        to_pos = _parse_pos(data.get("to"), "to")
        if isinstance(to_pos, ProtocolError):
            return to_pos
        return MoveCommand(from_pos=from_pos, to_pos=to_pos)

    # CMD_JUMP
    pos = _parse_pos(data.get("pos"), "pos")
    if isinstance(pos, ProtocolError):
        return pos
    return JumpCommand(pos=pos)
