"""
Parses incoming MSG_SNAPSHOT wire messages and holds the latest GameSnapshot.

SRP: this module owns snapshot deserialization only.
     It knows the wire format (from server/network/serialization.py) but
     nothing about rendering, networking, or game rules.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot, MoveRecord
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.server.network.protocol import (
    MSG_SNAPSHOT, MSG_OPPONENT_DISCONNECTED, MSG_OPPONENT_RECONNECTED, MSG_ERROR,
)
from kungfu_chess.client.activity_logger import ClientActivityLogger

logger = logging.getLogger(__name__)


def _pos(d: dict | None) -> Optional[Position]:
    if d is None:
        return None
    return Position(row=d["row"], col=d["col"])


def _piece_snapshot(d: dict) -> PieceSnapshot:
    return PieceSnapshot(
        id=d["id"],
        kind=PieceKind(d["kind"]),
        color=PieceColor(d["color"]),
        cell=_pos(d["cell"]),
        state=PieceState(d["state"]),
        motion_progress=d.get("motion_progress", 1.0),
        target_cell=_pos(d.get("target_cell")),
    )


def _move_record(d: dict) -> MoveRecord:
    return MoveRecord(
        elapsed_ms=d["elapsed_ms"],
        notation=d["notation"],
        color=PieceColor(d["color"]),
    )


def parse_snapshot(data: dict) -> GameSnapshot:
    """
    Deserialise the ``data`` sub-dict from a MSG_SNAPSHOT wire message into
    a GameSnapshot.  Mirrors the structure produced by
    server/network/serialization.py's snapshot_to_json().
    """
    raw_scores = data.get("scores", {})
    scores = {PieceColor(k): v for k, v in raw_scores.items()}
    raw_winner = data.get("winner_color")

    return GameSnapshot(
        board_width=data["board_width"],
        board_height=data["board_height"],
        pieces=[_piece_snapshot(p) for p in data.get("pieces", [])],
        selected_cell=_pos(data.get("selected_cell")),
        game_over=data.get("game_over", False),
        airborne_pos=_pos(data.get("airborne_pos")),
        scores=scores,
        move_history=[_move_record(m) for m in data.get("move_history", [])],
        winner_color=PieceColor(raw_winner) if raw_winner is not None else None,
    )


class SnapshotReceiver:
    """
    Holds the most-recently received GameSnapshot and opponent-disconnect state.

    Call ``feed(raw_json)`` for every incoming WebSocket message.
    Call ``latest()`` to get the current board state.
    ``countdown_ms`` is set when MSG_OPPONENT_DISCONNECTED arrives and
    cleared on MSG_OPPONENT_RECONNECTED or when a game-over snapshot arrives.
    """

    def __init__(self, activity_logger: "ClientActivityLogger | None" = None) -> None:
        self._snapshot: Optional[GameSnapshot] = None
        self._countdown_ms: Optional[int] = None
        self._pending_error: Optional[str] = None
        self._activity_logger = activity_logger

    @property
    def snapshot(self) -> Optional[GameSnapshot]:
        return self._snapshot

    @property
    def countdown_ms(self) -> Optional[int]:
        """Remaining auto-resign window in ms, or None when no disconnect is pending."""
        return self._countdown_ms

    def latest(self) -> Optional[GameSnapshot]:
        """Zero-argument callable — suitable as a SnapshotProvider for Controller."""
        return self._snapshot

    def pop_error(self) -> Optional[str]:
        """
        Return and clear the most recent MSG_ERROR reason (e.g. a rejected
        move), or None if none is pending.  "Pop" semantics mean each error
        is surfaced to the caller exactly once — suitable for a render loop
        polling once per frame.
        """
        err, self._pending_error = self._pending_error, None
        return err

    def feed(self, raw: str) -> bool:
        """
        Parse one raw WebSocket message.  Handles MSG_SNAPSHOT, MSG_ERROR,
        MSG_OPPONENT_DISCONNECTED, and MSG_OPPONENT_RECONNECTED.
        Returns True if the message was recognised.
        """
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return False

        msg_type = msg.get("type")

        if msg_type == MSG_SNAPSHOT:
            try:
                self._snapshot = parse_snapshot(msg["data"])
                if self._snapshot.game_over:
                    self._countdown_ms = None
                    logger.info("Snapshot received — game_over=True")
                else:
                    logger.debug("Snapshot received — pieces=%d",
                                 len(self._snapshot.pieces))
                if self._activity_logger is not None:
                    import asyncio
                    asyncio.ensure_future(self._activity_logger.log(
                        "message_received",
                        {"msg_type": MSG_SNAPSHOT, "game_over": self._snapshot.game_over},
                    ))
                return True
            except Exception:
                logger.exception("Failed to parse snapshot: %s", raw[:200])
                return False

        if msg_type == MSG_OPPONENT_DISCONNECTED:
            self._countdown_ms = msg.get("auto_resign_ms")
            logger.info("Opponent disconnected — %r auto_resign_ms=%s",
                        msg.get("username"), self._countdown_ms)
            if self._activity_logger is not None:
                import asyncio
                asyncio.ensure_future(self._activity_logger.log(
                    "message_received",
                    {"msg_type": MSG_OPPONENT_DISCONNECTED, "username": msg.get("username")},
                ))
            return True

        if msg_type == MSG_OPPONENT_RECONNECTED:
            self._countdown_ms = None
            logger.info("Opponent reconnected — %r", msg.get("username"))
            if self._activity_logger is not None:
                import asyncio
                asyncio.ensure_future(self._activity_logger.log(
                    "message_received",
                    {"msg_type": MSG_OPPONENT_RECONNECTED, "username": msg.get("username")},
                ))
            return True

        if msg_type == MSG_ERROR:
            reason = msg.get("reason", "unknown error")
            self._pending_error = reason
            logger.warning("Command rejected: %s", reason)
            if self._activity_logger is not None:
                import asyncio
                asyncio.ensure_future(self._activity_logger.log(
                    "message_received",
                    {"msg_type": MSG_ERROR, "reason": reason},
                ))
            return True

        return False
