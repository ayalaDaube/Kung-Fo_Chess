# Repository: https://github.com/your-org/kung-fo-chess
"""Entry point: loads ServerConfig and starts the WebSocket server."""
from __future__ import annotations
import asyncio
import logging

import websockets

from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.db import SqliteUserRepository
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.connection_router import ConnectionRouter
from kungfu_chess.server.session.game_session import GameSession

logging.basicConfig(level=logging.INFO)


async def _main() -> None:
    config = load_server_config()

    repo = SqliteUserRepository(config.auth.sqlite_db_path)
    auth_service = AuthService(repo=repo, config=config.auth)
    activity_logger = ActivityLogger(config.logging.log_path)

    def _session_factory() -> GameSession:
        return GameSession(bus=EventBus(), piece_scores=config.stats.piece_scores)

    router = ConnectionRouter(
        session_factory=_session_factory,
        realtime_config=config.realtime,
        auth_service=auth_service,
        matchmaking_config=config.matchmaking,
        activity_logger=activity_logger,
    )

    async with websockets.serve(router.handle, config.host, config.port):
        logging.info("Kung-Fo Chess server listening on %s:%s", config.host, config.port)
        await asyncio.get_running_loop().create_future()  # run forever


if __name__ == "__main__":
    asyncio.run(_main())
