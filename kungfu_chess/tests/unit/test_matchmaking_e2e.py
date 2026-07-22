"""
End-to-end matchmaking + disconnect/auto-resign tests.
Real ConnectionRouter + real websockets — no mocking, no patching.
Style mirrors test_handshake_e2e.py.
"""
from __future__ import annotations
import asyncio
import json
import unittest

import websockets

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import AuthConfig, MatchmakingConfig, RealtimeConfig
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_LOGIN, CMD_FIND_MATCH, CMD_JOIN_ROOM,
    MSG_LOGGED_IN, MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT, MSG_ROOM_JOINED, MSG_ASSIGNED,
)
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18780

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

_AUTH_CFG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")
_MM_CFG = MatchmakingConfig(
    elo_range=500,          # wide — always matches in tests
    elo_widen_step=50,
    widen_interval_ms=20,   # fast ticks
    timeout_ms=5000,
)
_RT_CFG = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=200)  # short for tests
_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def _make_engine() -> GameEngine:
    board = BoardParser().parse(_MINIMAL_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_router(auth: AuthService) -> ConnectionRouter:
    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
        realtime_config=_RT_CFG,
        auth_service=auth,
        matchmaking_config=_MM_CFG,
    )


async def _login(ws, username: str, password: str) -> None:
    await ws.send(json.dumps({"cmd": CMD_LOGIN, "username": username, "password": password}))
    msg = json.loads(await ws.recv())
    assert msg["type"] == MSG_LOGGED_IN, f"Expected logged_in, got {msg}"


async def _drain_until(ws, msg_type: str, limit: int = 10) -> dict:
    """Read messages until one with the given type is found."""
    for _ in range(limit):
        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
        msg = json.loads(raw)
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"Did not receive {msg_type!r} within {limit} messages")


class TestMatchmakingEndToEnd(unittest.TestCase):

    def test_two_logged_in_players_get_matched_into_same_room(self):
        """Two logged-in connections both send find_match → same room, opposite colors."""
        async def _run():
            repo = InMemoryUserRepository()
            auth = AuthService(repo=repo, config=_AUTH_CFG)
            await auth.register("alice", "pw")
            await auth.register("bob", "pw")
            router = _make_router(auth)

            async with websockets.serve(router.handle, _HOST, _PORT):
                uri = f"ws://{_HOST}:{_PORT}"
                ws1 = await websockets.connect(uri)
                ws2 = await websockets.connect(uri)

                await _login(ws1, "alice", "pw")
                await _login(ws2, "bob", "pw")

                await ws1.send(json.dumps({"cmd": CMD_FIND_MATCH}))
                await ws2.send(json.dumps({"cmd": CMD_FIND_MATCH}))

                # _on_match sends: MSG_ROOM_JOINED, MSG_ASSIGNED, then MSG_MATCH_FOUND
                joined1 = await _drain_until(ws1, MSG_ROOM_JOINED)
                joined2 = await _drain_until(ws2, MSG_ROOM_JOINED)
                self.assertEqual(joined1["role"], "player")
                self.assertEqual(joined2["role"], "player")

                color1 = (await _drain_until(ws1, MSG_ASSIGNED))["color"]
                color2 = (await _drain_until(ws2, MSG_ASSIGNED))["color"]
                self.assertNotEqual(color1, color2)
                self.assertIn(color1, ("w", "b"))
                self.assertIn(color2, ("w", "b"))

                found1 = await _drain_until(ws1, MSG_MATCH_FOUND)
                found2 = await _drain_until(ws2, MSG_MATCH_FOUND)
                self.assertEqual(found1["room_id"], found2["room_id"])

                await ws1.close()
                await ws2.close()

        asyncio.run(_run())

    def test_reconnect_within_window_does_not_trigger_resign(self):
        """Player disconnects and reconnects before auto_resign_ms — no resign fires."""
        async def _run():
            repo = InMemoryUserRepository()
            auth = AuthService(repo=repo, config=_AUTH_CFG)
            await auth.register("alice", "pw")
            await auth.register("bob", "pw")
            router = _make_router(auth)

            async with websockets.serve(router.handle, _HOST, _PORT + 1):
                uri = f"ws://{_HOST}:{_PORT + 1}"

                # Both join a room manually (no matchmaking needed here)
                ws1 = await websockets.connect(uri)
                ws2 = await websockets.connect(uri)
                await ws1.send(json.dumps({"cmd": "create_room"}))
                room_msg = json.loads(await ws1.recv())
                rid = room_msg["room_id"]

                await ws1.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": rid, "username": "alice"}))
                await _drain_until(ws1, MSG_ASSIGNED)

                await ws2.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": rid, "username": "bob"}))
                await _drain_until(ws2, MSG_ASSIGNED)

                # alice disconnects
                await ws1.close()
                await asyncio.sleep(0.05)   # well within auto_resign_ms=200

                # alice reconnects before the timer fires
                ws1b = await websockets.connect(uri)
                await ws1b.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": rid, "username": "alice"}))
                rejoined = await _drain_until(ws1b, MSG_ROOM_JOINED)
                self.assertEqual(rejoined["role"], "player")

                # wait past original auto_resign window — no GAME_ENDED should arrive
                await asyncio.sleep(0.25)

                # bob's socket should still be open (no game-ended broadcast)
                session = router.session_for(rid)
                self.assertIsNotNone(session)

                await ws1b.close()
                await ws2.close()

        asyncio.run(_run())

    def test_no_reconnect_triggers_auto_resign(self):
        """Player disconnects and does not reconnect — resign fires, GAME_ENDED published."""
        async def _run():
            repo = InMemoryUserRepository()
            auth = AuthService(repo=repo, config=_AUTH_CFG)
            await auth.register("alice", "pw")
            await auth.register("bob", "pw")
            router = _make_router(auth)

            game_ended_events: list[dict] = []

            async with websockets.serve(router.handle, _HOST, _PORT + 2):
                uri = f"ws://{_HOST}:{_PORT + 2}"

                ws1 = await websockets.connect(uri)
                ws2 = await websockets.connect(uri)
                await ws1.send(json.dumps({"cmd": "create_room"}))
                rid = json.loads(await ws1.recv())["room_id"]

                await ws1.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": rid, "username": "alice"}))
                await _drain_until(ws1, MSG_ASSIGNED)

                await ws2.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": rid, "username": "bob"}))
                await _drain_until(ws2, MSG_ASSIGNED)

                # Subscribe to GAME_ENDED on the session bus
                session = router.session_for(rid)
                from kungfu_chess.server.bus import topics
                session._bus.subscribe(
                    topics.GAME_ENDED,
                    lambda p: game_ended_events.append(p),
                )

                # alice disconnects and never comes back
                await ws1.close()

                # wait past auto_resign_ms=200
                await asyncio.sleep(0.35)

                self.assertEqual(len(game_ended_events), 1)
                evt = game_ended_events[0]
                self.assertEqual(evt["loser"], "alice")
                self.assertEqual(evt["winner"], "bob")

                await ws2.close()

        asyncio.run(_run())


# Config with a very short timeout so the e2e timeout test doesn't wait 60 s.
_MM_CFG_SHORT_TIMEOUT = MatchmakingConfig(
    elo_range=0,            # never matches (ELO gap always > 0 unless identical)
    elo_widen_step=0,       # window never widens
    widen_interval_ms=20,   # fast ticks
    timeout_ms=150,         # times out after 150 ms
)


class TestMatchmakingTimeout(unittest.TestCase):

    def test_unmatched_player_receives_timeout_message(self):
        """
        A player who sends find_match but is never paired receives
        MSG_MATCH_TIMEOUT after matchmaking.timeout_ms.
        Uses a short timeout config — no real 60 s wait.
        """
        async def _run():
            repo = InMemoryUserRepository()
            auth = AuthService(repo=repo, config=_AUTH_CFG)
            await auth.register("carol", "pw")
            router = ConnectionRouter(
                session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
                realtime_config=_RT_CFG,
                auth_service=auth,
                matchmaking_config=_MM_CFG_SHORT_TIMEOUT,
            )

            async with websockets.serve(router.handle, _HOST, _PORT + 3):
                uri = f"ws://{_HOST}:{_PORT + 3}"
                ws = await websockets.connect(uri)

                await _login(ws, "carol", "pw")
                await ws.send(json.dumps({"cmd": CMD_FIND_MATCH}))

                # Wait for MSG_MATCH_TIMEOUT — should arrive within ~300 ms
                msg = await _drain_until(ws, MSG_MATCH_TIMEOUT, limit=20)
                self.assertEqual(msg["type"], MSG_MATCH_TIMEOUT)

                await ws.close()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main(verbosity=2)
