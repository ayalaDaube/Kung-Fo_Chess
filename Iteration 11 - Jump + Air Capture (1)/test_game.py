"""
טסטים מקיפים למשחק שחמט קונג פו.
מכסה: board_logic, movement, actions, handlers, main (אינטגרציה).
"""

import unittest
from unittest.mock import patch
import io
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from board_logic import validate_board, is_valid_token, print_board
from movement import is_legal_move
from actions import perform_move, capture_airborne_piece, move_piece
from handlers import handle_click, handle_wait, handle_jump, _pixel_to_cell, _is_within_board
from game_state import ChessGame
from main import parse_input, run_command


# ─── עזרים ────────────────────────────────────────────────────────────────────

def make_game(rows):
    """בונה ChessGame מרשימת מחרוזות שורות."""
    board = [r.split() for r in rows]
    return ChessGame(board)


def empty_board(size=8):
    return [["." for _ in range(size)] for _ in range(size)]


# ══════════════════════════════════════════════════════════════════════════════
# board_logic
# ══════════════════════════════════════════════════════════════════════════════

class TestIsValidToken(unittest.TestCase):

    def test_empty_cell(self):
        self.assertTrue(is_valid_token("."))

    def test_all_white_pieces(self):
        for p in ("wK", "wQ", "wR", "wB", "wN", "wP"):
            self.assertTrue(is_valid_token(p))

    def test_all_black_pieces(self):
        for p in ("bK", "bQ", "bR", "bB", "bN", "bP"):
            self.assertTrue(is_valid_token(p))

    def test_wrong_color(self):
        self.assertFalse(is_valid_token("rK"))

    def test_wrong_piece_type(self):
        self.assertFalse(is_valid_token("wX"))

    def test_too_short(self):
        self.assertFalse(is_valid_token("w"))

    def test_too_long(self):
        self.assertFalse(is_valid_token("wKK"))

    def test_empty_string(self):
        self.assertFalse(is_valid_token(""))

    def test_number(self):
        self.assertFalse(is_valid_token("12"))


class TestValidateBoard(unittest.TestCase):

    def test_valid_board(self):
        rows = ["wR wN wB wQ wK wB wN wR",
                "wP wP wP wP wP wP wP wP",
                ". . . . . . . .",
                ". . . . . . . .",
                ". . . . . . . .",
                ". . . . . . . .",
                "bP bP bP bP bP bP bP bP",
                "bR bN bB bQ bK bB bN bR"]
        self.assertIsNone(validate_board(rows))

    def test_row_width_mismatch(self):
        rows = ["wK wQ", "wR"]
        self.assertEqual(validate_board(rows), "ERROR ROW_WIDTH_MISMATCH")

    def test_unknown_token(self):
        rows = ["wK XX", "wR wN"]
        self.assertEqual(validate_board(rows), "ERROR UNKNOWN_TOKEN")

    def test_single_cell_board(self):
        self.assertIsNone(validate_board(["wK"]))

    def test_all_empty(self):
        self.assertIsNone(validate_board([". . .", ". . ."]))


class TestPrintBoard(unittest.TestCase):

    def test_output_format(self):
        board = [["wK", "."], [".", "bK"]]
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            print_board(board)
            self.assertEqual(mock_out.getvalue(), "wK .\n. bK\n")


# ══════════════════════════════════════════════════════════════════════════════
# movement
# ══════════════════════════════════════════════════════════════════════════════

class TestKingMovement(unittest.TestCase):

    def _board(self):
        b = empty_board()
        b[4][4] = "wK"
        return b

    def test_one_step_all_directions(self):
        b = self._board()
        for dr, dc in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            self.assertTrue(is_legal_move("wK", 4, 4, 4+dr, 4+dc, b))

    def test_two_steps_illegal(self):
        b = self._board()
        self.assertFalse(is_legal_move("wK", 4, 4, 4, 6, b))

    def test_no_move(self):
        b = self._board()
        self.assertFalse(is_legal_move("wK", 4, 4, 4, 4, b))


class TestRookMovement(unittest.TestCase):

    def _board(self):
        b = empty_board()
        b[4][4] = "wR"
        return b

    def test_horizontal(self):
        b = self._board()
        self.assertTrue(is_legal_move("wR", 4, 4, 4, 0, b))

    def test_vertical(self):
        b = self._board()
        self.assertTrue(is_legal_move("wR", 4, 4, 0, 4, b))

    def test_diagonal_illegal(self):
        b = self._board()
        self.assertFalse(is_legal_move("wR", 4, 4, 2, 6, b))


class TestBishopMovement(unittest.TestCase):

    def _board(self):
        b = empty_board()
        b[4][4] = "wB"
        return b

    def test_diagonal(self):
        b = self._board()
        self.assertTrue(is_legal_move("wB", 4, 4, 1, 1, b))

    def test_straight_illegal(self):
        b = self._board()
        self.assertFalse(is_legal_move("wB", 4, 4, 4, 7, b))


class TestQueenMovement(unittest.TestCase):

    def _board(self):
        b = empty_board()
        b[4][4] = "wQ"
        return b

    def test_horizontal(self):
        b = self._board()
        self.assertTrue(is_legal_move("wQ", 4, 4, 4, 0, b))

    def test_diagonal(self):
        b = self._board()
        self.assertTrue(is_legal_move("wQ", 4, 4, 1, 1, b))

    def test_l_shape_illegal(self):
        b = self._board()
        self.assertFalse(is_legal_move("wQ", 4, 4, 3, 6, b))


class TestKnightMovement(unittest.TestCase):

    def _board(self):
        b = empty_board()
        b[4][4] = "wN"
        return b

    def test_all_l_shapes(self):
        b = self._board()
        for dr, dc in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
            self.assertTrue(is_legal_move("wN", 4, 4, 4+dr, 4+dc, b))

    def test_straight_illegal(self):
        b = self._board()
        self.assertFalse(is_legal_move("wN", 4, 4, 4, 5, b))


class TestPawnMovement(unittest.TestCase):

    def test_white_one_step_forward(self):
        b = empty_board()
        b[4][4] = "wP"
        self.assertTrue(is_legal_move("wP", 4, 4, 3, 4, b))

    def test_white_two_steps_from_start_row(self):
        b = empty_board(8)
        b[7][4] = "wP"
        self.assertTrue(is_legal_move("wP", 7, 4, 5, 4, b))

    def test_white_two_steps_not_from_start_row(self):
        b = empty_board()
        b[4][4] = "wP"
        self.assertFalse(is_legal_move("wP", 4, 4, 2, 4, b))

    def test_white_two_steps_blocked_middle(self):
        b = empty_board()
        b[7][4] = "wP"
        b[6][4] = "bP"
        self.assertFalse(is_legal_move("wP", 7, 4, 5, 4, b))

    def test_white_forward_blocked(self):
        b = empty_board()
        b[4][4] = "wP"
        b[3][4] = "bP"
        self.assertFalse(is_legal_move("wP", 4, 4, 3, 4, b))

    def test_white_capture_diagonal(self):
        b = empty_board()
        b[4][4] = "wP"
        b[3][5] = "bP"
        self.assertTrue(is_legal_move("wP", 4, 4, 3, 5, b))

    def test_white_capture_empty_diagonal(self):
        b = empty_board()
        b[4][4] = "wP"
        self.assertFalse(is_legal_move("wP", 4, 4, 3, 5, b))

    def test_white_capture_own_piece(self):
        b = empty_board()
        b[4][4] = "wP"
        b[3][5] = "wR"
        self.assertFalse(is_legal_move("wP", 4, 4, 3, 5, b))

    def test_black_one_step_forward(self):
        b = empty_board()
        b[3][4] = "bP"
        self.assertTrue(is_legal_move("bP", 3, 4, 4, 4, b))

    def test_black_two_steps_from_start_row(self):
        b = empty_board(8)
        b[0][4] = "bP"
        self.assertTrue(is_legal_move("bP", 0, 4, 2, 4, b))

    def test_white_backward_illegal(self):
        b = empty_board()
        b[4][4] = "wP"
        self.assertFalse(is_legal_move("wP", 4, 4, 5, 4, b))


# ══════════════════════════════════════════════════════════════════════════════
# actions
# ══════════════════════════════════════════════════════════════════════════════

class TestMovePiece(unittest.TestCase):

    def test_basic_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        move_piece(0, 0, 1, 1, game)
        self.assertEqual(game.board[1][1], "wK")
        self.assertEqual(game.board[0][0], ".")

    def test_capture(self):
        game = make_game(["wK bR .", ". . .", ". . ."])
        move_piece(0, 0, 0, 1, game)
        self.assertEqual(game.board[0][1], "wK")
        self.assertEqual(game.board[0][0], ".")

    def test_clears_selected_piece(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        game.selected_piece = (0, 0)
        move_piece(0, 0, 1, 1, game)
        self.assertIsNone(game.selected_piece)


class TestCaptureAirbornePiece(unittest.TestCase):

    def test_enemy_captures_airborne(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        game.airborne_piece = (0, 0)
        capture_airborne_piece(1, 0, game)
        self.assertEqual(game.board[1][0], ".")
        self.assertIsNone(game.airborne_piece)

    def test_friendly_no_capture(self):
        game = make_game(["wK . .", "wR . .", ". . ."])
        game.airborne_piece = (0, 0)
        capture_airborne_piece(1, 0, game)
        self.assertEqual(game.board[1][0], "wR")

    def test_airborne_piece_cleared_after_capture(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        game.airborne_piece = (0, 0)
        capture_airborne_piece(1, 0, game)
        self.assertIsNone(game.airborne_piece)


class TestPerformMove(unittest.TestCase):

    def test_regular_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        perform_move(0, 0, 1, 1, game)
        self.assertEqual(game.board[1][1], "wK")

    def test_routes_to_airborne_capture(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        game.airborne_piece = (0, 0)
        perform_move(1, 0, 0, 0, game)
        self.assertEqual(game.board[1][0], ".")

    def test_no_airborne_does_regular_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        game.airborne_piece = None
        perform_move(0, 0, 2, 2, game)
        self.assertEqual(game.board[2][2], "wK")


# ══════════════════════════════════════════════════════════════════════════════
# handlers – עזרים
# ══════════════════════════════════════════════════════════════════════════════

class TestPixelToCell(unittest.TestCase):

    def test_origin(self):
        self.assertEqual(_pixel_to_cell(0, 0), (0, 0))

    def test_middle_of_cell(self):
        self.assertEqual(_pixel_to_cell(150, 250), (2, 1))

    def test_exact_boundary(self):
        self.assertEqual(_pixel_to_cell(100, 100), (1, 1))


class TestIsWithinBoard(unittest.TestCase):

    def _board(self):
        return [["." for _ in range(8)] for _ in range(8)]

    def test_inside(self):
        self.assertTrue(_is_within_board(400, 400, self._board()))

    def test_negative_x(self):
        self.assertFalse(_is_within_board(-1, 400, self._board()))

    def test_negative_y(self):
        self.assertFalse(_is_within_board(400, -1, self._board()))

    def test_exact_max_x(self):
        self.assertFalse(_is_within_board(800, 400, self._board()))

    def test_exact_max_y(self):
        self.assertFalse(_is_within_board(400, 800, self._board()))


# ══════════════════════════════════════════════════════════════════════════════
# handlers – handle_click
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleClick(unittest.TestCase):

    def _game(self):
        return make_game(["wK . bK", ". . .", ". . ."])

    def test_select_piece(self):
        game = self._game()
        handle_click(0, 0, game)
        self.assertEqual(game.selected_piece, (0, 0))

    def test_click_empty_no_selection(self):
        game = self._game()
        handle_click(100, 0, game)
        self.assertIsNone(game.selected_piece)

    def test_click_outside_board_ignored(self):
        game = self._game()
        handle_click(9999, 9999, game)
        self.assertIsNone(game.selected_piece)

    def test_legal_move_creates_pending_action(self):
        game = self._game()
        handle_click(0, 0, game)       # בחר wK ב-(0,0)
        handle_click(100, 0, game)     # לחץ על (0,1) - מהלך חוקי למלך
        self.assertIsNotNone(game.pending_action)
        self.assertEqual(game.pending_action["type"], "move")

    def test_illegal_move_keeps_selection(self):
        game = self._game()
        handle_click(0, 0, game)       # בחר wK ב-(0,0)
        handle_click(200, 0, game)     # (0,2) - bK שם, לא ניתן לאכול עם מלך ממרחק 2
        # המהלך לא חוקי (מרחק 2), הבחירה נשמרת
        self.assertEqual(game.selected_piece, (0, 0))

    def test_switch_selection_to_own_piece(self):
        game = make_game(["wK wQ .", ". . .", ". . ."])
        handle_click(0, 0, game)       # בחר wK
        handle_click(100, 0, game)     # לחץ על wQ - החלפת בחירה
        self.assertEqual(game.selected_piece, (0, 1))

    def test_click_ignored_during_pending_move(self):
        game = self._game()
        handle_click(0, 0, game)
        handle_click(100, 0, game)     # יוצר pending_action
        game.selected_piece = None
        handle_click(0, 0, game)       # אמור להיות מוגנוז
        self.assertIsNone(game.selected_piece)


# ══════════════════════════════════════════════════════════════════════════════
# handlers – handle_jump
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleJump(unittest.TestCase):

    def _game(self):
        return make_game(["wK . .", ". . .", ". . ."])

    def test_jump_sets_airborne(self):
        game = self._game()
        handle_jump(0, 0, game)
        self.assertEqual(game.airborne_piece, (0, 0))

    def test_jump_sets_pending_action(self):
        game = self._game()
        handle_jump(0, 0, game)
        self.assertIsNotNone(game.pending_action)
        self.assertEqual(game.pending_action["type"], "jump")

    def test_jump_clears_selection(self):
        game = self._game()
        game.selected_piece = (0, 0)
        handle_jump(0, 0, game)
        self.assertIsNone(game.selected_piece)

    def test_jump_on_empty_cell_ignored(self):
        game = self._game()
        handle_jump(100, 0, game)
        self.assertIsNone(game.airborne_piece)

    def test_jump_ignored_if_pending_action_exists(self):
        game = self._game()
        handle_jump(0, 0, game)
        first_action = game.pending_action
        handle_jump(0, 0, game)
        self.assertIs(game.pending_action, first_action)

    def test_jump_duration(self):
        game = self._game()
        handle_jump(0, 0, game)
        self.assertEqual(game.pending_action["remaining_time"], 1000)


# ══════════════════════════════════════════════════════════════════════════════
# handlers – handle_wait
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleWait(unittest.TestCase):

    def _game_with_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_click(0, 0, game)
        handle_click(100, 0, game)   # מהלך ל-(0,1), מרחק 1 → 500ms
        return game

    def test_advances_game_time(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_wait(300, game)
        self.assertEqual(game.game_time, 300)

    def test_partial_wait_does_not_resolve(self):
        game = self._game_with_move()
        handle_wait(200, game)
        self.assertIsNotNone(game.pending_action)
        self.assertEqual(game.board[0][1], ".")

    def test_full_wait_resolves_move(self):
        game = self._game_with_move()
        handle_wait(500, game)
        self.assertIsNone(game.pending_action)
        self.assertEqual(game.board[0][1], "wK")
        self.assertEqual(game.board[0][0], ".")

    def test_over_wait_resolves_move(self):
        game = self._game_with_move()
        handle_wait(9999, game)
        self.assertEqual(game.board[0][1], "wK")

    def test_jump_resolves_after_duration(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_jump(0, 0, game)
        handle_wait(1000, game)
        self.assertIsNone(game.pending_action)
        self.assertIsNone(game.airborne_piece)
        self.assertEqual(game.board[0][0], "wK")  # הכלי נשאר במקום

    def test_wait_without_pending_action(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_wait(500, game)
        self.assertEqual(game.game_time, 500)
        self.assertIsNone(game.pending_action)


# ══════════════════════════════════════════════════════════════════════════════
# אינטגרציה – air capture
# ══════════════════════════════════════════════════════════════════════════════

class TestAirCapture(unittest.TestCase):

    def test_enemy_captures_airborne_piece(self):
        """כלי שחור מגיע לתא של כלי לבן שקפץ - הכלי השחור נעלם."""
        game = make_game(["wK . .", "bR . .", ". . ."])
        handle_jump(0, 0, game)          # wK קופץ
        handle_click(0, 100, game)       # בחר bR ב-(1,0)
        handle_click(0, 0, game)         # bR מנסה ללכת ל-(0,0) - תא של wK המרחף
        handle_wait(500, game)           # bR מגיע
        self.assertEqual(game.board[1][0], ".")   # bR נעלם
        self.assertEqual(game.board[0][0], "wK")  # wK נשאר

    def test_friendly_no_air_capture(self):
        """כלי לבן לא לוכד כלי לבן מרחף."""
        game = make_game(["wK . .", "wR . .", ". . ."])
        handle_jump(0, 0, game)
        handle_click(0, 100, game)
        handle_click(0, 0, game)
        handle_wait(500, game)
        self.assertEqual(game.board[1][0], "wR")

    def test_airborne_cleared_after_capture(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        handle_jump(0, 0, game)
        handle_click(0, 100, game)
        handle_click(0, 0, game)
        handle_wait(500, game)
        self.assertIsNone(game.airborne_piece)


# ══════════════════════════════════════════════════════════════════════════════
# main – parse_input & run_command
# ══════════════════════════════════════════════════════════════════════════════

class TestParseInput(unittest.TestCase):

    def test_basic_parse(self):
        data = "Board:\nwK . .\n. . .\nCommands:\nprint"
        board_part, commands_part = parse_input(data)
        self.assertIn("wK", board_part)
        self.assertEqual(commands_part, "print")

    def test_multiple_commands(self):
        data = "Board:\nwK .\n. .\nCommands:\nclick 0 0\nwait 500"
        _, commands_part = parse_input(data)
        self.assertIn("click", commands_part)
        self.assertIn("wait", commands_part)


class TestRunCommand(unittest.TestCase):

    def _game(self):
        return make_game(["wK . .", ". . .", ". . ."])

    def test_unknown_command_ignored(self):
        game = self._game()
        run_command("fly 0 0", game)   # לא קורה כלום, אין exception

    def test_empty_command_ignored(self):
        game = self._game()
        run_command("", game)

    def test_print_command(self):
        game = self._game()
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            run_command("print", game)
            self.assertIn("wK", mock_out.getvalue())

    def test_click_command(self):
        game = self._game()
        run_command("click 0 0", game)
        self.assertEqual(game.selected_piece, (0, 0))

    def test_wait_command(self):
        game = self._game()
        run_command("wait 300", game)
        self.assertEqual(game.game_time, 300)

    def test_jump_command(self):
        game = self._game()
        run_command("jump 0 0", game)
        self.assertEqual(game.airborne_piece, (0, 0))


# ══════════════════════════════════════════════════════════════════════════════
# אינטגרציה מלאה – זרימת משחק שלמה
# ══════════════════════════════════════════════════════════════════════════════

class TestFullGameFlow(unittest.TestCase):

    def test_select_move_wait_print(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        run_command("click 0 0", game)
        run_command("click 100 0", game)
        run_command("wait 500", game)
        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            run_command("print", game)
            output = mock_out.getvalue()
        self.assertIn("wK", output)
        self.assertNotIn("wK . .", output.split("\n")[0])

    def test_jump_then_enemy_arrives(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        run_command("jump 0 0", game)
        run_command("click 0 100", game)
        run_command("click 0 0", game)
        run_command("wait 500", game)
        run_command("wait 1000", game)
        self.assertEqual(game.board[0][0], "wK")
        self.assertEqual(game.board[1][0], ".")


if __name__ == "__main__":
    unittest.main(verbosity=2)
