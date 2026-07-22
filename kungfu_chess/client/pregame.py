"""
Pre-game client flow: login/register → menu → room or matchmaking.

All I/O is injected (read_line, write_line, ws) so every function is
testable with real WebSocket objects and fake stdio — no mock.patch needed.

SRP: this module knows the pre-game protocol sequence only.
     ws_client.py stays protocol-primitive (connect_and_join).
     shell_login.py stays username-prompt only.
     No rendering, no move logic.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from kungfu_chess.server.network.protocol import (
    CMD_LOGIN, CMD_REGISTER,
    CMD_FIND_MATCH, CMD_CANCEL_MATCH,
    CMD_CREATE_ROOM, CMD_JOIN_ROOM,
    MSG_LOGGED_IN, MSG_REGISTERED, MSG_ERROR,
    MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ASSIGNED,
)

logger = logging.getLogger(__name__)

# Type aliases
WS        = Any
WriteFn   = Callable[[str], None]
ReadFn    = Callable[[], str]

# Menu choices — kept as module-level constants so tests can reference them
# without hardcoding strings.
MENU_PLAY = "1"
MENU_ROOM = "2"
MENU_QUIT = "q"

AUTH_LOGIN    = "1"
AUTH_REGISTER = "2"


# ── credential prompting ──────────────────────────────────────────────────────

def prompt_credentials(
    *,
    read: ReadFn = input,
    write: WriteFn = print,
    getpass_fn: Callable[[str], str] | None = None,
) -> tuple[str, str, bool]:
    """
    Interactively ask for username, login-vs-register choice, and password.

    Returns (username, password, register) where ``register`` is True when
    the user chose CMD_REGISTER.

    All I/O is injected so this function is testable without touching real
    stdin/stdout/getpass.  In production, pass no arguments and the real
    system calls are used.

    Parameters
    ----------
    read
        Callable that returns one line of input (default: ``input``).
    write
        Callable that prints one line (default: ``print``).
    getpass_fn
        Callable(prompt) -> str for masked password input
        (default: ``getpass.getpass``).
    """
    import getpass as _getpass
    if getpass_fn is None:
        getpass_fn = _getpass.getpass

    from kungfu_chess.client.shell_login import prompt_username
    write("Username: ")
    username = prompt_username(read_line=read)

    write(f"[{AUTH_LOGIN}] Login  [{AUTH_REGISTER}] Register")
    auth_choice = read().strip()
    register = (auth_choice == AUTH_REGISTER)

    password = getpass_fn("Password: ")
    return username, password, register


# ── low-level helpers ─────────────────────────────────────────────────────────

async def _recv_until(ws: WS, *expected_types: str, timeout_s: float = 10.0) -> dict:
    """
    Read messages from ws until one whose 'type' is in expected_types arrives.
    Raises RuntimeError on timeout or connection close.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise RuntimeError(
                f"Timed out waiting for {expected_types!r}"
            )
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        if msg.get("type") in expected_types:
            return msg


# ── login / register ──────────────────────────────────────────────────────────

async def login_or_register(
    ws: WS,
    username: str,
    password: str,
    *,
    register: bool = False,
    write: WriteFn = print,
) -> bool:
    """
    Send CMD_LOGIN or CMD_REGISTER and wait for the server's response.

    Returns True on success, False on failure (wrong password, duplicate
    username, etc.).  Writes a human-readable message via ``write``.
    """
    cmd = CMD_REGISTER if register else CMD_LOGIN
    await ws.send(json.dumps({"cmd": cmd, "username": username, "password": password}))

    expected = (MSG_LOGGED_IN, MSG_REGISTERED, MSG_ERROR)
    msg = await _recv_until(ws, *expected)

    if msg["type"] in (MSG_LOGGED_IN, MSG_REGISTERED):
        action = "Registered" if register else "Logged in"
        elo_part = f"  ELO: {msg['elo']}" if "elo" in msg else ""
        write(f"{action} as {msg.get('username', username)!r}.{elo_part}")
        logger.info("%s as %r (elo=%s)", action, msg.get('username', username),
                    msg.get('elo', 'n/a'))
        return True

    # MSG_ERROR
    write(f"Error: {msg.get('reason', 'unknown error')}")
    logger.warning("Auth failed for %r: %s", username, msg.get('reason', 'unknown error'))
    return False


# ── matchmaking ───────────────────────────────────────────────────────────────

async def find_match_flow(
    ws: WS,
    *,
    write: WriteFn = print,
    cancel_event: asyncio.Event | None = None,
    recv_timeout_s: float = 120.0,
) -> dict | None:
    """
    Send CMD_FIND_MATCH and wait for MSG_MATCH_FOUND or MSG_MATCH_TIMEOUT.

    If ``cancel_event`` is set before a result arrives, sends CMD_CANCEL_MATCH
    and returns None.

    Returns the MSG_MATCH_FOUND payload dict on success, None on timeout or
    cancel.
    """
    await ws.send(json.dumps({"cmd": CMD_FIND_MATCH}))
    write("Searching for an opponent… (press Enter to cancel)")

    if cancel_event is None:
        cancel_event = asyncio.Event()

    async def _wait_for_match() -> dict | None:
        return await _recv_until(
            ws, MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
            timeout_s=recv_timeout_s,
        )

    async def _wait_for_cancel() -> None:
        await cancel_event.wait()

    match_task  = asyncio.ensure_future(_wait_for_match())
    cancel_task = asyncio.ensure_future(_wait_for_cancel())

    done, pending = await asyncio.wait(
        {match_task, cancel_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    for t in pending:
        t.cancel()
        await asyncio.gather(t, return_exceptions=True)

    if cancel_task in done:
        await ws.send(json.dumps({"cmd": CMD_CANCEL_MATCH}))
        write("Match search cancelled.")
        return None

    # match_task finished
    try:
        msg = match_task.result()
    except Exception:
        return None

    if msg["type"] == MSG_MATCH_FOUND:
        write(
            f"Match found!  Room: {msg['room_id']!r}  "
            f"Opponent: {msg.get('opponent', '?')!r}"
        )
        logger.info("Match found — room=%r opponent=%r",
                    msg['room_id'], msg.get('opponent', '?'))
        return msg

    # MSG_MATCH_TIMEOUT
    write("No opponent found — match timed out.")
    logger.info("Match search timed out")
    return None


# ── room flow ─────────────────────────────────────────────────────────────────

async def room_flow(
    ws: WS,
    username: str,
    *,
    read: ReadFn = input,
    write: WriteFn = print,
) -> tuple[str, str, str | None] | None:
    """
    Prompt for an optional room ID, then join (or create) a room on the
    *existing* ws connection.  Returns (room_id, role, color) or None on error.

    Reuses the same WebSocket so the caller never needs a second connection.
    """
    write("Enter a room ID to join, or leave blank to create a new room:")
    raw = read().strip()
    room_id_hint = raw or None

    try:
        if room_id_hint is None:
            await ws.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
            created = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            if created.get("type") != MSG_ROOM_CREATED:
                write(f"Could not create room: {created}")
                return None
            room_id = created["room_id"]
        else:
            room_id = room_id_hint

        await ws.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": username}))
        joined = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
        if joined.get("type") != MSG_ROOM_JOINED:
            write(f"Could not join room: {joined}")
            return None

        role = joined["role"]
        color: str | None = None
        if role == "player":
            assigned = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
            if assigned.get("type") == MSG_ASSIGNED:
                color = assigned["color"]

        logger.info("Room joined — room=%r role=%s color=%s", room_id, role, color)
        return room_id, role, color

    except Exception as exc:
        write(f"Could not join room: {exc}")
        return None


# ── top-level pre-game menu ───────────────────────────────────────────────────

async def run_pregame(
    host: str,
    port: int,
    username: str,
    password: str,
    *,
    register: bool = False,
    read: ReadFn = input,
    write: WriteFn = print,
    cancel_match_event: asyncio.Event | None = None,
    recv_timeout_s: float = 120.0,
) -> tuple[WS, str, str, str | None] | None:
    """
    Full pre-game flow on a single WebSocket connection:
      1. Login or register.
      2. Show Play / Room menu.
      3. Return (ws, room_id, role, color) once a room is joined, or None.

    Injected ``read`` / ``write`` replace stdin/stdout so tests never touch
    real I/O.  ``cancel_match_event`` lets tests trigger CMD_CANCEL_MATCH
    programmatically.
    """
    uri = f"ws://{host}:{port}"
    import websockets
    ws = await websockets.connect(uri)

    # Step 1 — auth
    ok = await login_or_register(
        ws, username, password, register=register, write=write
    )
    if not ok:
        await ws.close()
        return None

    # Step 2 — menu loop
    while True:
        write(f"\n[{MENU_PLAY}] Play  [{MENU_ROOM}] Room  [{MENU_QUIT}] Quit")
        choice = read().strip().lower()

        if choice == MENU_QUIT:
            await ws.close()
            return None

        if choice == MENU_PLAY:
            result = await find_match_flow(
                ws,
                write=write,
                cancel_event=cancel_match_event,
                recv_timeout_s=recv_timeout_s,
            )
            if result is None:
                # Timed out or cancelled — loop back to menu
                continue
            # Matched: server already joined us to a room via _on_match;
            # drain the MSG_ROOM_JOINED + MSG_ASSIGNED that arrived before
            # MSG_MATCH_FOUND (see connection_router._on_match message order).
            room_id = result["room_id"]
            return ws, room_id, "player", None   # color already printed by server

        if choice == MENU_ROOM:
            result = await room_flow(ws, username, read=read, write=write)
            if result is not None:
                room_id, role, color = result
                return ws, room_id, role, color
            # Error already printed — loop back to menu
            continue

        write(f"Unknown choice {choice!r}. Please enter {MENU_PLAY}, {MENU_ROOM}, or {MENU_QUIT}.")
