"""
Authentication service — registration and login only.
No WebSocket, JSON, or protocol knowledge. No direct SQLite access.
All blocking DB calls are wrapped in asyncio.to_thread at the call site here.
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from enum import Enum

import bcrypt

from kungfu_chess.server.auth.db import UserRecord, UserRepository
from kungfu_chess.server.auth.elo_cache import EloCache
from kungfu_chess.server.auth.constants import PASSWORD_MAX_LEN
from kungfu_chess.server.config import AuthConfig

logger = logging.getLogger(__name__)


# ── result types ──────────────────────────────────────────────────────────────

class RegisterStatus(Enum):
    SUCCESS           = "success"
    DUPLICATE         = "duplicate_username"
    INVALID_INPUT     = "invalid_input"


class LoginStatus(Enum):
    SUCCESS           = "success"
    INVALID_CREDENTIALS = "invalid_credentials"


@dataclass(frozen=True)
class RegisterResult:
    status: RegisterStatus
    message: str
    user: UserRecord | None = None   # populated on SUCCESS only


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    user: UserRecord | None   # populated on SUCCESS only


# ── service ───────────────────────────────────────────────────────────────────

_PASSWORD_MAX_LEN = PASSWORD_MAX_LEN


class AuthService:
    """
    Handles registration and login.
    Takes a UserRepository so tests can inject InMemoryUserRepository
    without touching a real database or using monkeypatching.
    Optional EloCache: on successful login the ELO is cached; on cache hit
    the DB lookup is skipped.  If the cache is unavailable the service
    falls back to the DB transparently (fail-open).
    """

    def __init__(
        self,
        repo: UserRepository,
        config: AuthConfig,
        elo_cache: EloCache | None = None,
    ) -> None:
        self._repo = repo
        self._config = config
        self._cache = elo_cache

    async def register(self, username: str, password: str) -> RegisterResult:
        if not username or not password:
            return RegisterResult(RegisterStatus.INVALID_INPUT, "username and password are required")
        if len(password) > _PASSWORD_MAX_LEN:
            return RegisterResult(RegisterStatus.INVALID_INPUT,
                                  f"password must be at most {_PASSWORD_MAX_LEN} characters")

        existing = await asyncio.to_thread(self._repo.get_user_by_username, username)
        if existing is not None:
            return RegisterResult(RegisterStatus.DUPLICATE, "username already taken")

        password_hash = await asyncio.to_thread(
            bcrypt.hashpw, password.encode(), bcrypt.gensalt()
        )
        await asyncio.to_thread(
            self._repo.create_user, username, password_hash.decode(), self._config.default_starting_elo
        )
        user = UserRecord(username=username, password_hash=password_hash.decode(),
                          elo=self._config.default_starting_elo)
        return RegisterResult(RegisterStatus.SUCCESS, "registered successfully", user=user)

    async def login(self, username: str, password: str) -> LoginResult:
        # Check Redis cache first — if we have a cached ELO we still need
        # the password_hash from the DB to verify, so the cache only saves
        # us the get_user_by_username call when the user is already known.
        cached_elo = await asyncio.to_thread(self._cache.get, username) if self._cache else None
        user = await asyncio.to_thread(self._repo.get_user_by_username, username)
        if user is None:
            return LoginResult(LoginStatus.INVALID_CREDENTIALS, None)
        password_matches = await asyncio.to_thread(
            bcrypt.checkpw, password.encode(), user.password_hash.encode()
        )
        if not password_matches:
            return LoginResult(LoginStatus.INVALID_CREDENTIALS, None)
        # Populate cache on successful login.
        elo = cached_elo if cached_elo is not None else user.elo
        if self._cache is not None:
            await asyncio.to_thread(self._cache.set, username, user.elo)
        result_user = UserRecord(
            username=user.username,
            password_hash=user.password_hash,
            elo=elo,
        )
        return LoginResult(LoginStatus.SUCCESS, result_user)

