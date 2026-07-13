from __future__ import annotations
from typing import Optional
from kungfu_chess.model.position import Position


class BoardMapper:
    """Responsible for converting pixel coordinates to board cells. Has no knowledge of game rules."""

    def __init__(self, board_width: int, board_height: int, cell_size: int = 100):
        self._board_width = board_width
        self._board_height = board_height
        self._cell_size = cell_size

    def pixel_to_cell(self, x: int, y: int) -> Optional[Position]:
        """Returns a Position if the click is inside the board, otherwise None."""
        col = x // self._cell_size
        row = y // self._cell_size
        if 0 <= row < self._board_height and 0 <= col < self._board_width:
            return Position(row, col)
        return None
