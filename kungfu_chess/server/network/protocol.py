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
from kungfu_chess.server.auth.constants import PASSWORD_MAX_LEN, USERNAME_MAX_LEN

# ── command-name constants ────────────────────────────────────────────────────
CMD_MOVE: Final = "move"
CMD_JUMP: Final = "jump"
CMD_JOIN: Final = "join"
CMD_LOGIN:    Final = "login"
CMD_REGISTER: Final = "register"

# ── server→client message type constants ─────────────────────────────────────
MSG_ASSIGNED:   Final = "assigned"
MSG_JOINED:     Final = "joined"
MSG_SNAPSHOT:   Final = "snapshot"
MSG_ERROR:      Final = "error"
MSG_LOGGED_IN:  Final = "logged_in"
MSG_REGISTERED: Final = "registered"

_KNOWN_COMMANDS: frozenset[str] = frozenset({CMD_MOVE, CMD_JUMP, CMD_JOIN, CMD_LOGIN, CMD_REGISTER})

_USERNAME_MAX_LEN = USERNAME_MAX_LEN
_PASSWORD_MAX_LEN = PASSWORD_MAX_LEN


# ── typed command structures ──────────────────────────────────────────────────
@dataclass(frozen=True)
class MoveCommand:
    from_pos: Position
    to_pos: Position


@dataclass(frozen=True)
class JumpCommand:
    pos: Position


@dataclass(frozen=True)
class JoinCommand:
    username: str


@dataclass(frozen=True)
class LoginCommand:
    username: str
    password: str


@dataclass(frozen=True)
class RegisterCommand:
    username: str
    password: str


@dataclass(frozen=True)
class ProtocolError:
    reason: str


Command = Union[MoveCommand, JumpCommand, JoinCommand, LoginCommand, RegisterCommand]
ParseResult = Union[Command, ProtocolError]


# ── parser ────────────────────────────────────────────────────────────────────
def _parse_username(raw: object) -> str | ProtocolError:
    if not isinstance(raw, str) or not raw.strip():
        return ProtocolError("'username' must be a non-empty string")
    if len(raw) > _USERNAME_MAX_LEN:
        return ProtocolError(f"'username' must be at most {_USERNAME_MAX_LEN} characters")
    return raw.strip()


def _parse_password(raw: object) -> str | ProtocolError:
    if not isinstance(raw, str) or not raw:
        return ProtocolError("'password' must be a non-empty string")
    if len(raw) > _PASSWORD_MAX_LEN:
        return ProtocolError(f"'password' must be at most {_PASSWORD_MAX_LEN} characters")
    return raw


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

    if cmd == CMD_JUMP:
        pos = _parse_pos(data.get("pos"), "pos")
        if isinstance(pos, ProtocolError):
            return pos
        return JumpCommand(pos=pos)

    # CMD_JOIN
    if cmd == CMD_JOIN:
        username = _parse_username(data.get("username"))
        if isinstance(username, ProtocolError):
            return username
        return JoinCommand(username=username)

    if cmd == CMD_LOGIN:
        username = _parse_username(data.get("username"))
        if isinstance(username, ProtocolError):
            return username
        password = _parse_password(data.get("password"))
        if isinstance(password, ProtocolError):
            return password
        return LoginCommand(username=username, password=password)

    # CMD_REGISTER
    username = _parse_username(data.get("username"))
    if isinstance(username, ProtocolError):
        return username
    password = _parse_password(data.get("password"))
    if isinstance(password, ProtocolError):
        return password
    return RegisterCommand(username=username, password=password)
