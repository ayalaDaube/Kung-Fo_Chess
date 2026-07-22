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
  - Route matchmaking commands to Matchmaker
  - Start/cancel DisconnectMonitor on player disconnect/reconnect
"""
from __future__ import annotations
import json
import logging
import time
from typing import Any, Callable

from kungfu_chess.server.auth.auth_service import AuthService, RegisterStatus, LoginStatus
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.bus import topics
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.config import RealtimeConfig, MatchmakingConfig
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker, MatchResult, QueueEntry
from kungfu_chess.server.matchmaking.matchmaking_loop import MatchmakingLoop
from kungfu_chess.server.network.protocol import (
    parse_incoming_message, ProtocolError,
    MoveCommand, JumpCommand,
    LoginCommand, RegisterCommand,
    CreateRoomCommand, JoinRoomCommand, CancelRoomCommand,
    FindMatchCommand, CancelMatchCommand,
    MSG_ASSIGNED, MSG_ERROR,
    MSG_LOGGED_IN, MSG_REGISTERED,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ROOM_CANCELLED,
    MSG_MATCH_FOUND, MSG_MATCH_TIMEOUT,
    MSG_OPPONENT_DISCONNECTED, MSG_OPPONENT_RECONNECTED,
)
from kungfu_chess.server.network.serialization import snapshot_to_json
from kungfu_chess.server.session.disconnect_monitor import DisconnectMonitor
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.server.session.tick_loop import TickLoop
from kungfu_chess.model.game_state import GameSnapshot

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], GameSession]
RoomIdGenerator = Callable[[], str]


def _default_room_id_generator() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


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
        matchmaking_config: MatchmakingConfig | None = None,
        room_id_generator: RoomIdGenerator = _default_room_id_generator,
        activity_logger: ActivityLogger | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._realtime_config = realtime_config
        self._auth = auth_service
        self._room_id_generator = room_id_generator
        self._activity_logger = activity_logger

        self._rooms: dict[str, GameSession] = {}           # room_id -> session
        self._tick_loops: dict[str, TickLoop] = {}         # room_id -> tick loop
        self._conn_to_room: dict[str, str] = {}            # connection_id -> room_id
        self._connections: dict[str, Any] = {}             # connection_id -> ws
        self._logged_in: dict[str, tuple[str, int]] = {}   # conn_id -> (username, elo)

        # disconnect monitors: (room_id, username) -> DisconnectMonitor
        self._disconnect_monitors: dict[tuple[str, str], DisconnectMonitor] = {}

        # matchmaking (optional — only active when matchmaking_config is provided)
        self._matchmaker: Matchmaker | None = None
        self._matchmaking_loop: MatchmakingLoop | None = None
        if matchmaking_config is not None:
            self._matchmaker = Matchmaker(matchmaking_config)
            self._matchmaking_loop = MatchmakingLoop(
                matchmaker=self._matchmaker,
                config=matchmaking_config,
                on_match=self._on_match,
                on_timeout=self._on_match_timeout,
            )

    # ── public connection handler ─────────────────────────────────────────────

    async def handle(self, ws: Any) -> None:
        conn_id = str(id(ws))
        self._connections[conn_id] = ws
        if self._matchmaking_loop is not None and not self._matchmaking_loop.running:
            self._matchmaking_loop.start()
        logger.info("Connection opened: %s", conn_id)
        try:
            async for raw in ws:
                await self._dispatch(conn_id, raw)
        finally:
            await self._on_disconnect(conn_id)
            self._connections.pop(conn_id, None)
            self._conn_to_room.pop(conn_id, None)
            self._logged_in.pop(conn_id, None)
            logger.info("Connection closed: %s", conn_id)

    # ── room management ───────────────────────────────────────────────────────

    async def create_room(self, room_id: str | None = None) -> str:
        """Create a new room and return its id."""
        rid = room_id or self._room_id_generator()
        session = self._session_factory()
        session.game_id = rid
        self._rooms[rid] = session
        if self._activity_logger is not None:
            self._subscribe_logger_to_session(session)
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
        stale = [c for c, r in self._conn_to_room.items() if r == room_id]
        for c in stale:
            del self._conn_to_room[c]
        logger.info("Room cancelled: %s", room_id)
        return True

    def _subscribe_logger_to_session(self, session: GameSession) -> None:
        """Subscribe ActivityLogger to every loggable bus topic on this session."""
        al = self._activity_logger
        assert al is not None
        _loggable = [
            topics.MOVE_ACCEPTED, topics.MOVE_REJECTED,
            topics.JUMP_ACCEPTED, topics.JUMP_REJECTED,
            topics.SNAPSHOT, topics.PLAYER_JOINED,
            topics.PLAYER_DISCONNECTED, topics.PLAYER_RECONNECTED,
            topics.GAME_ENDED,
        ]
        for topic in _loggable:
            def _make_handler(t: str):
                async def _handler(payload):
                    game_id = payload.get("game_id") if isinstance(payload, dict) else None
                    await al.log(t, payload, game_id=game_id)
                return _handler
            session.subscribe(topic, _make_handler(topic))

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

        if self._activity_logger is not None:
            cmd_type = type(result).__name__
            await self._activity_logger.log(
                "command_received",
                {"connection_id": conn_id, "command_type": cmd_type},
            )

        if isinstance(result, (LoginCommand, RegisterCommand)):
            await self._handle_auth(conn_id, result)
            return

        if isinstance(result, FindMatchCommand):
            await self._handle_find_match(conn_id)
            return

        if isinstance(result, CancelMatchCommand):
            await self._handle_cancel_match(conn_id)
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
            # Cancel any pending auto-resign for this player.
            monitor_key = (room_id, username)
            monitor = self._disconnect_monitors.pop(monitor_key, None)
            if monitor is not None:
                monitor.cancel()
            await session.publish_reconnected(room_id, username, conn_id)
            await self._send_to_others(room_id, conn_id, {
                "type": MSG_OPPONENT_RECONNECTED,
                "username": username,
            })
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
                self._logged_in[conn_id] = (result.user.username, result.user.elo)
                await self._send(conn_id, {"type": MSG_REGISTERED, "username": command.username})
                if self._activity_logger is not None:
                    await self._activity_logger.log(
                        "auth_register",
                        {"username": command.username, "outcome": "success"},
                    )
            else:
                await self._send_error(conn_id, result.message)
                if self._activity_logger is not None:
                    await self._activity_logger.log(
                        "auth_register",
                        {"username": command.username, "outcome": "failure", "reason": result.message},
                    )
        else:
            result = await self._auth.login(command.username, command.password)
            if result.status == LoginStatus.SUCCESS:
                self._logged_in[conn_id] = (result.user.username, result.user.elo)
                await self._send(conn_id, {
                    "type": MSG_LOGGED_IN,
                    "username": result.user.username,
                    "elo": result.user.elo,
                })
                if self._activity_logger is not None:
                    await self._activity_logger.log(
                        "auth_login",
                        {"username": command.username, "outcome": "success"},
                    )
            else:
                await self._send_error(conn_id, "invalid credentials")
                if self._activity_logger is not None:
                    await self._activity_logger.log(
                        "auth_login",
                        {"username": command.username, "outcome": "failure", "reason": "invalid_credentials"},
                    )

    async def _handle_find_match(self, conn_id: str) -> None:
        if self._matchmaker is None:
            await self._send_error(conn_id, "matchmaking not configured")
            return
        identity = self._logged_in.get(conn_id)
        if identity is None:
            await self._send_error(conn_id, "must be logged in to find a match")
            return
        username, elo = identity
        self._matchmaker.enqueue(username, elo, conn_id, _now_ms())

    async def _handle_cancel_match(self, conn_id: str) -> None:
        if self._matchmaker is None:
            return
        identity = self._logged_in.get(conn_id)
        if identity is not None:
            self._matchmaker.cancel(identity[0])

    # ── matchmaking callbacks ─────────────────────────────────────────────────

    async def _on_match(self, match: MatchResult) -> None:
        rid = await self.create_room()
        for entry in (match.entry_a, match.entry_b):
            if entry.conn_id in self._connections:
                await self._handle_join_room(entry.conn_id, rid, entry.username)
                await self._send(entry.conn_id, {
                    "type": MSG_MATCH_FOUND,
                    "room_id": rid,
                    "opponent": (
                        match.entry_b.username
                        if entry is match.entry_a
                        else match.entry_a.username
                    ),
                })

    async def _on_match_timeout(self, entry: QueueEntry) -> None:
        if entry.conn_id in self._connections:
            await self._send(entry.conn_id, {"type": MSG_MATCH_TIMEOUT})

    # ── disconnect / reconnect ────────────────────────────────────────────────

    async def _on_disconnect(self, conn_id: str) -> None:
        # FIX 4: cancel matchmaking queue entry even if not yet in a room
        if self._matchmaker is not None:
            identity = self._logged_in.get(conn_id)
            if identity is not None:
                self._matchmaker.cancel(identity[0])

        room_id = self._conn_to_room.get(conn_id)
        if room_id is None:
            return
        session = self._rooms.get(room_id)
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
        if monitor_key not in self._disconnect_monitors:
            async def _resign(r=room_id, u=username) -> None:
                await self._auto_resign(r, u)

            monitor = DisconnectMonitor(
                delay_ms=self._realtime_config.auto_resign_ms,
                on_resign=_resign,
            )
            self._disconnect_monitors[monitor_key] = monitor
            monitor.start()

    async def _auto_resign(self, room_id: str, username: str) -> None:
        self._disconnect_monitors.pop((room_id, username), None)
        session = self._rooms.get(room_id)
        if session is None:
            return
        snapshot = await session.resign(username)
        # Apply ELO update if auth is wired and both players are known.
        if self._auth is not None:
            winner = session.other_player_username(username)
            if winner is not None:
                await self._auth.apply_elo_update(winner, username)
        await self._broadcast_snapshot(room_id, snapshot)
        # FIX 3c: tear down the room after resign (mirrors cancel_room)
        self.cancel_room(room_id)

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
            try:
                await ws.send(json.dumps(payload))
            except Exception:
                # Connection may have closed between selection and send; the
                # handler's finally-block will clean it up. Mirror the
                # resilience of _broadcast_raw / _send_to_others so a single
                # dead connection never tears down the dispatch loop.
                logger.debug("Failed to send to %s (connection closed?)", conn_id)

    async def _send_to_others(self, room_id: str, exclude_conn_id: str, payload: dict) -> None:
        """Send payload to every connection in room_id except exclude_conn_id."""
        msg = json.dumps(payload)
        for conn_id, rid in list(self._conn_to_room.items()):
            if rid != room_id or conn_id == exclude_conn_id:
                continue
            ws = self._connections.get(conn_id)
            if ws:
                try:
                    await ws.send(msg)
                except Exception:
                    logger.exception("Failed to send to %s", conn_id)

    async def _send_error(self, conn_id: str, reason: str) -> None:
        await self._send(conn_id, {"type": MSG_ERROR, "reason": reason})
