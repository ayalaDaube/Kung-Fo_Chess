"""
מטפלי הפקודות: click, jump, wait.

עיצוב: כל פקודה מטופלת ע"י פונקציה משלה. handle_click פוצל לתתי-פונקציות
כדי שכל אחת תעשה דבר אחד ברור (בחירת כלי / התחלת מהלך).
"""

from movement import is_legal_move
from actions import perform_move


def _pixel_to_cell(x, y):
    """ממירה קואורדינטות פיקסלים למיקום שורה/עמודה בלוח."""
    return y // 100, x // 100


def _is_within_board(x, y, board):
    num_rows = len(board)
    num_cols = len(board[0])
    max_x, max_y = num_cols * 100, num_rows * 100
    return 0 <= x < max_x and 0 <= y < max_y


def handle_click(x, y, game):
    """
    מטפלת בקליק על הלוח: אם כבר יש כלי נבחר, מנסה להזיז אותו או להחליף
    בחירה; אחרת, בוחרת את הכלי שנלחץ עליו (אם יש).
    """
    if not _is_within_board(x, y, game.board):
        return

    if game.pending_action and game.pending_action["type"] == "move":
        return

    row, col = _pixel_to_cell(x, y)
    clicked_piece = game.board[row][col]

    if game.selected_piece:
        _handle_click_with_selection(row, col, clicked_piece, game)
    elif clicked_piece != ".":
        game.selected_piece = (row, col)

def _handle_click_with_selection(row, col, clicked_piece, game):
    """כבר יש כלי נבחר: מחליפה בחירה אם נלחץ כלי חבר, אחרת מנסה להתחיל מהלך."""
    prev_row, prev_col = game.selected_piece
    prev_piece = game.board[prev_row][prev_col]

    is_own_piece = clicked_piece != "." and clicked_piece[0] == prev_piece[0]

    if is_own_piece:
        game.selected_piece = (row, col)
        return

    if is_legal_move(prev_piece, prev_row, prev_col, row, col, game.board):
        _start_move(prev_piece, prev_row, prev_col, row, col, game)
        game.selected_piece = None
    # אם המהלך לא חוקי - הבחירה נשמרת, המשתמש יכול לנסות תא אחר


def _start_move(piece, from_row, from_col, to_row, to_col, game):
    """יוצרת pending_action מסוג 'move', עם זמן יחסי למרחק שהכלי צריך לעבור."""
    distance = max(abs(to_row - from_row), abs(to_col - from_col))

    game.pending_action = {
        "type": "move",
        "piece": piece,
        "from": (from_row, from_col),
        "to": (to_row, to_col),
        "remaining_time": distance * game.ms_per_square,
    }


def handle_jump(x, y, game):
    """מטפלת בפקודת jump: שולחת כלי 'לאוויר' לזמן קבוע."""
    if game.pending_action:
        return

    row, col = _pixel_to_cell(x, y)
    piece = game.board[row][col]

    if piece == ".":
        return

    game.pending_action = {
        "type": "jump",
        "piece": piece,
        "from": (row, col),
        "remaining_time": game.jump_duration_ms,
    }

    game.airborne_piece = (row, col)
    game.selected_piece = None


def handle_wait(ms, game):
    """מקדמת את זמן המשחק; אם פעולה ממתינה הסתיימה, מבצעת אותה."""
    if not game.pending_action:
        game.game_time += ms
        return

    game.pending_action["remaining_time"] -= ms

    if game.pending_action["remaining_time"] <= 0:
        _resolve_pending_action(game)

    game.game_time += ms


def _resolve_pending_action(game):
    """מבצעת את הפעולה שהזמן שלה נגמר, ומנקה את ה-state בהתאם."""
    action = game.pending_action

    if action["type"] == "move":
        perform_move(
            action["from"][0],
            action["from"][1],
            action["to"][0],
            action["to"][1],
            game,
        )
    elif action["type"] == "jump":
        # הקפיצה מסתיימת באותו תא - אין שינוי בלוח כאן.
        # (אם כלי אחר מגיע לתא בזמן שהכלי באוויר, הלכידה מטופלת
        # ב-perform_move דרך game.airborne_piece.)
        pass

    game.pending_action = None
    game.airborne_piece = None