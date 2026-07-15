from dataclasses import dataclass
from enum import Enum
from kungfu_chess.model.position import Position


class PieceColor(Enum):
    WHITE = "w"
    BLACK = "b"


class PieceKind(Enum):
    KING   = "K"
    QUEEN  = "Q"
    ROOK   = "R"
    BISHOP = "B"
    KNIGHT = "N"
    PAWN   = "P"


class PieceState(Enum):
    IDLE       = "idle"
    MOVING     = "moving"
    JUMPING    = "jumping"
    LONG_REST  = "long_rest"
    SHORT_REST = "short_rest"
    CAPTURED   = "captured"


@dataclass
class Piece:
    """
    Represents a chess piece. Responsible for identity and lifecycle state.
    Has no knowledge of pixels, rendering, movement rules, or timing.
    """
    id: str
    color: PieceColor
    kind: PieceKind
    cell: Position
    state: PieceState = PieceState.IDLE
    start_row: int = -1  # set by BoardParser; used by PawnMovement for double-step eligibility

    @property
    def code(self) -> str:
        """Two-character code: color + kind (e.g. 'wK', 'bR')."""
        return self.color.value + self.kind.value
