"""
State של המשחק הרץ - מופרד מנקודת הכניסה כדי לאפשר ייבוא נקי.
"""

from enum import Enum


class ActionType(Enum):
    MOVE = "move"
    JUMP = "jump"


class PendingAction:
    """מייצגת פעולה שהתחילה אך טרם הסתיימה (move או jump)."""

    def __init__(self, action_type, piece, from_pos, remaining_time, to_pos=None):
        self.action_type = action_type
        self.piece = piece
        self.from_pos = from_pos
        self.to_pos = to_pos
        self.remaining_time = remaining_time


class ChessGame:
    """מחזיקה את כל ה-state של המשחק הרץ."""

    def __init__(self, board):
        self._board = board
        self.selected_piece = None
        self.game_time = 0
        self.pending_action = None
        self.airborne_piece = None
        self.ms_per_square = 500
        self.jump_duration_ms = 1000
        self.cell_size_px = 100

    def get_piece(self, r, c):
        return self._board[r][c]

    def set_piece(self, r, c, piece):
        self._board[r][c] = piece

    def num_rows(self):
        return len(self._board)

    def num_cols(self):
        return len(self._board[0])
