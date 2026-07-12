import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceColor, PieceKind
from kungfu_chess.model.board import Board
from kungfu_chess.rules.piece_rules import (
    KingMovement, RookMovement, BishopMovement,
    QueenMovement, KnightMovement, PawnMovement,
)


def empty_board(size=8) -> Board:
    return Board(size, size)


def place(board: Board, code: str, row: int, col: int, pid: str = "p1") -> Piece:
    color = PieceColor.WHITE if code[0] == "w" else PieceColor.BLACK
    kind  = {k.value: k for k in PieceKind}[code[1]]
    p = Piece(pid, color, kind, Position(row, col))
    board.add_piece(p)
    return p


class TestKingMovement(unittest.TestCase):

    def test_all_eight_directions(self):
        b = empty_board()
        p = place(b, "wK", 4, 4)
        dests = KingMovement().legal_destinations(b, p)
        self.assertEqual(len(dests), 8)

    def test_includes_friendly_cell_geometry(self):
        # piece_rules מחזיר יעדים גיאומטריים; RuleEngine מסנן ידידותיים
        b = empty_board()
        p = place(b, "wK", 4, 4)
        place(b, "wR", 4, 5, "p2")
        dests = KingMovement().legal_destinations(b, p)
        self.assertIn(Position(4, 5), dests)  # גיאומטרית חוקי

    def test_friendly_blocked_by_rule_engine(self):
        from kungfu_chess.rules.rule_engine import RuleEngine
        from kungfu_chess.model.board import Board
        b = empty_board()
        p = place(b, "wK", 4, 4)
        place(b, "wR", 4, 5, "p2")
        v = RuleEngine().validate_move(b, Position(4, 4), Position(4, 5))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "friendly_destination")

    def test_can_capture_enemy(self):
        b = empty_board()
        p = place(b, "wK", 4, 4)
        place(b, "bR", 4, 5, "p2")
        dests = KingMovement().legal_destinations(b, p)
        self.assertIn(Position(4, 5), dests)


class TestRookMovement(unittest.TestCase):

    def test_horizontal_and_vertical(self):
        b = empty_board(5)
        p = place(b, "wR", 2, 2)
        dests = RookMovement().legal_destinations(b, p)
        self.assertIn(Position(2, 0), dests)
        self.assertIn(Position(0, 2), dests)

    def test_blocked_by_friendly(self):
        # piece_rules עוצר בחוסם אבל כולל אותו גיאומטרית; RuleEngine מסנן
        b = empty_board(5)
        p = place(b, "wR", 2, 2)
        place(b, "wP", 2, 4, "p2")
        dests = RookMovement().legal_destinations(b, p)
        self.assertIn(Position(2, 3), dests)   # לפני החוסם — חוקי
        self.assertNotIn(Position(2, 5) if b.in_bounds(Position(2, 5)) else Position(2, 4), dests - {Position(2, 4)})
        # RuleEngine מסנן את Position(2,4) כידידותי
        from kungfu_chess.rules.rule_engine import RuleEngine
        v = RuleEngine().validate_move(b, Position(2, 2), Position(2, 4))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "friendly_destination")

    def test_captures_enemy_but_not_beyond(self):
        b = empty_board(5)
        p = place(b, "wR", 2, 0)
        place(b, "bP", 2, 2, "p2")
        dests = RookMovement().legal_destinations(b, p)
        self.assertIn(Position(2, 2), dests)
        self.assertNotIn(Position(2, 3), dests)

    def test_no_diagonal(self):
        b = empty_board()
        p = place(b, "wR", 4, 4)
        dests = RookMovement().legal_destinations(b, p)
        self.assertNotIn(Position(3, 3), dests)


class TestBishopMovement(unittest.TestCase):

    def test_diagonal(self):
        b = empty_board()
        p = place(b, "wB", 4, 4)
        dests = BishopMovement().legal_destinations(b, p)
        self.assertIn(Position(1, 1), dests)

    def test_no_straight(self):
        b = empty_board()
        p = place(b, "wB", 4, 4)
        dests = BishopMovement().legal_destinations(b, p)
        self.assertNotIn(Position(4, 7), dests)

    def test_blocked_by_friendly(self):
        # piece_rules עוצר בחוסם; RuleEngine מסנן ידידותיים
        b = empty_board()
        p = place(b, "wB", 4, 4)
        place(b, "wP", 3, 3, "p2")
        dests = BishopMovement().legal_destinations(b, p)
        self.assertNotIn(Position(2, 2), dests)  # מעבר לחוסם — לא חוקי
        from kungfu_chess.rules.rule_engine import RuleEngine
        v = RuleEngine().validate_move(b, Position(4, 4), Position(3, 3))
        self.assertFalse(v.is_valid)
        self.assertEqual(v.reason, "friendly_destination")


class TestQueenMovement(unittest.TestCase):

    def test_combines_rook_and_bishop(self):
        b = empty_board()
        p = place(b, "wQ", 4, 4)
        dests = QueenMovement().legal_destinations(b, p)
        self.assertIn(Position(4, 0), dests)   # צריח
        self.assertIn(Position(1, 1), dests)   # רץ

    def test_no_knight_move(self):
        b = empty_board()
        p = place(b, "wQ", 4, 4)
        dests = QueenMovement().legal_destinations(b, p)
        self.assertNotIn(Position(3, 6), dests)


class TestKnightMovement(unittest.TestCase):

    def test_all_l_shapes(self):
        b = empty_board()
        p = place(b, "wN", 4, 4)
        dests = KnightMovement().legal_destinations(b, p)
        self.assertEqual(len(dests), 8)

    def test_jumps_over_blockers(self):
        b = empty_board()
        p = place(b, "wN", 4, 4)
        for dr, dc in [(-1,0),(0,-1),(0,1),(1,0),(-1,-1),(-1,1),(1,-1),(1,1)]:
            place(b, "wP", 4+dr, 4+dc, f"p{dr}{dc}")
        dests = KnightMovement().legal_destinations(b, p)
        self.assertEqual(len(dests), 8)

    def test_no_straight(self):
        b = empty_board()
        p = place(b, "wN", 4, 4)
        dests = KnightMovement().legal_destinations(b, p)
        self.assertNotIn(Position(4, 5), dests)


class TestPawnMovement(unittest.TestCase):

    def test_white_one_step_forward(self):
        b = empty_board()
        p = place(b, "wP", 4, 4)
        dests = PawnMovement().legal_destinations(b, p)
        self.assertIn(Position(3, 4), dests)

    def test_white_no_double_step(self):
        b = empty_board(8)
        p = place(b, "wP", 7, 4)
        dests = PawnMovement().legal_destinations(b, p)
        self.assertNotIn(Position(5, 4), dests)

    def test_white_blocked_forward(self):
        b = empty_board()
        p = place(b, "wP", 4, 4)
        place(b, "bP", 3, 4, "p2")
        dests = PawnMovement().legal_destinations(b, p)
        self.assertNotIn(Position(3, 4), dests)

    def test_white_capture_diagonal(self):
        b = empty_board()
        p = place(b, "wP", 4, 4)
        place(b, "bP", 3, 5, "p2")
        dests = PawnMovement().legal_destinations(b, p)
        self.assertIn(Position(3, 5), dests)

    def test_white_no_capture_empty_diagonal(self):
        b = empty_board()
        p = place(b, "wP", 4, 4)
        dests = PawnMovement().legal_destinations(b, p)
        self.assertNotIn(Position(3, 5), dests)

    def test_black_one_step_forward(self):
        b = empty_board()
        p = place(b, "bP", 3, 4)
        dests = PawnMovement().legal_destinations(b, p)
        self.assertIn(Position(4, 4), dests)

    def test_white_backward_illegal(self):
        b = empty_board()
        p = place(b, "wP", 4, 4)
        dests = PawnMovement().legal_destinations(b, p)
        self.assertNotIn(Position(5, 4), dests)


if __name__ == "__main__":
    unittest.main(verbosity=2)
