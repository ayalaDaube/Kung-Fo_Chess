"""
ConnectionRouter — thin facade composing ApiGateway and WsGateway.

This class exists for backwards compatibility: all existing tests and
main.py import ConnectionRouter and call its public API unchanged.

Internally it wires:
  - ApiGateway  — stateless auth (login / register)
  - WsGateway   — live connections (rooms, moves, matchmaking, disconnect)

Both share one ConnectionRegistry instance.  That shared object is the
single wiring point that a future multi-instance deployment would replace
with a Redis Room Directory — the swap happens here, not inside either
gateway.

Do NOT add new logic here.  New auth logic belongs in ApiGateway;
new game/room logic belongs in WsGateway.
"""
from __future__ import annotations
import logging
from typing import Any, Callable

from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.elo_service import EloService
from kungfu_chess.server.config import RealtimeConfig, MatchmakingConfig
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.matchmaking.matchmaker import Matchmaker
from kungfu_chess.server.matchmaking.matchmaking_loop import MatchmakingLoop
from kungfu_chess.server.network.api_gateway import ApiGateway
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.ws_gateway import WsGateway
from kungfu_chess.server.session.disconnect_coordinator import DisconnectCoordinator
from kungfu_chess.server.session.game_session import GameSession

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], GameSession]
RoomIdGenerator = Callable[[], str]


def _default_room_id_generator() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


class ConnectionRouter:
    """
    Backwards-compatible facade over ApiGateway + WsGateway.

    Constructor signature is identical to the old monolithic class so
    callers (main.py, all tests) require zero changes.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        realtime_config: RealtimeConfig,
        auth_service: AuthService | None = None,
        elo_service: EloService | None = None,
        matchmaking_config: MatchmakingConfig | None = None,
        room_id_generator: RoomIdGenerator = _default_room_id_generator,
        activity_logger: ActivityLogger | None = None,
        game_allocator=None,   # GameAllocator | None
        room_directory=None,   # RoomDirectory | None
    ) -> None:
        self._realtime_config = realtime_config
        self._registry = ConnectionRegistry()

        # ApiGateway — auth tier (None when auth_service is None)
        self._api_gateway: ApiGateway | None = None
        if auth_service is not None:
            self._api_gateway = ApiGateway(
                auth_service=auth_service,
                registry=self._registry,
                send=self._send_via_registry,
                activity_logger=activity_logger,
            )
        # keep _auth for the test_server_main.py shim
        self._auth = auth_service

        # WsGateway — live-connection tier
        self._ws_gateway = WsGateway(
            session_factory=session_factory,
            realtime_config=realtime_config,
            registry=self._registry,
            auth_dispatch=self._api_gateway.handle_auth if self._api_gateway else None,
            elo_service=elo_service,
            matchmaking_config=matchmaking_config,
            room_id_generator=room_id_generator,
            activity_logger=activity_logger,
            game_allocator=game_allocator,
            room_directory=room_directory,
        )

    # ── async send helper used by ApiGateway before WsGateway is wired ───────

    async def _send_via_registry(self, conn_id: str, payload: dict) -> None:
        """Thin send shim passed to ApiGateway at construction time."""
        import json
        ws = self._registry.get_ws(conn_id)
        if ws:
            try:
                await ws.send(json.dumps(payload))
            except Exception:
                logger.debug("Failed to send to %s (connection closed?)", conn_id)

    # ── backwards-compat shims (existing tests reach into these) ─────────────

    @property
    def _connections(self) -> dict:
        return self._registry._connections

    @property
    def _logged_in(self) -> dict:
        return self._registry._logged_in

    @property
    def _conn_to_room(self) -> dict:
        return self._registry._conn_to_room

    @property
    def _disconnect_monitors(self) -> dict:
        return self._ws_gateway._disconnect_coordinator.monitors()

    @property
    def _matchmaker(self) -> Matchmaker | None:
        return self._ws_gateway._matchmaker

    @property
    def _matchmaking_loop(self) -> MatchmakingLoop | None:
        return self._ws_gateway._matchmaking_loop

    # ── public connection handler ─────────────────────────────────────────────

    async def handle(self, ws: Any) -> None:
        await self._ws_gateway.handle(ws)

    # ── room management ───────────────────────────────────────────────────────

    async def create_room(self, room_id: str | None = None) -> str:
        return await self._ws_gateway.create_room(room_id)

    def cancel_room(self, room_id: str) -> bool:
        return self._ws_gateway.cancel_room(room_id)

    def room_ids(self) -> list[str]:
        return self._ws_gateway.room_ids()

    def session_for(self, room_id: str) -> GameSession | None:
        return self._ws_gateway.session_for(room_id)

    # ── internal helpers (used by tests that call _on_disconnect directly) ────

    async def _on_disconnect(self, conn_id: str) -> None:
        await self._ws_gateway._on_disconnect(conn_id)
