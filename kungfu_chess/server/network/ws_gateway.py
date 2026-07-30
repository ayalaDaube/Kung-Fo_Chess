"""
WsGateway — live-connection tier.

Owns every long-lived per-connection concern: room create/join/cancel,
move/jump commands, matchmaking, and disconnect/reconnect/auto-resign.

Auth is NOT done here.  A connection is considered authenticated when
ConnectionRegistry.identity_of(conn_id) returns a value — that entry is
written by ApiGateway.  WsGateway reads it but never writes it.

SRP: this class knows nothing about bcrypt, passwords, or login flows.
     It only routes game and room commands for already-authenticated
     (or unauthenticated-but-allowed) connections.

Shared wiring point
-------------------
Both ApiGateway and WsGateway receive the *same* ConnectionRegistry
instance.  Today that's a plain in-process object.  When the system
grows to multiple gateway instances the registry becomes a Redis-backed
Room Directory lookup — that swap happens in main.py wiring only, not
inside either gateway class.
"""
from __future__ import annotations
import json
import logging
from typing import Any, Callable, Awaitable

from kungfu_chess.server.auth.elo_service import EloService
from kungfu_chess.server.config import RealtimeConfig, MatchmakingConfig
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker
from kungfu_chess.server.matchmaking.matchmaking_coordinator import MatchmakingCoordinator
from kungfu_chess.server.matchmaking.matchmaking_loop import MatchmakingLoop
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    parse_incoming_message, ProtocolError,
    MoveCommand, JumpCommand,
    LoginCommand, RegisterCommand,
    CreateRoomCommand, JoinRoomCommand, CancelRoomCommand,
    FindMatchCommand, CancelMatchCommand,
    MSG_ERROR, MSG_ROOM_CREATED, MSG_ROOM_CANCELLED,
)
from kungfu_chess.server.network.serialization import snapshot_to_json
from kungfu_chess.server.session.disconnect_coordinator import DisconnectCoordinator
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.server.session.room_manager import RoomManager
from kungfu_chess.model.game_state import GameSnapshot

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], GameSession]
RoomIdGenerator = Callable[[], str]


def _default_room_id_generator() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


class WsGateway:
    """
    Routes live WebSocket connections to per-room GameSessions.

    Receives auth commands (LoginCommand / RegisterCommand) from the
    message loop and forwards them to an injected auth_dispatch callable
    — supplied by ConnectionRouter / main.py wiring — so WsGateway never
    imports ApiGateway directly (no circular dependency).
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        realtime_config: RealtimeConfig,
        registry: ConnectionRegistry,
        auth_dispatch: Callable[[str, LoginCommand | RegisterCommand], Awaitable[None]] | None = None,
        elo_service: EloService | None = None,
        matchmaking_config: MatchmakingConfig | None = None,
        room_id_generator: RoomIdGenerator = _default_room_id_generator,
        activity_logger: ActivityLogger | None = None,
        game_allocator=None,   # GameAllocator | None
        room_directory=None,   # RoomDirectory | None
    ) -> None:
        self._realtime_config = realtime_config
        self._activity_logger = activity_logger
        self._registry = registry
        self._auth_dispatch = auth_dispatch  # callable supplied by wiring layer

        self._room_manager = RoomManager(
            session_factory=session_factory,
            realtime_config=realtime_config,
            registry=registry,
            room_id_generator=room_id_generator,
            send=self._send,
            send_to_others=self._send_to_others,
            make_broadcast=self._make_broadcast,
            send_raw=self._send_raw,
            activity_logger=activity_logger,
            game_allocator=game_allocator,
            room_directory=room_directory,
        )

        self._disconnect_coordinator = DisconnectCoordinator(
            room_manager=self._room_manager,
            registry=registry,
            realtime_config=realtime_config,
            broadcast_snapshot=self._broadcast_snapshot,
            send_to_others=self._send_to_others,
            elo_service=elo_service,
        )

        self._mm_coordinator: MatchmakingCoordinator | None = None
        if matchmaking_config is not None:
            self._mm_coordinator = MatchmakingCoordinator(
                config=matchmaking_config,
                room_manager=self._room_manager,
                registry=registry,
                send=self._send,
                join_room=self._room_manager.handle_join_room,
                disconnect_monitors=self._disconnect_coordinator.monitors(),
            )

    # ── public connection handler ─────────────────────────────────────────────

    async def handle(self, ws: Any) -> None:
        conn_id = str(id(ws))
        self._registry.register(conn_id, ws)
        if self._mm_coordinator is not None and not self._mm_coordinator.loop.running:
            self._mm_coordinator.loop.start()
        logger.info("Connection opened: %s", conn_id)
        try:
            async for raw in ws:
                await self._dispatch(conn_id, raw)
        finally:
            await self._on_disconnect(conn_id)
            self._registry.forget(conn_id)
            logger.info("Connection closed: %s", conn_id)

    # ── room management (public API) ──────────────────────────────────────────

    async def create_room(self, room_id: str | None = None) -> str:
        return await self._room_manager.create_room(room_id)

    def cancel_room(self, room_id: str) -> bool:
        return self._room_manager.cancel_room(room_id)

    def room_ids(self) -> list[str]:
        return self._room_manager.room_ids()

    def session_for(self, room_id: str) -> GameSession | None:
        return self._room_manager.session_for(room_id)

    # ── backwards-compat shims (tests reach into these via ConnectionRouter) ──

    @property
    def _matchmaker(self) -> Matchmaker | None:
        return self._mm_coordinator.matchmaker if self._mm_coordinator else None

    @property
    def _matchmaking_loop(self) -> MatchmakingLoop | None:
        return self._mm_coordinator.loop if self._mm_coordinator else None

    # ── dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(self, conn_id: str, raw: str) -> None:
        result = parse_incoming_message(raw)
        if isinstance(result, ProtocolError):
            await self._send_error(conn_id, result.reason)
            return

        if self._activity_logger is not None:
            await self._activity_logger.log(
                "command_received",
                {"connection_id": conn_id, "command_type": type(result).__name__},
            )

        # Auth commands — forwarded to ApiGateway via injected callable
        if isinstance(result, (LoginCommand, RegisterCommand)):
            if self._auth_dispatch is None:
                await self._send_error(conn_id, "auth not configured")
            else:
                await self._auth_dispatch(conn_id, result)
            return

        if isinstance(result, FindMatchCommand):
            if self._mm_coordinator is None:
                await self._send_error(conn_id, "matchmaking not configured")
            else:
                await self._mm_coordinator.handle_find_match(conn_id)
            return

        if isinstance(result, CancelMatchCommand):
            if self._mm_coordinator is not None:
                await self._mm_coordinator.handle_cancel_match(conn_id)
            return

        if isinstance(result, CreateRoomCommand):
            rid = await self.create_room(result.room_id or None)
            await self._send(conn_id, {"type": MSG_ROOM_CREATED, "room_id": rid})
            return

        if isinstance(result, JoinRoomCommand):
            await self._room_manager.handle_join_room(
                conn_id, result.room_id, result.username,
                disconnect_monitors=self._disconnect_coordinator.monitors(),
            )
            return

        if isinstance(result, CancelRoomCommand):
            ok = self.cancel_room(result.room_id)
            if ok:
                await self._send(conn_id, {"type": MSG_ROOM_CANCELLED, "room_id": result.room_id})
            else:
                await self._send_error(conn_id, f"room {result.room_id!r} not found")
            return

        # Game commands — must be in a room
        room_id = self._registry.room_of(conn_id)
        if room_id is None:
            await self._send_error(conn_id, "not in a room")
            return
        session = self._room_manager.session_for(room_id)
        if session is None:
            await self._send_error(conn_id, "room no longer exists")
            return

        if isinstance(result, (MoveCommand, JumpCommand)):
            pos = result.from_pos if isinstance(result, MoveCommand) else result.pos
            if not session.owns_piece_at(conn_id, pos):
                await self._send_error(conn_id, "not your piece")
                return

        move_result, snapshot = await session.handle_command(conn_id, result)
        if not move_result.is_accepted:
            await self._send_error(conn_id, move_result.reason.value)
            return
        await self._broadcast_snapshot(room_id, snapshot)

    # ── disconnect ────────────────────────────────────────────────────────────

    async def _on_disconnect(self, conn_id: str) -> None:
        if self._mm_coordinator is not None:
            self._mm_coordinator.cancel_by_identity(conn_id)
        await self._disconnect_coordinator.on_disconnect(conn_id)

    # ── networking plumbing ───────────────────────────────────────────────────

    def _make_broadcast(self, room_id: str) -> Any:
        async def _broadcast(msg: str) -> None:
            await self._broadcast_raw(room_id, msg)
        return _broadcast

    async def _broadcast_snapshot(self, room_id: str, snapshot: GameSnapshot) -> None:
        await self._broadcast_raw(room_id, snapshot_to_json(snapshot))

    async def _broadcast_raw(self, room_id: str, msg: str) -> None:
        for conn_id in self._registry.conns_in_room(room_id):
            ws = self._registry.get_ws(conn_id)
            if ws:
                try:
                    await ws.send(msg)
                except Exception:
                    logger.exception("Failed to send to %s", conn_id)

    async def _send(self, conn_id: str, payload: dict) -> None:
        ws = self._registry.get_ws(conn_id)
        if ws:
            try:
                await ws.send(json.dumps(payload))
            except Exception:
                logger.debug("Failed to send to %s (connection closed?)", conn_id)

    async def _send_raw(self, conn_id: str, raw: str) -> None:
        ws = self._registry.get_ws(conn_id)
        if ws:
            try:
                await ws.send(raw)
            except Exception:
                logger.debug("Failed to send to %s (connection closed?)", conn_id)

    async def _send_to_others(self, room_id: str, exclude_conn_id: str, payload: dict) -> None:
        msg = json.dumps(payload)
        for conn_id in self._registry.conns_in_room(room_id):
            if conn_id == exclude_conn_id:
                continue
            ws = self._registry.get_ws(conn_id)
            if ws:
                try:
                    await ws.send(msg)
                except Exception:
                    logger.exception("Failed to send to %s", conn_id)

    async def _send_error(self, conn_id: str, reason: str) -> None:
        await self._send(conn_id, {"type": MSG_ERROR, "reason": reason})
