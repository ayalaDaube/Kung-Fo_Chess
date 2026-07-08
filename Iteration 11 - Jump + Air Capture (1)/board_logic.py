"""
לוגיקת לוח: אימות קלט והדפסה.
קובץ זה אחראי אך ורק על ייצוג הלוח - לא על חוקי תנועה ולא על state של המשחק.
"""

VALID_COLORS = ("w", "b")
VALID_PIECE_TYPES = ("K", "Q", "R", "B", "N", "P")


def validate_board(board_rows):
    """
    מוודאת שהלוח תקין:
    - כל השורות באותו אורך.
    - כל טוקן הוא '.' או קוד כלי חוקי (למשל 'wK', 'bP').

    מחזירה מחרוזת שגיאה אם משהו לא תקין, אחרת None.
    """
    first_row_len = len(board_rows[0].split())

    for row in board_rows:
        tokens = row.split()

        if len(tokens) != first_row_len:
            return "ERROR ROW_WIDTH_MISMATCH"

        for token in tokens:
            if not is_valid_token(token):
                return "ERROR UNKNOWN_TOKEN"

    return None


def is_valid_token(token):
    """בודקת אם טוקן בודד הוא תא ריק או קוד כלי חוקי."""
    if token == ".":
        return True

    if len(token) != 2:
        return False

    color, piece_type = token[0], token[1]
    return color in VALID_COLORS and piece_type in VALID_PIECE_TYPES


def print_board(board):
    """מדפיסה את הלוח, שורה בכל שורת פלט, תאים מופרדים ברווח."""
    for row in board:
        print(" ".join(row))