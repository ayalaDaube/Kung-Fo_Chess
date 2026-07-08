"""
חוקי תנועה לכל סוגי הכלים.

הערה: הפונקציות כאן בודקות רק את *צורת* התנועה (המרחק בין המשבצות),
ולא בודקות חסימות בדרך (למשל צריח שצריך "לקפוץ" מעל כלי אחר על הלוח).
אם המשחק אמור לתמוך בחסימות, יש להוסיף את הבדיקה הזו בנפרד.

עיצוב: כל כלי מיושם כ-Strategy (PieceMovement). RuleEngine טוען רשימת
PieceType ומספק את חוק התנועה לפי קוד הכלי. להוספת כלי חדש - מחלקה חדשה
שיורשת מ-PieceMovement, PieceType חדש, והוספה ל-RuleEngine.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class PieceMovement(ABC):
    """ממשק בסיס לכל חוקי תנועה. כל כלי מממש is_legal בעצמו."""

    @abstractmethod
    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        pass  # pragma: no cover


class KingMovement(PieceMovement):
    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        dr, dc = abs(to_r - from_r), abs(to_c - from_c)
        return (dr <= 1 and dc <= 1) and (dr, dc) != (0, 0)


class RookMovement(PieceMovement):
    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        dr, dc = abs(to_r - from_r), abs(to_c - from_c)
        return (dr == 0 or dc == 0) and (dr, dc) != (0, 0)


class BishopMovement(PieceMovement):
    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        dr, dc = abs(to_r - from_r), abs(to_c - from_c)
        return dr == dc and (dr, dc) != (0, 0)


class QueenMovement(PieceMovement):
    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        return (
            RookMovement().is_legal(from_r, from_c, to_r, to_c, piece_code, game)
            or BishopMovement().is_legal(from_r, from_c, to_r, to_c, piece_code, game)
        )


class KnightMovement(PieceMovement):
    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        dr, dc = abs(to_r - from_r), abs(to_c - from_c)
        return (dr == 2 and dc == 1) or (dr == 1 and dc == 2)


class PawnMovement(PieceMovement):
    """
    config אופציונלי עם שדות:
      direction  : 1 או -1 (ברירת מחדל: -1 ללבן, 1 לשחור לפי piece_code)
      start_row  : שורת ההתחלה לצעד כפול (ברירת מחדל: num_rows-1 ללבן, 0 לשחור)
    """

    def is_legal(self, from_r, from_c, to_r, to_c, piece_code, game, config=None):
        color = piece_code[0]
        cfg = config or {}
        direction = cfg.get("direction", -1 if color == "w" else 1)
        start_row = cfg.get("start_row", game.num_rows() - 1 if color == "w" else 0)
        dr = to_r - from_r
        dc = to_c - from_c

        if dc == 0 and dr == direction:
            return game.get_piece(to_r, to_c) == "."

        if dc == 0 and dr == 2 * direction and from_r == start_row:
            return game.get_piece(to_r, to_c) == "." and game.get_piece(from_r + direction, from_c) == "."

        if abs(dc) == 1 and dr == direction:
            target = game.get_piece(to_r, to_c)
            return target != "." and target[0] != color

        return False


@dataclass
class PieceType:
    """מגדיר סוג כלי: שם קריא, קוד (תו אחד), חוק תנועה, וקונפיגורציה אופציונלית."""
    name: str
    code: str
    movement: PieceMovement
    config: Optional[dict] = field(default=None)


class RuleEngine:
    """טוען ומחזיק רשימת PieceType; מספק חוק תנועה לפי קוד כלי."""

    def __init__(self, piece_types):
        self._rules = {pt.code: pt for pt in piece_types}

    def get_piece_type(self, code):
        """מחזיר PieceType לפי קוד (תו אחד), או None אם לא קיים."""
        return self._rules.get(code)

    @staticmethod
    def default():
        """מחזיר RuleEngine עם כלי שחמט סטנדרטיים."""
        return RuleEngine([
            PieceType("King",   "K", KingMovement()),
            PieceType("Rook",   "R", RookMovement()),
            PieceType("Bishop", "B", BishopMovement()),
            PieceType("Queen",  "Q", QueenMovement()),
            PieceType("Knight", "N", KnightMovement()),
            PieceType("Pawn",   "P", PawnMovement()),
        ])


def is_legal_move(piece_code, from_r, from_c, to_r, to_c, game, engine):
    """נקודת הכניסה היחידה לבדיקת חוקיות מהלך - מנתבת לפי סוג הכלי."""
    piece_type = engine.get_piece_type(piece_code[1])
    if piece_type is None:
        return False
    return piece_type.movement.is_legal(from_r, from_c, to_r, to_c, piece_code, game, piece_type.config)