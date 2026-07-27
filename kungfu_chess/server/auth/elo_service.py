"""
ELO rating service — updates player ratings after a game result.
No WebSocket, JSON, or protocol knowledge. No direct SQLite access.
"""
from __future__ import annotations
import asyncio
import logging

from kungfu_chess.server.auth.db import UserRepository
from kungfu_chess.server.config import AuthConfig

logger = logging.getLogger(__name__)


class EloService:
    def __init__(self, repo: UserRepository, config: AuthConfig) -> None:
        self._repo = repo
        self._config = config

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

        new_winner_elo = round(winner.elo + k * (1.0 - win_probability))
        new_loser_elo  = round(loser.elo  + k * (0.0 - lose_probability))

        await asyncio.to_thread(self._repo.update_elo, winner_username, new_winner_elo)
        await asyncio.to_thread(self._repo.update_elo, loser_username,  new_loser_elo)
