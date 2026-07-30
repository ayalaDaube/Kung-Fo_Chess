"""
WebSocket Gateway entry point.

Runs WsGateway: rooms, moves, matchmaking, disconnect/reconnect.
Uses RedisConnectionRegistry so login state written by the ApiGateway
process is visible here via the shared Redis instance.

Auth dispatch still calls AuthService directly (in-process) — the
auth_dispatch callable already flows through an injected callable, so
no network call is needed yet.  A future phase can replace that callable
with a Redis/gRPC lookup without changing WsGateway's internals.

Start with:
    python -m kungfu_chess.server.main_ws
Or via docker-compose: the ws-gateway service.
"""
from __future__ import annotations
import asyncio
import logging
import os

import websockets

from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.elo_cache import EloCache
from kungfu_chess.server.auth.elo_service import EloService
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.api_gateway import ApiGateway
from kungfu_chess.server.network.redis_connection_registry import RedisConnectionRegistry
from kungfu_chess.server.network.ws_gateway import WsGateway
from kungfu_chess.server.allocator.game_allocator import GameAllocator
from kungfu_chess.server.allocator.room_directory import RoomDirectory
from kungfu_chess.server.session.game_session import GameSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_repo(config):
    backend = os.environ.get("DB_BACKEND", "sqlite").lower()
    if backend == "postgres":
        from kungfu_chess.server.auth.db import PostgresUserRepository
        logger.info("Using PostgresUserRepository")
        return PostgresUserRepository(
            host=config.database.host,
            port=config.database.port,
            user=config.database.user,
            password=config.database.password,
            dbname=config.database.dbname,
        )
    from kungfu_chess.server.auth.db import SqliteUserRepository
    logger.info("Using SqliteUserRepository (%s)", config.auth.sqlite_db_path)
    return SqliteUserRepository(config.auth.sqlite_db_path)


async def _main() -> None:
    config = load_server_config()

    repo = _build_repo(config)
    elo_cache = EloCache(
        host=config.redis.host,
        port=config.redis.port,
        ttl_seconds=config.redis.elo_ttl_seconds,
    )
    auth_service = AuthService(repo=repo, config=config.auth, elo_cache=elo_cache)
    elo_service = EloService(repo=repo, config=config.auth, elo_cache=elo_cache)
    activity_logger = ActivityLogger(config.logging.log_path)

    registry = RedisConnectionRegistry(
        host=config.redis.host,
        port=config.redis.port,
    )

    # ApiGateway is constructed here only to provide the auth_dispatch callable.
    # WsGateway never imports ApiGateway directly — it receives the callable.
    async def _send_ws(conn_id: str, payload: dict) -> None:
        import json
        ws = registry.get_ws(conn_id)
        if ws:
            try:
                await ws.send(json.dumps(payload))
            except Exception:
                logger.debug("Failed to send to %s", conn_id)

    api_gateway = ApiGateway(
        auth_service=auth_service,
        registry=registry,
        send=_send_ws,
        activity_logger=activity_logger,
    )

    game_allocator = GameAllocator(config=config.allocator)
    room_directory = RoomDirectory(
        host=config.redis.host,
        port=config.redis.port,
    )

    def _session_factory() -> GameSession:
        return GameSession(bus=EventBus(), piece_scores=config.stats.piece_scores)

    ws_gateway = WsGateway(
        session_factory=_session_factory,
        realtime_config=config.realtime,
        registry=registry,
        auth_dispatch=api_gateway.handle_auth,
        elo_service=elo_service,
        matchmaking_config=config.matchmaking,
        activity_logger=activity_logger,
        game_allocator=game_allocator,
        room_directory=room_directory,
    )

    async with websockets.serve(ws_gateway.handle, config.host, config.port):
        logger.info("WS Gateway listening on %s:%s", config.host, config.port)
        await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    asyncio.run(_main())
