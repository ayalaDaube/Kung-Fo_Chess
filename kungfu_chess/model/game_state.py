from __future__ import annotations
from dataclasses import dataclass, field
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
    motion_progress: float = 1.0
    target_cell: Optional[Position] = None
    """Destination cell while mid-motion; None when settled.
    PieceLayer uses cell + target_cell + motion_progress to interpolate pixel position.
    0.0 = motion just started, 1.0 = settled/not moving."""


@dataclass(frozen=True)
class MoveRecord:
    """A single move entry for the move history table."""
    elapsed_ms: int
    notation: str   # e.g. 'Ne4', 'Pxd5'
    color: PieceColor


@dataclass
class GameSnapshot:
    """Read-only snapshot (DTO) passed to Renderer and BoardPrinter."""
    board_width: int
    board_height: int
    pieces: list[PieceSnapshot]
    selected_cell: Optional[Position]
    game_over: bool
    airborne_pos: Optional[Position]
    scores: dict = field(default_factory=dict)          # PieceColor -> int
    move_history: list = field(default_factory=list)    # list[MoveRecord]
    winner_color: Optional[PieceColor] = None
    """Set when game_over is True and the outcome is known (e.g. resignation).
    None for a natural king-capture ending — the board itself shows the result."""
