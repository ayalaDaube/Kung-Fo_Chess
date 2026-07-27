"""
DisconnectCoordinator — manages player disconnect/reconnect and auto-resign.

Owns the DisconnectMonitor lifecycle.  Depends on RoomManager and
ConnectionRegistry (both injected).  Never touches WebSocket objects directly.
"""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

from kungfu_chess.server.auth.elo_service import EloService
from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    MSG_OPPONENT_DISCONNECTED,
)
from kungfu_chess.server.session.disconnect_monitor import DisconnectMonitor
from kungfu_chess.server.session.room_manager import RoomManager

logger = logging.getLogger(__name__)

BroadcastSnapshotFn = Callable[[str, object], Awaitable[None]]
SendToOthersFn = Callable[[str, str, dict], Awaitable[None]]


class DisconnectCoordinator:
    """
    Handles the full disconnect → auto-resign → room-teardown flow.
    """

    def __init__(
        self,
        room_manager: RoomManager,
        registry: ConnectionRegistry,
        realtime_config: RealtimeConfig,
        broadcast_snapshot: BroadcastSnapshotFn,
        send_to_others: SendToOthersFn,
        elo_service: EloService | None = None,
    ) -> None:
        self._room_manager = room_manager
        self._registry = registry
        self._realtime_config = realtime_config
        self._broadcast_snapshot = broadcast_snapshot
        self._send_to_others = send_to_others
        self._elo = elo_service

        self._monitors: dict[tuple[str, str], DisconnectMonitor] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def monitors(self) -> dict[tuple[str, str], DisconnectMonitor]:
        """Expose monitor dict so RoomManager.handle_join_room can cancel on reconnect."""
        return self._monitors

    async def on_disconnect(self, conn_id: str) -> None:
        room_id = self._registry.room_of(conn_id)
        if room_id is None:
            return
        session = self._room_manager.session_for(room_id)
        if session is None or session.is_spectator(conn_id):
            return
        username = session.username_for(conn_id)
        if username is None:
            return

        await session.publish_disconnected(room_id, username, conn_id)
        await self._send_to_others(room_id, conn_id, {
            "type": MSG_OPPONENT_DISCONNECTED,
            "username": username,
            "auto_resign_ms": self._realtime_config.auto_resign_ms,
        })

        monitor_key = (room_id, username)
        if monitor_key not in self._monitors:
            async def _resign(r=room_id, u=username) -> None:
                await self._auto_resign(r, u)

            monitor = DisconnectMonitor(
                delay_ms=self._realtime_config.auto_resign_ms,
                on_resign=_resign,
            )
            self._monitors[monitor_key] = monitor
            monitor.start()

    # ── internal ──────────────────────────────────────────────────────────────

    async def _auto_resign(self, room_id: str, username: str) -> None:
        self._monitors.pop((room_id, username), None)
        session = self._room_manager.session_for(room_id)
        if session is None:
            return
        snapshot = await session.resign(username)
        if self._elo is not None:
            winner = session.other_player_username(username)
            if winner is not None:
                await self._elo.apply_elo_update(winner, username)
        await self._broadcast_snapshot(room_id, snapshot)
        self._room_manager.cancel_room(room_id)
