"""
End-to-end tests for client/pregame.py.

Real ConnectionRouter + real websockets — no mocking, no patching.
Style mirrors test_ws_client.py / test_matchmaking_e2e.py.

Scenarios covered:
  1. login_or_register — success (login)
  2. login_or_register — failure (wrong password)
  3. login_or_register — success (register)
  4. find_match_flow   — MSG_MATCH_FOUND (two real clients)
  5. find_match_flow   — MSG_MATCH_TIMEOUT (short timeout config)
  6. find_match_flow   — cancel via cancel_event → CMD_CANCEL_MATCH
"""
from __future__ import annotations

import asyncio
import json
import unittest

import websockets

from kungfu_chess.client.pregame import (
    AUTH_LOGIN, AUTH_REGISTER,
    MENU_PLAY, MENU_ROOM, MENU_QUIT,
    find_match_flow,
    login_or_register,
    run_pregame,
)
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import (
    AuthConfig, MatchmakingConfig, RealtimeConfig,
    load_server_config as _load_cfg,
)
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_LOGIN,
    MSG_LOGGED_IN, MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
    MSG_ROOM_JOINED, MSG_ASSIGNED,
)
from kungfu_chess.server.session.game_session import GameSession

# ── shared test infrastructure ────────────────────────────────────────────────

_HOST = "localhost"
_BASE_PORT = 18790   # distinct from all other test files

_MINIMAL_BOARD = """\
. . . . bK . . .
. . . . bP . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . wP . . .
. . . . wK . . .
"""

_AUTH_CFG = AuthConfig(
    default_starting_elo=1200,
    elo_k_factor=32,
    sqlite_db_path=":memory:",
)

# Wide ELO range → always matches immediately in tests.
_MM_CFG_FAST = MatchmakingConfig(
    elo_range=500,
    elo_widen_step=50,
    widen_interval_ms=20,
    timeout_ms=5000,
)

# Zero ELO range + short timeout → never matches, times out quickly.
_MM_CFG_TIMEOUT = MatchmakingConfig(
    elo_range=0,
    elo_widen_step=0,
    widen_interval_ms=20,
    timeout_ms=150,
)

_RT_CFG = RealtimeConfig(
    tick_interval_ms=50,
    auto_resign_ms=_load_cfg().realtime.auto_resign_ms,
)


def _make_engine() -> GameEngine:
    board = BoardParser().parse(_MINIMAL_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_auth(*usernames_passwords: tuple[str, str]) -> AuthService:
    """Create an AuthService pre-populated with the given (username, password) pairs."""
    repo = InMemoryUserRepository()
    auth = AuthService(repo=repo, config=_AUTH_CFG)

    async def _register_all():
        for u, p in usernames_passwords:
            await auth.register(u, p)

    asyncio.run(_register_all())
    return auth


def _make_router(
    auth: AuthService | None = None,
    mm_cfg: MatchmakingConfig | None = None,
) -> ConnectionRouter:
    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), engine_factory=_make_engine),
        realtime_config=_RT_CFG,
        auth_service=auth,
        matchmaking_config=mm_cfg,
    )


class _Capture:
    """Collects write() calls so tests can assert on printed output."""
    def __init__(self):
        self.lines: list[str] = []

    def __call__(self, msg: str) -> None:
        self.lines.append(msg)

    def joined(self) -> str:
        return "\n".join(self.lines)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _drain_until(ws, msg_type: str, limit: int = 15) -> dict:
    for _ in range(limit):
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(raw)
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"Did not receive {msg_type!r} within {limit} messages")


# ── Test 1 & 2 & 3: login_or_register ────────────────────────────────────────

class TestLoginOrRegister(unittest.TestCase):

    def test_login_success(self):
        """Correct credentials → returns True, prints logged-in message."""
        auth = _make_auth(("alice", "secret"))
        router = _make_router(auth=auth)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT):
                ws = await websockets.connect(f"ws://{_HOST}:{_BASE_PORT}")
                ok = await login_or_register(ws, "alice", "secret", write=out)
                await ws.close()
                return ok

        ok = asyncio.run(_run())
        self.assertTrue(ok)
        self.assertTrue(any("alice" in line for line in out.lines))

    def test_login_wrong_password(self):
        """Wrong password → returns False, prints error message."""
        auth = _make_auth(("alice", "secret"))
        router = _make_router(auth=auth)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 1):
                ws = await websockets.connect(f"ws://{_HOST}:{_BASE_PORT + 1}")
                ok = await login_or_register(ws, "alice", "wrong", write=out)
                await ws.close()
                return ok

        ok = asyncio.run(_run())
        self.assertFalse(ok)
        self.assertTrue(any("Error" in line or "error" in line for line in out.lines))

    def test_register_success(self):
        """New user registers → returns True, prints registered message."""
        auth = _make_auth()   # empty repo
        router = _make_router(auth=auth)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 2):
                ws = await websockets.connect(f"ws://{_HOST}:{_BASE_PORT + 2}")
                ok = await login_or_register(
                    ws, "newuser", "pass123", register=True, write=out
                )
                await ws.close()
                return ok

        ok = asyncio.run(_run())
        self.assertTrue(ok)
        self.assertTrue(any("newuser" in line or "Registered" in line for line in out.lines))

    def test_login_unknown_user_returns_false(self):
        """Login for a username that was never registered → returns False."""
        auth = _make_auth()
        router = _make_router(auth=auth)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 3):
                ws = await websockets.connect(f"ws://{_HOST}:{_BASE_PORT + 3}")
                ok = await login_or_register(ws, "ghost", "pw", write=out)
                await ws.close()
                return ok

        ok = asyncio.run(_run())
        self.assertFalse(ok)


# ── Test 4: find_match → MSG_MATCH_FOUND ─────────────────────────────────────

class TestFindMatchFound(unittest.TestCase):

    def test_two_players_get_matched(self):
        """
        Two logged-in clients both call find_match_flow → both receive
        MSG_MATCH_FOUND with the same room_id.
        """
        auth = _make_auth(("alice", "pw"), ("bob", "pw"))
        router = _make_router(auth=auth, mm_cfg=_MM_CFG_FAST)
        out1, out2 = _Capture(), _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 4):
                uri = f"ws://{_HOST}:{_BASE_PORT + 4}"
                ws1 = await websockets.connect(uri)
                ws2 = await websockets.connect(uri)

                # Login both
                await ws1.send(json.dumps({"cmd": CMD_LOGIN, "username": "alice", "password": "pw"}))
                await _drain_until(ws1, MSG_LOGGED_IN)
                await ws2.send(json.dumps({"cmd": CMD_LOGIN, "username": "bob", "password": "pw"}))
                await _drain_until(ws2, MSG_LOGGED_IN)

                # Both search concurrently
                result1, result2 = await asyncio.gather(
                    find_match_flow(ws1, write=out1, recv_timeout_s=5.0),
                    find_match_flow(ws2, write=out2, recv_timeout_s=5.0),
                )

                await ws1.close()
                await ws2.close()
                return result1, result2

        r1, r2 = asyncio.run(_run())

        self.assertIsNotNone(r1, "alice did not receive match_found")
        self.assertIsNotNone(r2, "bob did not receive match_found")
        self.assertEqual(r1["room_id"], r2["room_id"])
        self.assertTrue(any("Match found" in line for line in out1.lines))
        self.assertTrue(any("Match found" in line for line in out2.lines))


# ── Test 5: find_match → MSG_MATCH_TIMEOUT ───────────────────────────────────

class TestFindMatchTimeout(unittest.TestCase):

    def test_unmatched_player_gets_timeout(self):
        """
        A single player searching with a short-timeout config receives
        MSG_MATCH_TIMEOUT; find_match_flow returns None and prints a message.
        """
        auth = _make_auth(("carol", "pw"))
        router = _make_router(auth=auth, mm_cfg=_MM_CFG_TIMEOUT)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 5):
                uri = f"ws://{_HOST}:{_BASE_PORT + 5}"
                ws = await websockets.connect(uri)

                await ws.send(json.dumps({"cmd": CMD_LOGIN, "username": "carol", "password": "pw"}))
                await _drain_until(ws, MSG_LOGGED_IN)

                result = await find_match_flow(ws, write=out, recv_timeout_s=2.0)
                await ws.close()
                return result

        result = asyncio.run(_run())
        self.assertIsNone(result)
        self.assertTrue(any("timed out" in line.lower() for line in out.lines))


# ── Test 6: cancel_match ──────────────────────────────────────────────────────

class TestCancelMatch(unittest.TestCase):

    def test_cancel_event_stops_search(self):
        """
        Setting cancel_event while find_match_flow is waiting causes it to
        send CMD_CANCEL_MATCH and return None immediately.
        """
        auth = _make_auth(("dave", "pw"))
        router = _make_router(auth=auth, mm_cfg=_MM_CFG_FAST)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 6):
                uri = f"ws://{_HOST}:{_BASE_PORT + 6}"
                ws = await websockets.connect(uri)

                await ws.send(json.dumps({"cmd": CMD_LOGIN, "username": "dave", "password": "pw"}))
                await _drain_until(ws, MSG_LOGGED_IN)

                cancel = asyncio.Event()

                async def _trigger_cancel():
                    await asyncio.sleep(0.05)   # let find_match_flow start
                    cancel.set()

                result, _ = await asyncio.gather(
                    find_match_flow(ws, write=out, cancel_event=cancel, recv_timeout_s=5.0),
                    _trigger_cancel(),
                )
                await ws.close()
                return result

        result = asyncio.run(_run())
        self.assertIsNone(result)
        self.assertTrue(any("cancel" in line.lower() for line in out.lines))


# ── Test 7: run_pregame — room path ──────────────────────────────────────────

class TestRunPregameRoomPath(unittest.TestCase):

    def test_room_path_returns_ws_and_room_id(self):
        """
        Choosing MENU_ROOM in run_pregame creates a room and returns
        (ws, room_id, role, color).
        """
        auth = _make_auth(("eve", "pw"))
        router = _make_router(auth=auth)

        # run_pregame takes register= as a param, so read() is only called
        # for the menu — first read() is the menu choice, second is room_id.
        inputs = iter([MENU_ROOM, ""])
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 7):
                result = await run_pregame(
                    _HOST, _BASE_PORT + 7,
                    "eve", "pw",
                    register=False,
                    read=lambda: next(inputs),
                    write=out,
                )
                if result:
                    ws, room_id, role, color = result
                    router.cancel_room(room_id)
                    await ws.close()
                return result

        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        ws, room_id, role, color = result
        self.assertTrue(len(room_id) > 0)
        self.assertEqual(role, "player")

    def test_bad_login_returns_none(self):
        """Wrong password in run_pregame → returns None without entering menu."""
        auth = _make_auth(("frank", "correct"))
        router = _make_router(auth=auth)
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 8):
                result = await run_pregame(
                    _HOST, _BASE_PORT + 8,
                    "frank", "wrong",
                    register=False,
                    read=lambda: "",
                    write=out,
                )
                return result

        result = asyncio.run(_run())
        self.assertIsNone(result)

    def test_quit_choice_returns_none(self):
        """Choosing MENU_QUIT in the menu → returns None cleanly."""
        auth = _make_auth(("grace", "pw"))
        router = _make_router(auth=auth)

        inputs = iter([MENU_QUIT])
        out = _Capture()

        async def _run():
            async with websockets.serve(router.handle, _HOST, _BASE_PORT + 9):
                result = await run_pregame(
                    _HOST, _BASE_PORT + 9,
                    "grace", "pw",
                    register=False,
                    read=lambda: next(inputs),
                    write=out,
                )
                return result

        result = asyncio.run(_run())
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
