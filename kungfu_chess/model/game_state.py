from dataclasses import dataclass
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState


@dataclass(frozen=True)
class PieceSnapshot:
    """Read-only snapshot of a single piece, passed to Renderer."""
    id: str
    kind: PieceKind
    color: PieceColor
    cell: Position
    state: PieceState
    pixel_x: float
    pixel_y: float


@dataclass
class GameSnapshot:
    """Read-only snapshot (DTO) passed to Renderer and BoardPrinter."""
    board_width: int
    board_height: int
    pieces: list[PieceSnapshot]
    selected_cell: Optional[Position]
    game_over: bool
    airborne_pos: Optional[Position]
