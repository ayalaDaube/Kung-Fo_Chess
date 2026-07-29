"""
AuthHandler — handles login and register commands.

Depends on AuthService and ConnectionRegistry (both injected).
No WebSocket, room, or game knowledge.
"""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

from kungfu_chess.server.auth.auth_service import AuthService, RegisterStatus, LoginStatus
from kungfu_chess.server.logging_.activity_logger import ActivityLogger
from kungfu_chess.server.network.connection_registry import ConnectionRegistry
from kungfu_chess.server.network.protocol import (
    LoginCommand, RegisterCommand,
    MSG_ERROR, MSG_LOGGED_IN, MSG_REGISTERED,
)

logger = logging.getLogger(__name__)

SendFn = Callable[[str, dict], Awaitable[None]]


class AuthHandler:
    """
    Processes login/register commands and updates the ConnectionRegistry.
    """

    def __init__(
        self,
        auth_service: AuthService,
        registry: ConnectionRegistry,
        send: SendFn,
        activity_logger: ActivityLogger | None = None,
    ) -> None:
        self._auth = auth_service
        self._registry = registry
        self._send = send
        self._activity_logger = activity_logger

    async def handle(self, conn_id: str, command: LoginCommand | RegisterCommand) -> None:
        if isinstance(command, RegisterCommand):
            await self._handle_register(conn_id, command)
        else:
            await self._handle_login(conn_id, command)

    async def _handle_register(self, conn_id: str, command: RegisterCommand) -> None:
        result = await self._auth.register(command.username, command.password)
        if result.status == RegisterStatus.SUCCESS:
            self._registry.mark_logged_in(conn_id, result.user.username, result.user.elo)
            await self._send(conn_id, {"type": MSG_REGISTERED, "username": result.user.username, "elo": result.user.elo})
            if self._activity_logger is not None:
                await self._activity_logger.log(
                    "auth_register",
                    {"username": command.username, "outcome": "success"},
                )
        else:
            await self._send(conn_id, {"type": MSG_ERROR, "reason": result.message})
            if self._activity_logger is not None:
                await self._activity_logger.log(
                    "auth_register",
                    {"username": command.username, "outcome": "failure", "reason": result.message},
                )

    async def _handle_login(self, conn_id: str, command: LoginCommand) -> None:
        result = await self._auth.login(command.username, command.password)
        if result.status == LoginStatus.SUCCESS:
            self._registry.mark_logged_in(conn_id, result.user.username, result.user.elo)
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
            await self._send(conn_id, {"type": MSG_ERROR, "reason": "invalid credentials"})
            if self._activity_logger is not None:
                await self._activity_logger.log(
                    "auth_login",
                    {"username": command.username, "outcome": "failure", "reason": "invalid_credentials"},
                )
