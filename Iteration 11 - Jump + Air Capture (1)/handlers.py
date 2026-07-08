"""
מטפלי הפקודות: click, jump, wait.

עיצוב: כל פקודה מטופלת ע"י פונקציה משלה. handle_click פוצל לתתי-פונקציות
כדי שכל אחת תעשה דבר אחד ברור (בחירת כלי / התחלת מהלך).
"""

from movement import is_legal_move, RuleEngine
from actions import perform_move
from game_state import PendingAction, ActionType


def _pixel_to_cell(x, y, cell_size):
    """ממירה קואורדינטות פיקסלים למיקום שורה/עמודה בלוח."""
    return y // cell_size, x // cell_size


def _is_within_board(x, y, game, cell_size):
    max_x, max_y = game.num_cols() * cell_size, game.num_rows() * cell_size
    return 0 <= x < max_x and 0 <= y < max_y


def handle_click(x, y, game, engine=None):
    """
    מטפלת בקליק על הלוח: אם כבר יש כלי נבחר, מנסה להזיז אותו או להחליף
    בחירה; אחרת, בוחרת את הכלי שנלחץ עליו (אם יש).
    """
    if not _is_within_board(x, y, game, game.cell_size_px):
        return

    if game.pending_action and game.pending_action.action_type == ActionType.MOVE:
        return

    row, col = _pixel_to_cell(x, y, game.cell_size_px)
    clicked_piece = game.get_piece(row, col)

    if game.selected_piece:
        _handle_click_with_selection(row, col, clicked_piece, game, engine or RuleEngine.default())
    elif clicked_piece != ".":
        game.selected_piece = (row, col)

def _handle_click_with_selection(row, col, clicked_piece, game, engine):
    """כבר יש כלי נבחר: מחליפה בחירה אם נלחץ כלי חבר, אחרת מנסה להתחיל מהלך."""
    prev_row, prev_col = game.selected_piece
    prev_piece = game.get_piece(prev_row, prev_col)

    is_own_piece = clicked_piece != "." and clicked_piece[0] == prev_piece[0]

    if is_own_piece:
        game.selected_piece = (row, col)
        return

    if is_legal_move(prev_piece, prev_row, prev_col, row, col, game, engine):
        _start_move(prev_piece, prev_row, prev_col, row, col, game)
        game.selected_piece = None
    # אם המהלך לא חוקי - הבחירה נשמרת, המשתמש יכול לנסות תא אחר


def _start_move(piece, from_row, from_col, to_row, to_col, game):
    """יוצרת pending_action מסוג 'move', עם זמן יחסי למרחק שהכלי צריך לעבור."""
    distance = max(abs(to_row - from_row), abs(to_col - from_col))

    game.pending_action = PendingAction(
        action_type=ActionType.MOVE,
        piece=piece,
        from_pos=(from_row, from_col),
        to_pos=(to_row, to_col),
        remaining_time=distance * game.ms_per_square,
    )


def handle_jump(x, y, game):
    """מטפלת בפקודת jump: שולחת כלי 'לאוויר' לזמן קבוע."""
    if game.pending_action:
        return

    row, col = _pixel_to_cell(x, y, game.cell_size_px)
    piece = game.get_piece(row, col)

    if piece == ".":
        return

    game.pending_action = PendingAction(
        action_type=ActionType.JUMP,
        piece=piece,
        from_pos=(row, col),
        remaining_time=game.jump_duration_ms,
    )

    game.airborne_piece = (row, col)
    game.selected_piece = None


def handle_wait(ms, game):
    """מקדמת את זמן המשחק; אם פעולה ממתינה הסתיימה, מבצעת אותה."""
    if not game.pending_action:
        game.game_time += ms
        return

    game.pending_action.remaining_time -= ms

    if game.pending_action.remaining_time <= 0:
        _resolve_pending_action(game)

    game.game_time += ms


def _resolve_pending_action(game):
    """מבצעת את הפעולה שהזמן שלה נגמר, ומנקה את ה-state בהתאם."""
    action = game.pending_action

    if action.action_type == ActionType.MOVE:
        perform_move(
            action.from_pos[0],
            action.from_pos[1],
            action.to_pos[0],
            action.to_pos[1],
            game,
        )
    elif action.action_type == ActionType.JUMP:
        # הקפיצה מסתיימת באותו תא - אין שינוי בלוח כאן.
        # (אם כלי אחר מגיע לתא בזמן שהכלי באוויר, הלכידה מטופלת
        # ב-perform_move דרך game.airborne_piece.)
        pass

    game.pending_action = None
    game.airborne_piece = None