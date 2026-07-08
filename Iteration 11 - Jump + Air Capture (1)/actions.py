"""
פעולות בפועל על הלוח: הזזת כלי, ולכידת כלי מרחף.

עיצוב: הפונקציה הישנה perform_move עשתה שני דברים שונים לגמרי
(לכידת כלי מרחף מול מהלך רגיל) - כאן זה מפוצל לשתי פונקציות ברורות,
ו-perform_move משמשת רק כ"מנתבת" ביניהן.
"""


def capture_airborne_piece(from_r, from_c, game):
    """
    כלי מגיע לתא של כלי שנמצא כרגע 'באוויר' (jump).
    אם הכלי המגיע הוא יריב - הכלי המרחף נלכד (הכלי המגיע נעלם).
    אם הכלי המגיע הוא ידידותי - שום דבר לא קורה (אין לכידה עצמית).
    """
    airborne_r, airborne_c = game.airborne_piece

    arriving_piece = game.board[from_r][from_c]
    airborne_piece = game.board[airborne_r][airborne_c]

    is_enemy = (
        arriving_piece != "."
        and airborne_piece != "."
        and arriving_piece[0] != airborne_piece[0]
    )

    if is_enemy:
        game.board[from_r][from_c] = "."
        game.airborne_piece = None


def move_piece(from_r, from_c, to_r, to_c, game):
    """מהלך רגיל: מעבירה כלי מתא אחד לתא אחר."""
    game.board[to_r][to_c] = game.board[from_r][from_c]
    game.board[from_r][from_c] = "."
    game.selected_piece = None


def perform_move(from_r, from_c, to_r, to_c, game):
    """
    נקודת הכניסה היחידה לביצוע מהלך: מנתבת ללכידת כלי מרחף אם היעד
    הוא התא שבו נמצא כלי מרחף, אחרת מבצעת מהלך רגיל.
    """
    if game.airborne_piece and (to_r, to_c) == game.airborne_piece:
        capture_airborne_piece(from_r, from_c, game)
        return

    move_piece(from_r, from_c, to_r, to_c, game)