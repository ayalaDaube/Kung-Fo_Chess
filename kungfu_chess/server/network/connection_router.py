"""
ConnectionRouter — connection routing only.

Accepts incoming WebSocket connections and routes messages to the correct
per-room GameSession. Does not contain game logic, auth logic, or tick logic.

Responsibilities:
  - Maintain dict[room_id, GameSession]
  - Maintain dict[connection_id, room_id]
  - Accept players into rooms (up to MAX_PLAYERS) and spectators beyond that
  - Start/stop a TickLoop per room
  - Broadcast snapshots to all connections in a room
  - Route auth commands to AuthService
"""
from __future__ import annotations
import json
import logging
from typing import Any, Callable

from kungfu_chess.server.auth.auth_service import AuthService, RegisterStatus, LoginStatus
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.network.protocol import (
    parse_incoming_message, ProtocolError,
    JoinCommand, MoveCommand, JumpCommand,
    LoginCommand, RegisterCommand,
    CreateRoomCommand, JoinRoomCommand, CancelRoomCommand,
    MSG_ASSIGNED, MSG_JOINED, MSG_ERROR,
    MSG_LOGGED_IN, MSG_REGISTERED,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ROOM_CANCELLED,
)
from kungfu_chess.server.network.serialization import snapshot_to_json
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.server.session.tick_loop import TickLoop
from kungfu_chess.model.game_state import GameSnapshot

logger = logging.getLogger(__name__)

# Injectable factory — mirrors engine_factory pattern in GameSession.
SessionFactory = Callable[[], GameSession]

# Injectable room-id generator — swappable without touching router internals.
RoomIdGenerator = Callable[[], str]


def _default_room_id_generator() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


class ConnectionRouter:
    """
    Routes WebSocket connections to per-room GameSessions.
    One router per server process; rooms are created on demand.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        realtime_config: RealtimeConfig,
        auth_service: AuthService | None = None,
        room_id_generator: RoomIdGenerator = _default_room_id_generator,
    ) -> None:
        self._session_factory = session_factory
        self._realtime_config = realtime_config
        self._auth = auth_service
        self._room_id_generator = room_id_generator

        self._rooms: dict[str, GameSession] = {}           # room_id -> session
        self._tick_loops: dict[str, TickLoop] = {}         # room_id -> tick loop
        self._conn_to_room: dict[str, str] = {}            # connection_id -> room_id
        self._connections: dict[str, Any] = {}             # connection_id -> ws

    # ── public connection handler ─────────────────────────────────────────────

    async def handle(self, ws: Any) -> None:
        conn_id = str(id(ws))
        self._connections[conn_id] = ws
        logger.info("Connection opened: %s", conn_id)
        try:
            async for raw in ws:
                await self._dispatch(conn_id, raw)
        finally:
            self._connections.pop(conn_id, None)
            self._conn_to_room.pop(conn_id, None)
            logger.info("Connection closed: %s", conn_id)

    # ── room management ───────────────────────────────────────────────────────

    async def create_room(self, room_id: str | None = None) -> str:
        """Create a new room and return its id."""
        rid = room_id or self._room_id_generator()
        session = self._session_factory()
        session.game_id = rid
        self._rooms[rid] = session
        self._tick_loops[rid] = TickLoop(
            session=session,
            broadcast=self._make_broadcast(rid),
            config=self._realtime_config,
        )
        self._tick_loops[rid].start()
        logger.info("Room created: %s", rid)
        return rid

    def cancel_room(self, room_id: str) -> bool:
        """Tear down a room. Returns True if it existed."""
        if room_id not in self._rooms:
            return False
        self._tick_loops[room_id].stop()
        del self._tick_loops[room_id]
        del self._rooms[room_id]
        # disconnect any connections still mapped to this room
        stale = [c for c, r in self._conn_to_room.items() if r == room_id]
        for c in stale:
            del self._conn_to_room[c]
        logger.info("Room cancelled: %s", room_id)
        return True

    def room_ids(self) -> list[str]:
        return list(self._rooms.keys())

    def session_for(self, room_id: str) -> GameSession | None:
        return self._rooms.get(room_id)

    # ── internal dispatch ─────────────────────────────────────────────────────

    async def _dispatch(self, conn_id: str, raw: str) -> None:
        result = parse_incoming_message(raw)
        if isinstance(result, ProtocolError):
            await self._send_error(conn_id, result.reason)
            return

        if isinstance(result, (LoginCommand, RegisterCommand)):
            await self._handle_auth(conn_id, result)
            return

        if isinstance(result, CreateRoomCommand):
            rid = await self.create_room(result.room_id or None)
            await self._send(conn_id, {"type": MSG_ROOM_CREATED, "room_id": rid})
            return

        if isinstance(result, JoinRoomCommand):
            await self._handle_join_room(conn_id, result.room_id, result.username)
            return

        if isinstance(result, CancelRoomCommand):
            ok = self.cancel_room(result.room_id)
            if ok:
                await self._send(conn_id, {"type": MSG_ROOM_CANCELLED, "room_id": result.room_id})
            else:
                await self._send_error(conn_id, f"room {result.room_id!r} not found")
            return

        # Game commands — must be in a room
        room_id = self._conn_to_room.get(conn_id)
        if room_id is None:
            await self._send_error(conn_id, "not in a room")
            return
        session = self._rooms.get(room_id)
        if session is None:
            await self._send_error(conn_id, "room no longer exists")
            return

        if isinstance(result, (MoveCommand, JumpCommand)):
            pos = result.from_pos if isinstance(result, MoveCommand) else result.pos
            if not session.owns_piece_at(conn_id, pos):
                await self._send_error(conn_id, "not your piece")
                return

        move_result, snapshot = await session.handle_command(conn_id, result)

        if isinstance(result, JoinCommand):
            await self._send(conn_id, {"type": MSG_JOINED, "username": result.username})
            return

        if not move_result.is_accepted:
            await self._send_error(conn_id, move_result.reason.value)
            return

        await self._broadcast_snapshot(room_id, snapshot)

    async def _handle_join_room(self, conn_id: str, room_id: str, username: str = "") -> None:
        session = self._rooms.get(room_id)
        if session is None:
            await self._send_error(conn_id, f"room {room_id!r} not found")
            return

        self._conn_to_room[conn_id] = room_id

        # Reconnect: username already has a PlayerRecord — rebind without consuming a slot.
        if username and session.has_player(username):
            session.rebind_connection(username, conn_id)
            color = session.color_for(conn_id)
            await self._send(conn_id, {
                "type": MSG_ROOM_JOINED,
                "room_id": room_id,
                "role": "player",
            })
            await self._send(conn_id, {"type": MSG_ASSIGNED, "color": color.value})
            return

        if not session.players_full():
            color = session.assign_color(conn_id)
            if username:
                await session.record_join(conn_id, username)
            await self._send(conn_id, {
                "type": MSG_ROOM_JOINED,
                "room_id": room_id,
                "role": "player",
            })
            await self._send(conn_id, {"type": MSG_ASSIGNED, "color": color.value})
        else:
            session.add_spectator(conn_id)
            await self._send(conn_id, {
                "type": MSG_ROOM_JOINED,
                "room_id": room_id,
                "role": "spectator",
            })

    async def _handle_auth(self, conn_id: str, command: LoginCommand | RegisterCommand) -> None:
        if self._auth is None:
            await self._send_error(conn_id, "auth not configured")
            return
        if isinstance(command, RegisterCommand):
            result = await self._auth.register(command.username, command.password)
            if result.status == RegisterStatus.SUCCESS:
                await self._send(conn_id, {"type": MSG_REGISTERED, "username": command.username})
            else:
                await self._send_error(conn_id, result.message)
        else:
            result = await self._auth.login(command.username, command.password)
            if result.status == LoginStatus.SUCCESS:
                await self._send(conn_id, {
                    "type": MSG_LOGGED_IN,
                    "username": result.user.username,
                    "elo": result.user.elo,
                })
            else:
                await self._send_error(conn_id, "invalid credentials")

    # ── broadcast helpers ─────────────────────────────────────────────────────

    def _make_broadcast(self, room_id: str) -> Any:
        async def _broadcast(msg: str) -> None:
            await self._broadcast_raw(room_id, msg)
        return _broadcast

    async def _broadcast_snapshot(self, room_id: str, snapshot: GameSnapshot) -> None:
        await self._broadcast_raw(room_id, snapshot_to_json(snapshot))

    async def _broadcast_raw(self, room_id: str, msg: str) -> None:
        for conn_id, rid in list(self._conn_to_room.items()):
            if rid != room_id:
                continue
            ws = self._connections.get(conn_id)
            if ws:
                try:
                    await ws.send(msg)
                except Exception:
                    logger.exception("Failed to send to %s", conn_id)

    async def _send(self, conn_id: str, payload: dict) -> None:
        ws = self._connections.get(conn_id)
        if ws:
            await ws.send(json.dumps(payload))

    async def _send_error(self, conn_id: str, reason: str) -> None:
        await self._send(conn_id, {"type": MSG_ERROR, "reason": reason})
