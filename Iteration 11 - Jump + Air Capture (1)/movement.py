"""
חוקי תנועה לכל סוגי הכלים.

הערה: הפונקציות כאן בודקות רק את *צורת* התנועה (המרחק בין המשבצות),
ולא בודקות חסימות בדרך (למשל צריח שצריך "לקפוץ" מעל כלי אחר על הלוח).
אם המשחק אמור לתמוך בחסימות, יש להוסיף את הבדיקה הזו בנפרד.
"""


def check_king(dr, dc):
    return (dr <= 1 and dc <= 1) and (dr, dc) != (0, 0)


def check_rook(dr, dc):
    return dr == 0 or dc == 0


def check_bishop(dr, dc):
    return dr == dc


def check_queen(dr, dc):
    return check_rook(dr, dc) or check_bishop(dr, dc)


def check_knight(dr, dc):
    return (dr == 2 and dc == 1) or (dr == 1 and dc == 2)


def check_pawn(from_r, from_c, to_r, to_c, piece_code, board):
    """חוקי חייל: מסובכים יותר כי תלויים בכיוון, שורת התחלה, ואכילה באלכסון."""
    color = piece_code[0]
    direction = -1 if color == "w" else 1
    start_row = len(board) - 1 if color == "w" else 0

    dr = to_r - from_r
    dc = to_c - from_c

    # צעד אחד קדימה - התא חייב להיות ריק
    if dc == 0 and dr == direction:
        return board[to_r][to_c] == "."

    # שני צעדים משורת ההתחלה - שני התאים חייבים להיות ריקים
    if dc == 0 and dr == 2 * direction and from_r == start_row:
        return (
            board[to_r][to_c] == "."
            and board[from_r + direction][from_c] == "."
        )

    # אכילה באלכסון - התא חייב להכיל כלי יריב
    if abs(dc) == 1 and dr == direction:
        target = board[to_r][to_c]
        return target != "." and target[0] != color

    return False


# מיפוי סוג כלי -> פונקציית הבדיקה שלו (עבור כלים שאינם חייל)
_MOVEMENT_RULES = {
    "K": check_king,
    "R": check_rook,
    "B": check_bishop,
    "Q": check_queen,
    "N": check_knight,
}


def is_legal_move(piece_code, from_r, from_c, to_r, to_c, board):
    """נקודת הכניסה היחידה לבדיקת חוקיות מהלך - מנתבת לפי סוג הכלי."""
    piece_type = piece_code[1]

    if piece_type == "P":
        return check_pawn(from_r, from_c, to_r, to_c, piece_code, board)

    dr, dc = abs(to_r - from_r), abs(to_c - from_c)

    rule = _MOVEMENT_RULES.get(piece_type)
    if rule is None:
        return False

    return rule(dr, dc)