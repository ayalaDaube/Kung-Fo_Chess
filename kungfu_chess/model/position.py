from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """Value object: a cell coordinate on the board. Has no knowledge of board size, pixels, or movement rules."""
    row: int
    col: int

    def __repr__(self):
        return f"Position(row={self.row}, col={self.col})"
