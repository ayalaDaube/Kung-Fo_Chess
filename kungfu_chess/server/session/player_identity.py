"""
Player identity types for GameSession.

PlayerRecord holds all stable per-player state keyed by username (not
connection_id). The connection_id is a separate, rebindable field so a
reconnecting player can be matched to their existing record without
creating a duplicate entry.

IdentityResolver is the seam that decides *how* a raw join name maps to
a canonical player identity. The default resolver is the identity function
(username unchanged). A future resolver can verify against AuthService
without any change to GameSession internals.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Optional

from kungfu_chess.model.piece import PieceColor


@dataclass
class PlayerRecord:
    """All stable state for one player in a game, keyed by username."""
    username: str
    color: PieceColor
    connection_id: Optional[str] = field(default=None)   # rebindable on reconnect


# Resolves a raw join name to a canonical player identity string.
# Default: identity function (returns the name unchanged).
# Future: could verify a session token against AuthService.
IdentityResolver = Callable[[str], str]


def default_identity_resolver(raw_name: str) -> str:
    """Returns the name unchanged — no verification."""
    return raw_name
