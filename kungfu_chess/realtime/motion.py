from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceState


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
class EliminationEvent:
    """
    Reported when a piece is eliminated mid-motion (collision or air-capture),
    before reaching its destination. GameEngine removes it from the board.
    """
    piece: Piece
    current_pos: Position


@dataclass(frozen=True)
class ArrivalEvent:
    """
    Arrival event reported from RealTimeArbiter to GameEngine.
    GameEngine is responsible for moving the piece on the board and checking game-over.
    captured_piece and pre_promotion_kind are set by GameEngine after applying the move.
    """
    arriving_piece: Piece
    from_pos: Position
    destination: Position
    captured_piece: Optional[Piece] = None
    pre_promotion_kind: Optional[object] = None  # PieceKind before promotion, for notation


@dataclass(frozen=True)
class RestEvent:
    """
    Reported when a motion finishes and the piece enters a rest state.
    GameEngine is responsible for updating piece.state and scheduling IdleEvent.
    """
    piece: Piece
    rest_state: PieceState  # LONG_REST or SHORT_REST
    duration_ms: int


@dataclass(frozen=True)
class IdleEvent:
    """Reported when a rest period ends. GameEngine sets piece.state = IDLE."""
    piece: Piece
