"""
RoomManager — owns dict[room_id, GameSession] and the TickLoop per room.

Responsibilities:
  - create_room / cancel_room
  - room_ids / session_for
  - handle_join_room (player slot assignment, spectator fallback, reconnect)
"""
from __future__ import annotations
import logging
from typing import Callable

from kungfu_chess.server.config import RealtimeConfig
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.bus import topics
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    MSG_ASSIGNED, MSG_ROOM_JOINED,
    MSG_OPPONENT_RECONNECTED,
)
from kungfu_chess.server.session.game_session import GameSession
from kungfu_chess.server.session.tick_loop import TickLoop

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], GameSession]
RoomIdGenerator = Callable[[], str]
SendFn = Callable[[str, dict], None]          # async (conn_id, payload)
SendToOthersFn = Callable[[str, str, dict], None]  # async (room_id, exclude, payload)
BroadcastFn = Callable[[str, str], None]      # async (room_id, raw_json)


class RoomManager:
    """
    Owns all room-level state: sessions and their tick loops.
    Receives send/broadcast callables so it never touches WebSocket objects.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        realtime_config: RealtimeConfig,
        registry: ConnectionRegistry,
        room_id_generator: RoomIdGenerator,
        send: SendFn,
        send_to_others: SendToOthersFn,
        make_broadcast: Callable[[str], BroadcastFn],
        activity_logger: ActivityLogger | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._realtime_config = realtime_config
        self._registry = registry
        self._room_id_generator = room_id_generator
        self._send = send
        self._send_to_others = send_to_others
        self._make_broadcast = make_broadcast
        self._activity_logger = activity_logger

        self._rooms: dict[str, GameSession] = {}
        self._tick_loops: dict[str, TickLoop] = {}

        # disconnect monitors injected after construction to avoid circular dep
        self._disconnect_monitors: dict[tuple[str, str], object] | None = None

    # ── room lifecycle ────────────────────────────────────────────────────────

    async def create_room(self, room_id: str | None = None) -> str:
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
        if room_id not in self._rooms:
            return False
        self._tick_loops[room_id].stop()
        del self._tick_loops[room_id]
        del self._rooms[room_id]
        self._registry.remove_room_entries(room_id)
        logger.info("Room cancelled: %s", room_id)
        return True

    def room_ids(self) -> list[str]:
        return list(self._rooms.keys())

    def session_for(self, room_id: str) -> GameSession | None:
        return self._rooms.get(room_id)

    # ── join handling ─────────────────────────────────────────────────────────

    async def handle_join_room(
        self,
        conn_id: str,
        room_id: str,
        username: str = "",
        disconnect_monitors: dict | None = None,
    ) -> None:
        session = self._rooms.get(room_id)
        if session is None:
            await self._send(conn_id, {"type": "error", "reason": f"room {room_id!r} not found"})
            return

        self._registry.assign_room(conn_id, room_id)

        if username and session.has_player(username):
            session.rebind_connection(username, conn_id)
            if disconnect_monitors is not None:
                monitor = disconnect_monitors.pop((room_id, username), None)
                if monitor is not None:
                    monitor.cancel()
            await session.publish_reconnected(room_id, username, conn_id)
            await self._send_to_others(room_id, conn_id, {
                "type": MSG_OPPONENT_RECONNECTED,
                "username": username,
            })
            color = session.color_for(conn_id)
            await self._send(conn_id, {"type": MSG_ROOM_JOINED, "room_id": room_id, "role": "player"})
            await self._send(conn_id, {"type": MSG_ASSIGNED, "color": color.value})
            return

        if not session.players_full():
            color = session.assign_color(conn_id)
            if username:
                await session.record_join(conn_id, username)
            await self._send(conn_id, {"type": MSG_ROOM_JOINED, "room_id": room_id, "role": "player"})
            await self._send(conn_id, {"type": MSG_ASSIGNED, "color": color.value})
        else:
            session.add_spectator(conn_id)
            await self._send(conn_id, {"type": MSG_ROOM_JOINED, "room_id": room_id, "role": "spectator"})

    # ── logger wiring ─────────────────────────────────────────────────────────

    def _subscribe_logger_to_session(self, session: GameSession) -> None:
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
