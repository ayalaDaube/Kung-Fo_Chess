import unittest
from kungfu_chess.texttests.script_runner import ScriptRunner


def run(script: str) -> list[str]:
    return ScriptRunner(cell_size=100).run(script)


class TestBoardParsing(unittest.TestCase):

    def test_print_initial_board(self):
        errors = run("""
Board
. . .
. wK .
. . .

print board
. . .
. wK .
. . .
""")
        self.assertEqual(errors, [])


class TestRookMove(unittest.TestCase):

    def test_rook_moves_after_wait(self):
        errors = run("""
Board
. wR .
. . .
. . bK

click 150 50
click 150 250
wait 2000
print board
. . .
. . .
. wR bK
""")
        self.assertEqual(errors, [])

    def test_board_unchanged_before_arrival(self):
        errors = run("""
Board
. wR .
. . .
. . bK

click 150 50
click 150 250
wait 999
print board
. wR .
. . .
. . bK
""")
        self.assertEqual(errors, [])


class TestInvalidMove(unittest.TestCase):

    def test_blocked_rook_board_unchanged(self):
        errors = run("""
Board
wR wP .
. . .
. . bK

click 50 50
click 250 50
wait 3000
print board
wR wP .
. . .
. . bK
""")
        self.assertEqual(errors, [])


class TestCapture(unittest.TestCase):

    def test_rook_captures_enemy(self):
        errors = run("""
Board
wR . bK

click 50 50
click 250 50
wait 2000
print board
. . wR
""")
        self.assertEqual(errors, [])

    def test_king_capture_ends_game(self):
        errors = run("""
Board
wR . bK
. . wN
. . .

click 50 50
click 250 50
wait 2000
print board
. . wR
. . wN
. . .

click 250 150
click 50 250
wait 2000
print board
. . wR
. . wN
. . .
""")
        self.assertEqual(errors, [])


class TestJumpAndAirCapture(unittest.TestCase):

    def test_jump_piece_stays_on_board(self):
        errors = run("""
Board
wK . .
. . .
. . .

jump 50 50
wait 500
print board
wK . .
. . .
. . .
""")
        self.assertEqual(errors, [])

    def test_enemy_captures_airborne(self):
        errors = run("""
Board
wK . .
bR . .
. . .

jump 50 50
click 50 150
click 50 50
wait 1000
print board
wK . .
. . .
. . .
""")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
