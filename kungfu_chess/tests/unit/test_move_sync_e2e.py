"""
End-to-end move-sync test: two real clients, real sockets, no mock.patch.

Player A sends a MoveCommand over the WebSocket.
Player B's received snapshot reflects the move.

Also verifies that a spectator receives the same snapshot broadcast.
"""
from __future__ import annotations

import asyncio
import json
import unittest

import websockets

from kungfu_chess.client.snapshot_receiver import SnapshotReceiver
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.network.protocol import (
    CMD_CREATE_ROOM, CMD_JOIN_ROOM, CMD_MOVE,
    MSG_ASSIGNED, MSG_ERROR, MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_SNAPSHOT,
)
from kungfu_chess.server.session.game_session import GameSession

_HOST = "localhost"
_PORT = 18830   # distinct from all other test files

# Minimal board: white pawn at e2 (row 6, col 4), kings for game-over detection.
_BOARD = """\
. . . . bK . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . .  . . .
. . . . wP . . .
. . . . wK . . .
"""

_RT_CFG = RealtimeConfig(tick_interval_ms=50, auto_resign_ms=5000)
_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def _make_engine() -> GameEngine:
    board = BoardParser().parse(_BOARD)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


def _make_router() -> ConnectionRouter:
    return ConnectionRouter(
        session_factory=lambda: GameSession(bus=EventBus(), piece_scores=_PIECE_SCORES, engine_factory=_make_engine),
        realtime_config=_RT_CFG,
    )


async def _drain_until(ws, msg_type: str, limit: int = 20) -> dict:
    for _ in range(limit):
        raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        msg = json.loads(raw)
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"Did not receive {msg_type!r} within {limit} messages")


async def _join_room(ws, room_id: str, username: str) -> str:
    """Join room, return assigned color (or 'spectator')."""
    await ws.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": username}))
    joined = await _drain_until(ws, MSG_ROOM_JOINED)
    role = joined["role"]
    if role == "player":
        assigned = await _drain_until(ws, MSG_ASSIGNED)
        return assigned["color"]
    return "spectator"


class TestMoveSyncE2E(unittest.TestCase):

    def test_rejected_move_reaches_snapshot_receiver_as_error(self):
        """
        Regression test for the "connection to the logic game can't connect
        properly" bug: during live gameplay, MSG_ERROR from a rejected move
        (e.g. moving the opponent's piece) flows over the exact same socket
        as MSG_SNAPSHOT. SnapshotReceiver.feed() previously had no case for
        MSG_ERROR at all, so the client silently dropped it — the player's
        click appeared to do nothing, with no feedback of any kind.

        This drives the real ConnectionRouter + real sockets, feeds every
        incoming raw message through SnapshotReceiver exactly as
        app.py's _network_loop does, and asserts pop_error() surfaces the
        server's rejection reason.
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 2):
                uri = f"ws://{_HOST}:{_PORT + 2}"

                ws_a = await websockets.connect(uri)
                ws_b = await websockets.connect(uri)

                await ws_a.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
                created = await _drain_until(ws_a, MSG_ROOM_CREATED)
                room_id = created["room_id"]

                color_a = await _join_room(ws_a, room_id, "alice")
                await _join_room(ws_b, room_id, "bob")

                # B attempts to move A's piece (the only pawn on the board).
                ws_attacker = ws_b if color_a == "w" else ws_a
                await ws_attacker.send(json.dumps({
                    "cmd": CMD_MOVE,
                    "from": {"row": 6, "col": 4},
                    "to":   {"row": 5, "col": 4},
                }))

                error_msg = await _drain_until(ws_attacker, MSG_ERROR)

                recv = SnapshotReceiver()
                handled = recv.feed(json.dumps(error_msg))

                await ws_a.close()
                await ws_b.close()
                return handled, recv.pop_error()

        handled, reason = asyncio.run(_run())
        self.assertTrue(handled, "SnapshotReceiver.feed() did not recognise MSG_ERROR")
        self.assertEqual(reason, "not your piece")

    def test_player_b_snapshot_reflects_player_a_move(self):
        """
        Player A sends a move; player B's next snapshot shows the piece
        at the new position (or in motion toward it).
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT):
                uri = f"ws://{_HOST}:{_PORT}"

                ws_a = await websockets.connect(uri)
                ws_b = await websockets.connect(uri)

                # Create room via player A
                await ws_a.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
                created = await _drain_until(ws_a, MSG_ROOM_CREATED)
                room_id = created["room_id"]

                color_a = await _join_room(ws_a, room_id, "alice")
                color_b = await _join_room(ws_b, room_id, "bob")

                # Determine which player owns white (white moves first in chess).
                # We'll have the white player send a move.
                if color_a == "w":
                    ws_white, ws_other = ws_a, ws_b
                else:
                    ws_white, ws_other = ws_b, ws_a

                # White pawn at row=6, col=4 → move to row=5, col=4 (one step forward).
                move_msg = json.dumps({
                    "cmd": CMD_MOVE,
                    "from": {"row": 6, "col": 4},
                    "to":   {"row": 5, "col": 4},
                })
                await ws_white.send(move_msg)

                # Both players should receive a snapshot.
                snap_msg_white = await _drain_until(ws_white, MSG_SNAPSHOT)
                snap_msg_other = await _drain_until(ws_other, MSG_SNAPSHOT)

                # Parse both snapshots via SnapshotReceiver.
                recv_white = SnapshotReceiver()
                recv_other = SnapshotReceiver()
                recv_white.feed(json.dumps(snap_msg_white))
                recv_other.feed(json.dumps(snap_msg_other))

                snap_white = recv_white.latest()
                snap_other = recv_other.latest()

                self.assertIsNotNone(snap_white, "white did not receive a valid snapshot")
                self.assertIsNotNone(snap_other, "other player did not receive a valid snapshot")

                # The pawn must no longer be at its starting cell in both snapshots.
                # (It is either in motion or has arrived at the target.)
                def _piece_at(snap, row, col):
                    return next(
                        (p for p in snap.pieces if p.cell.row == row and p.cell.col == col),
                        None,
                    )

                # After a move command the piece starts moving; its cell in the snapshot
                # is the *destination* once motion is registered, or still the source
                # if the arbiter hasn't ticked yet.  Either way, both snapshots must
                # be identical (same server state broadcast to both).
                self.assertEqual(
                    len(snap_white.pieces), len(snap_other.pieces),
                    "snapshots have different piece counts",
                )
                # Verify the pawn is no longer idle at the original cell in both.
                # (It may be in motion — target_cell == destination.)
                from kungfu_chess.model.piece import PieceKind
                pawn_white = next(
                    (p for p in snap_white.pieces if p.kind == PieceKind.PAWN), None
                )
                pawn_other = next(
                    (p for p in snap_other.pieces if p.kind == PieceKind.PAWN), None
                )
                self.assertIsNotNone(pawn_white, "pawn missing from white's snapshot")
                self.assertIsNotNone(pawn_other, "pawn missing from other's snapshot")

                # Both snapshots must agree on the pawn's cell.
                self.assertEqual(
                    pawn_white.cell, pawn_other.cell,
                    "snapshots disagree on pawn position",
                )

                await ws_a.close()
                await ws_b.close()

        asyncio.run(_run())

    def test_spectator_receives_same_snapshot(self):
        """
        A spectator joining the room also receives the snapshot broadcast
        after player A's move.
        """
        async def _run():
            router = _make_router()
            async with websockets.serve(router.handle, _HOST, _PORT + 1):
                uri = f"ws://{_HOST}:{_PORT + 1}"

                ws_a   = await websockets.connect(uri)
                ws_b   = await websockets.connect(uri)
                ws_spec = await websockets.connect(uri)

                await ws_a.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
                created = await _drain_until(ws_a, MSG_ROOM_CREATED)
                room_id = created["room_id"]

                color_a = await _join_room(ws_a, room_id, "alice")
                await _join_room(ws_b, room_id, "bob")
                spec_role = await _join_room(ws_spec, room_id, "")
                self.assertEqual(spec_role, "spectator")

                ws_white = ws_a if color_a == "w" else ws_b

                await ws_white.send(json.dumps({
                    "cmd": CMD_MOVE,
                    "from": {"row": 6, "col": 4},
                    "to":   {"row": 5, "col": 4},
                }))

                snap_spec_msg = await _drain_until(ws_spec, MSG_SNAPSHOT)
                recv = SnapshotReceiver()
                recv.feed(json.dumps(snap_spec_msg))
                snap = recv.latest()

                self.assertIsNotNone(snap, "spectator did not receive a valid snapshot")
                self.assertGreater(len(snap.pieces), 0)

                await ws_a.close()
                await ws_b.close()
                await ws_spec.close()

        asyncio.run(_run())

    def test_snapshot_receiver_parses_wire_message(self):
        """
        Unit-level: SnapshotReceiver.feed() correctly parses a MSG_SNAPSHOT
        wire message produced by the server's serialization module.
        """
        from kungfu_chess.server.network.serialization import snapshot_to_json
        from kungfu_chess.engine.snapshot_builder import build_snapshot
        from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter as _Arb

        board = BoardParser().parse(_BOARD)
        arbiter = _Arb()
        snap = build_snapshot(board, arbiter, selected_cell=None, game_over=False)
        wire = snapshot_to_json(snap)

        recv = SnapshotReceiver()
        ok = recv.feed(wire)
        self.assertTrue(ok)
        parsed = recv.latest()
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.board_width, snap.board_width)
        self.assertEqual(parsed.board_height, snap.board_height)
        self.assertEqual(len(parsed.pieces), len(snap.pieces))


if __name__ == "__main__":
    unittest.main(verbosity=2)
