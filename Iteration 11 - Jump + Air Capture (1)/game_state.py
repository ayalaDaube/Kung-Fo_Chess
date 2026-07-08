"""
State של המשחק הרץ - מופרד מנקודת הכניסה כדי לאפשר ייבוא נקי.
"""


class ChessGame:
    """מחזיקה את כל ה-state של המשחק הרץ."""

    def __init__(self, board):
        self.board = board
        self.selected_piece = None
        self.game_time = 0
        self.pending_action = None
        self.airborne_piece = None
        self.ms_per_square = 500
        self.jump_duration_ms = 1000
