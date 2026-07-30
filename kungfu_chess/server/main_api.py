"""
API Gateway entry point.

Runs ApiGateway only: login, register, stateless request/response.
No GameSession, RoomManager, TickLoop, or Matchmaker — ApiGateway has
never needed these.

Uses RedisConnectionRegistry so login state written here is immediately
visible to the WsGateway process reading the same Redis instance.

Start with:
    python -m kungfu_chess.server.main_api
Or via docker-compose: the api-gateway service.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os

import websockets

from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.auth.elo_cache import EloCache
from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.api_gateway import ApiGateway
from kungfu_chess.server.network.protocol import (
    parse_incoming_message, ProtocolError,
    LoginCommand, RegisterCommand, MSG_ERROR,
)
from kungfu_chess.server.network.redis_connection_registry import RedisConnectionRegistry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_API_PORT_DEFAULT = 8766


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
    api_port = int(os.environ.get("API_PORT", str(_API_PORT_DEFAULT)))

    repo = _build_repo(config)
    elo_cache = EloCache(
        host=config.redis.host,
        port=config.redis.port,
        ttl_seconds=config.redis.elo_ttl_seconds,
    )
    auth_service = AuthService(repo=repo, config=config.auth, elo_cache=elo_cache)
    activity_logger = ActivityLogger(config.logging.log_path)

    registry = RedisConnectionRegistry(
        host=config.redis.host,
        port=config.redis.port,
    )

    async def _send(conn_id: str, payload: dict) -> None:
        ws = registry.get_ws(conn_id)
        if ws:
            try:
                await ws.send(json.dumps(payload))
            except Exception:
                logger.debug("Failed to send to %s", conn_id)

    gateway = ApiGateway(
        auth_service=auth_service,
        registry=registry,
        send=_send,
        activity_logger=activity_logger,
    )

    async def _handle(ws) -> None:
        conn_id = str(id(ws))
        registry.register(conn_id, ws)
        logger.info("API connection opened: %s", conn_id)
        try:
            async for raw in ws:
                result = parse_incoming_message(raw)
                if isinstance(result, ProtocolError):
                    await _send(conn_id, {"type": MSG_ERROR, "reason": result.reason})
                    continue
                if isinstance(result, (LoginCommand, RegisterCommand)):
                    await gateway.handle_auth(conn_id, result)
                else:
                    await gateway.handle_no_auth(conn_id, _send)
        finally:
            registry.forget(conn_id)
            logger.info("API connection closed: %s", conn_id)

    async with websockets.serve(_handle, config.host, api_port):
        logger.info("API Gateway listening on %s:%s", config.host, api_port)
        await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    asyncio.run(_main())
