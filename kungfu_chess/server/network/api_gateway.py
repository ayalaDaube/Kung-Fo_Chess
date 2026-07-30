"""
ApiGateway — stateless request/response tier.

Handles login and register commands only.  Every request arrives, gets a
response, and the connection moves on — no long-lived per-connection state
lives here.

Shares a ConnectionRegistry with WsGateway so that a connection authenticated
here is immediately visible to the live-game tier without any extra handshake.
When the system grows to multiple gateway instances the registry hand-off
becomes a Redis lookup; that swap happens in one place (the wiring in main.py),
not inside either gateway.

SRP: this class knows nothing about rooms, moves, matchmaking, or tick loops.
"""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

from kungfu_chess.server.auth.auth_handler import AuthHandler
from kungfu_chess.server.auth.auth_service import AuthService
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    LoginCommand, RegisterCommand, MSG_ERROR,
)

logger = logging.getLogger(__name__)

SendFn = Callable[[str, dict], Awaitable[None]]


class ApiGateway:
    """
    Stateless request/response gateway.

    Processes CMD_LOGIN and CMD_REGISTER, marks the connection as
    authenticated in the shared ConnectionRegistry, and replies with
    MSG_LOGGED_IN / MSG_REGISTERED / MSG_ERROR.

    Parameters
    ----------
    auth_service
        The AuthService to delegate credential checks to.
    registry
        Shared ConnectionRegistry — the same instance WsGateway holds.
        ApiGateway writes login state here; WsGateway reads it.
    send
        Async callable (conn_id, payload) for sending a reply.
    activity_logger
        Optional structured logger.
    """

    def __init__(
        self,
        auth_service: AuthService,
        registry: ConnectionRegistry,
        send: SendFn,
        activity_logger: ActivityLogger | None = None,
    ) -> None:
        self._registry = registry
        self._handler = AuthHandler(
            auth_service=auth_service,
            registry=registry,
            send=send,
            activity_logger=activity_logger,
        )

    async def handle_auth(
        self, conn_id: str, command: LoginCommand | RegisterCommand,
    ) -> None:
        """Route a login or register command to AuthHandler."""
        await self._handler.handle(conn_id, command)

    async def handle_no_auth(self, conn_id: str, send: SendFn) -> None:
        """Send MSG_ERROR when auth is not configured (no AuthService injected)."""
        await send(conn_id, {"type": MSG_ERROR, "reason": "auth not configured"})
