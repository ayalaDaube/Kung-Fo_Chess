from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece


class MotionType(Enum):
    MOVE = "move"
    JUMP = "jump"


@dataclass
class Motion:
    """
    An active movement owned by RealTimeArbiter, outside the Board.
    Stores: type, piece, source, destination (None for JUMP), remaining time.
    Contains no logic — data only.
    """
    motion_type: MotionType
    piece: Piece
    from_pos: Position
    remaining_ms: int
    to_pos: Optional[Position] = None  # None for JUMP

    def set_remaining_ms(self, ms: int) -> None:
        """Allows tests and external code to adjust remaining time without accessing private fields."""
        self.remaining_ms = ms


@dataclass(frozen=True)
class ArrivalEvent:
    """
    Arrival event reported from RealTimeArbiter to GameEngine.
    GameEngine is responsible for checking if captured_piece is a king.
    """
    arriving_piece: Piece
    destination: Position
    captured_piece: Optional[Piece]  # None if no piece was captured
