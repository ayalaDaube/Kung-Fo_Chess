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

async def _read_line(read: ReadFn) -> str:
    """
    Run a (possibly blocking) read callable — typically ``input`` waiting on
    a real keypress — off the event loop thread.

    BUG FIX: calling ``read()`` directly from inside an async function
    blocks the *entire* asyncio event loop for as long as the user takes to
    respond. While blocked, the client cannot process the WebSocket
    connection at all — including replying to the server's keepalive pings.
    If the user takes longer than the ping timeout (default 20s, e.g. two
    players coordinating before both press a key), the server drops the
    connection. The next ``ws.send``/``ws.recv`` then raises
    ``ConnectionClosedError: no close frame received`` — this is the exact
    bug reported with two players joining, and with "Join Room" seeming to
    silently do nothing.

    Running the read in a worker thread via ``asyncio.to_thread`` keeps the
    event loop free to answer pings while we wait for the user.
    """
    return await asyncio.to_thread(read)


class ServerError(RuntimeError):
    """Raised by _recv_until when the server sends MSG_ERROR."""
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _recv_until(
    ws: WS, *expected_types: str, timeout_s: float = 10.0,
    on_other: Callable[[dict], None] | None = None,
) -> dict:
    """
    Read messages from ws until one whose 'type' is in expected_types arrives.
    Raises ServerError immediately if MSG_ERROR arrives and is not in expected_types.
    Raises RuntimeError on timeout or connection close.

    ``on_other``, if given, is called with every message that is skipped
    while waiting (neither an expected type nor MSG_ERROR) — lets a caller
    observe intervening messages (e.g. MSG_ASSIGNED while waiting for
    MSG_MATCH_FOUND) without consuming them.
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
        msg_type = msg.get("type")
        if msg_type in expected_types:
            return msg
        if msg_type == MSG_ERROR and MSG_ERROR not in expected_types:
            raise ServerError(msg.get("reason", "unknown error"))
        if on_other is not None:
            on_other(msg)


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

    try:
        msg = await _recv_until(ws, MSG_LOGGED_IN, MSG_REGISTERED)
    except ServerError as exc:
        write(f"Error: {exc.reason}")
        logger.warning("Auth failed for %r: %s", username, exc.reason)
        return False

    if msg["type"] == MSG_REGISTERED:
        # Registration succeeded — server has already marked the connection as
        # logged in (Bug A fix), but we still need MSG_LOGGED_IN on the wire
        # so the client knows the ELO.  Send CMD_LOGIN immediately.
        logger.info("Registered as %r, auto-logging in", msg.get('username', username))
        await ws.send(json.dumps({"cmd": CMD_LOGIN, "username": username, "password": password}))
        try:
            msg = await _recv_until(ws, MSG_LOGGED_IN)
        except ServerError as exc:
            write(f"Error: {exc.reason}")
            return False

    # MSG_LOGGED_IN
    elo_part = f"  ELO: {msg['elo']}" if "elo" in msg else ""
    write(f"Logged in as {msg.get('username', username)!r}.{elo_part}")
    logger.info("Logged in as %r (elo=%s)", msg.get('username', username), msg.get('elo', 'n/a'))
    return True


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

    Returns the MSG_MATCH_FOUND payload dict on success (with a "color" key
    merged in from the MSG_ASSIGNED message the server sends just before
    MSG_MATCH_FOUND — previously discarded here, leaving the caller with no
    way to know which side it was assigned), None on timeout or cancel.
    """
    await ws.send(json.dumps({"cmd": CMD_FIND_MATCH}))
    write("Searching for an opponent… (press Enter to cancel)")

    if cancel_event is None:
        cancel_event = asyncio.Event()

    assigned_color: str | None = None

    def _capture_assigned(other_msg: dict) -> None:
        nonlocal assigned_color
        if other_msg.get("type") == MSG_ASSIGNED:
            assigned_color = other_msg.get("color")

    async def _wait_for_match() -> dict | None:
        try:
            return await _recv_until(
                ws, MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
                timeout_s=recv_timeout_s,
                on_other=_capture_assigned,
            )
        except ServerError as exc:
            write(f"Error: {exc.reason}")
            logger.warning("Match error: %s", exc.reason)
            return None

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

    if msg is None:
        return None

    if msg["type"] == MSG_MATCH_FOUND:
        write(
            f"Match found!  Room: {msg['room_id']!r}  "
            f"Opponent: {msg.get('opponent', '?')!r}"
        )
        logger.info("Match found — room=%r opponent=%r color=%s",
                    msg['room_id'], msg.get('opponent', '?'), assigned_color)
        return {**msg, "color": assigned_color}

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
    raw = (await _read_line(read)).strip()
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
    getpass_fn: Callable[[str], str] | None = None,
    cancel_match_event: asyncio.Event | None = None,
    recv_timeout_s: float = 120.0,
) -> tuple[WS, str, str, str | None] | None:
    """
    Full pre-game flow on a single WebSocket connection:
      1. Login or register, with retry on failure.
         An empty username at the re-prompt exits cleanly.
      2. Show Play / Room menu.
      3. Return (ws, room_id, role, color) once a room is joined, or None.

    ``username``, ``password``, ``register`` seed the first attempt.
    On failure the user is re-prompted via prompt_credentials().
    Injected ``read`` / ``write`` / ``getpass_fn`` replace stdin/stdout so
    tests never touch real I/O.
    """
    import websockets
    ws = await websockets.connect(f"ws://{host}:{port}")

    # Step 1 — auth with retry
    while True:
        ok = await login_or_register(
            ws, username, password, register=register, write=write
        )
        if ok:
            break
        # Auth failed — re-prompt; empty username or 'q' quits
        write("Enter empty username to quit, or try again.")
        raw_username = (await _read_line(read)).strip()
        if not raw_username or raw_username.lower() == MENU_QUIT:
            await ws.close()
            return None
        # Re-use prompt_credentials for auth-choice + password, seeding username
        # from what was just read so the user isn't asked twice.
        write(f"[{AUTH_LOGIN}] Login  [{AUTH_REGISTER}] Register")
        auth_choice = (await _read_line(read)).strip()
        register = (auth_choice == AUTH_REGISTER)
        import getpass as _getpass
        _gp = getpass_fn if getpass_fn is not None else _getpass.getpass
        password = await asyncio.to_thread(_gp, "Password: ")
        username = raw_username

    # Step 2 — menu loop
    while True:
        write(f"\n[{MENU_PLAY}] Play  [{MENU_ROOM}] Room  [{MENU_QUIT}] Quit")
        choice = (await _read_line(read)).strip().lower()

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
                continue
            room_id = result["room_id"]
            return ws, room_id, "player", result.get("color")

        if choice == MENU_ROOM:
            result = await room_flow(ws, username, read=read, write=write)
            if result is not None:
                room_id, role, color = result
                return ws, room_id, role, color
            continue

        write(f"Unknown choice {choice!r}. Please enter {MENU_PLAY}, {MENU_ROOM}, or {MENU_QUIT}.")
