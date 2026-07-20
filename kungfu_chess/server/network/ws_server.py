"""
WebSocket server: accepts exactly 2 connections, routes messages through
protocol.parse_incoming_message → GameSession, broadcasts snapshots to both.
Owns the EventBus and GameSession; never reaches into their internals.
"""
from __future__ import annotations
import dataclasses
import json
import logging
from typing import Any

from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.network.protocol import (
    parse_incoming_message, ProtocolError, JoinCommand, MoveCommand, JumpCommand,
    MSG_ASSIGNED, MSG_JOINED, MSG_SNAPSHOT, MSG_ERROR,
)
from kungfu_chess.server.session.game_session import GameSession

logger = logging.getLogger(__name__)


def _snapshot_to_json(snapshot: GameSnapshot) -> str:
    """Serialises a GameSnapshot to a JSON string for wire transport."""
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
    return json.dumps({"type": MSG_SNAPSHOT, "data": _convert(snapshot)})


class WsServer:
    """
    Manages the two WebSocket connections for one game.
    Responsibilities: connection lifecycle, message routing, broadcast.
    Does not contain game logic.
    """

    def __init__(
        self,
        session: GameSession | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._bus = bus or EventBus()
        self._session = session or GameSession(self._bus)
        self._connections: dict[str, Any] = {}

    # ── connection handler (passed to websockets.serve) ───────────────────────

    async def handle(self, ws: Any) -> None:
        conn_id = str(id(ws))

        if self._session.is_full():
            await ws.send(json.dumps({
                "type": MSG_ERROR,
                "reason": "server full: only 2 players allowed",
            }))
            await ws.close()
            return

        color = self._session.assign_color(conn_id)
        self._connections[conn_id] = ws
        await ws.send(json.dumps({"type": MSG_ASSIGNED, "color": color.value}))
        logger.info("Player connected: %s as %s", conn_id, color.value)

        try:
            async for raw in ws:
                await self._dispatch(conn_id, raw)
        finally:
            self._connections.pop(conn_id, None)
            logger.info("Player disconnected: %s", conn_id)

    # ── internal ──────────────────────────────────────────────────────────────

    async def _dispatch(self, conn_id: str, raw: str) -> None:
        result = parse_incoming_message(raw)
        if isinstance(result, ProtocolError):
            await self._send_error(conn_id, result.reason)
            return

        if isinstance(result, (MoveCommand, JumpCommand)):
            pos = result.from_pos if isinstance(result, MoveCommand) else result.pos
            if not self._session.owns_piece_at(conn_id, pos):
                await self._send_error(conn_id, "not your piece")
                return

        move_result, snapshot = await self._session.handle_command(conn_id, result)

        if isinstance(result, JoinCommand):
            ws = self._connections.get(conn_id)
            if ws:
                await ws.send(json.dumps({"type": MSG_JOINED, "username": result.username}))
            return

        if not move_result.is_accepted:
            await self._send_error(conn_id, move_result.reason.value)
            return

        await self._broadcast_snapshot(snapshot)

    async def _send_error(self, conn_id: str, reason: str) -> None:
        ws = self._connections.get(conn_id)
        if ws:
            await ws.send(json.dumps({"type": MSG_ERROR, "reason": reason}))

    async def _broadcast_snapshot(self, snapshot: GameSnapshot) -> None:
        msg = _snapshot_to_json(snapshot)
        for ws in list(self._connections.values()):
            try:
                await ws.send(msg)
            except Exception:
                logger.exception("Failed to send snapshot to a connection")
