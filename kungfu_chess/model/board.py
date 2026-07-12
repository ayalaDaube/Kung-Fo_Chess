from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceState


class Board:
    """
    Owns the logical arrangement of pieces.
    Knows what exists; does not decide which moves are legal.
    """

    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height
        self._grid: dict[Position, Piece] = {}

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.row < self._height and 0 <= pos.col < self._width

    def get_piece(self, pos: Position) -> Optional[Piece]:
        return self._grid.get(pos)

    def add_piece(self, piece: Piece) -> None:
        if piece.cell in self._grid:
            raise ValueError(f"Cell {piece.cell} already occupied")
        self._grid[piece.cell] = piece

    def remove_piece(self, pos: Position) -> Optional[Piece]:
        return self._grid.pop(pos, None)

    def move_piece(self, from_pos: Position, to_pos: Position) -> Optional[Piece]:
        """
        Assumes validation has already occurred.
        Returns the captured piece (if any), or None.
        """
        piece = self._grid.pop(from_pos)
        captured = self._grid.get(to_pos)
        if captured:
            captured.state = PieceState.CAPTURED
            del self._grid[to_pos]
        self._grid[to_pos] = piece
        piece.cell = to_pos
        return captured

    def all_pieces(self) -> list[Piece]:
        return list(self._grid.values())
