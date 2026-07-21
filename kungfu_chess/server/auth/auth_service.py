"""
Authentication and ELO service.
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


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    user: UserRecord | None   # populated on SUCCESS only


# ── service ───────────────────────────────────────────────────────────────────

_PASSWORD_MAX_LEN = PASSWORD_MAX_LEN


class AuthService:
    """
    Handles registration, login, and ELO updates.
    Takes a UserRepository so tests can inject InMemoryUserRepository
    without touching a real database or using monkeypatching.
    """

    def __init__(self, repo: UserRepository, config: AuthConfig) -> None:
        self._repo = repo
        self._config = config

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
        return RegisterResult(RegisterStatus.SUCCESS, "registered successfully")

    async def login(self, username: str, password: str) -> LoginResult:
        user = await asyncio.to_thread(self._repo.get_user_by_username, username)
        if user is None:
            return LoginResult(LoginStatus.INVALID_CREDENTIALS, None)
        password_matches = await asyncio.to_thread(
            bcrypt.checkpw, password.encode(), user.password_hash.encode()
        )
        if not password_matches:
            return LoginResult(LoginStatus.INVALID_CREDENTIALS, None)
        return LoginResult(LoginStatus.SUCCESS, user)

    async def apply_elo_update(self, winner_username: str, loser_username: str) -> None:
        """Updates both players' ELO using the standard formula. K-factor from config."""
        winner = await asyncio.to_thread(self._repo.get_user_by_username, winner_username)
        loser  = await asyncio.to_thread(self._repo.get_user_by_username, loser_username)
        if winner is None or loser is None:
            logger.warning("ELO update skipped: unknown user(s) %r %r", winner_username, loser_username)
            return

        k = self._config.elo_k_factor
        win_probability  = 1.0 / (1.0 + 10 ** ((loser.elo - winner.elo) / 400.0))
        lose_probability = 1.0 - win_probability

        actual_winner_score = 1.0   # won
        actual_loser_score  = 0.0   # lost

        new_winner_elo = round(winner.elo + k * (actual_winner_score - win_probability))
        new_loser_elo  = round(loser.elo  + k * (actual_loser_score  - lose_probability))

        await asyncio.to_thread(self._repo.update_elo, winner_username, new_winner_elo)
        await asyncio.to_thread(self._repo.update_elo, loser_username,  new_loser_elo)
