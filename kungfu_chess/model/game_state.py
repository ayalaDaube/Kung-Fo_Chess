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
    pixel_x: float
    pixel_y: float


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
