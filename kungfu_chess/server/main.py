# Repository: https://github.com/ayalaDaube/Kung-Fo_Chess
"""Entry point: loads ServerConfig and starts the WebSocket server."""
from __future__ import annotations
import asyncio
import logging
import os

import websockets

from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.elo_service import EloService
from kungfu_chess.server.auth.elo_cache import EloCache
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.session.game_session import GameSession

logging.basicConfig(level=logging.INFO)


def _build_repo(config):
    """
    Select UserRepository implementation via DB_BACKEND env var.
    Defaults to 'sqlite' so existing non-Docker workflow is unchanged.
    """
    backend = os.environ.get("DB_BACKEND", "sqlite").lower()
    if backend == "postgres":
        from kungfu_chess.server.auth.db import PostgresUserRepository
        logging.info("Using PostgresUserRepository")
        return PostgresUserRepository(
            host=config.database.host,
            port=config.database.port,
            user=config.database.user,
            password=config.database.password,
            dbname=config.database.dbname,
        )
    from kungfu_chess.server.auth.db import SqliteUserRepository
    logging.info("Using SqliteUserRepository (%s)", config.auth.sqlite_db_path)
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

    def _session_factory() -> GameSession:
        return GameSession(bus=EventBus(), piece_scores=config.stats.piece_scores)

    router = ConnectionRouter(
        session_factory=_session_factory,
        realtime_config=config.realtime,
        auth_service=auth_service,
        elo_service=elo_service,
        matchmaking_config=config.matchmaking,
        activity_logger=activity_logger,
    )

    async with websockets.serve(router.handle, config.host, config.port):
        logging.info("Kung-Fo Chess server listening on %s:%s", config.host, config.port)
        await asyncio.get_running_loop().create_future()  # run forever


if __name__ == "__main__":
    asyncio.run(_main())
