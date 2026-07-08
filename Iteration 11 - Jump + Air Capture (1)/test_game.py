"""
טסטים מקיפים למשחק שחמט קונג פו.
מכסה: board_logic, movement, actions, handlers, main (אינטגרציה).
"""

import unittest
import io
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from board_logic import validate_board, is_valid_token, print_board, board_to_string
from movement import is_legal_move, PieceType, RuleEngine, KingMovement, PawnMovement
from actions import perform_move, capture_airborne_piece, move_piece
from handlers import handle_click, handle_wait, handle_jump, _pixel_to_cell, _is_within_board
from game_state import ChessGame, PendingAction, ActionType
from main import parse_input, run_command, main


# ─── עזרים ────────────────────────────────────────────────────────────────────

def make_game(rows):
    board = [r.split() for r in rows]
    return ChessGame(board)


def empty_game(size=8):
    """מחזירה ChessGame עם לוח ריק."""
    return ChessGame([["." for _ in range(size)] for _ in range(size)])


def default_engine():
    return RuleEngine.default()


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
        self.assertEqual(validate_board(["wK wQ", "wR"]), "ERROR ROW_WIDTH_MISMATCH")

    def test_unknown_token(self):
        self.assertEqual(validate_board(["wK XX", "wR wN"]), "ERROR UNKNOWN_TOKEN")

    def test_single_cell_board(self):
        self.assertIsNone(validate_board(["wK"]))

    def test_all_empty(self):
        self.assertIsNone(validate_board([". . .", ". . ."]))


class TestBoardToString(unittest.TestCase):

    def test_format(self):
        game = make_game(["wK .", ". bK"])
        self.assertEqual(board_to_string(game), "wK .\n. bK")

    def test_single_row(self):
        game = make_game(["wR wN"])
        self.assertEqual(board_to_string(game), "wR wN")


class TestPrintBoard(unittest.TestCase):

    def test_output(self):
        game = make_game(["wK .", ". bK"])
        captured = io.StringIO()
        sys.stdout = captured
        try:
            print_board(game)
        finally:
            sys.stdout = sys.__stdout__
        self.assertEqual(captured.getvalue(), "wK .\n. bK\n")


# ══════════════════════════════════════════════════════════════════════════════
# movement
# ══════════════════════════════════════════════════════════════════════════════

class TestRuleEngine(unittest.TestCase):

    def test_default_engine_has_all_standard_pieces(self):
        engine = default_engine()
        for code in ("K", "Q", "R", "B", "N", "P"):
            self.assertIsNotNone(engine.get_piece_type(code))

    def test_unknown_piece_returns_none(self):
        self.assertIsNone(default_engine().get_piece_type("Z"))

    def test_custom_engine_overrides_default(self):
        custom = RuleEngine([PieceType("Dragon", "D", KingMovement())])
        self.assertIsNotNone(custom.get_piece_type("D"))
        self.assertIsNone(custom.get_piece_type("K"))

    def test_piece_type_fields(self):
        pt = PieceType("King", "K", KingMovement())
        self.assertEqual(pt.name, "King")
        self.assertEqual(pt.code, "K")
        self.assertIsNone(pt.config)

    def test_piece_type_with_config(self):
        pt = PieceType("ReversePawn", "P", PawnMovement(), config={"direction": 1, "start_row": 7})
        self.assertEqual(pt.config["direction"], 1)

    def test_pawn_with_custom_direction(self):
        """חייל לבן עם direction=1 (הפוך) - הולך למטה."""
        g = empty_game()
        g.set_piece(3, 4, "wP")
        engine = RuleEngine([PieceType("Pawn", "P", PawnMovement(), config={"direction": 1, "start_row": 0})])
        self.assertTrue(is_legal_move("wP", 3, 4, 4, 4, g, engine))
        self.assertFalse(is_legal_move("wP", 3, 4, 2, 4, g, engine))


class TestKingMovement(unittest.TestCase):

    def _game(self):
        g = empty_game()
        g.set_piece(4, 4, "wK")
        return g

    def test_one_step_all_directions(self):
        g = self._game()
        for dr, dc in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
            self.assertTrue(is_legal_move("wK", 4, 4, 4+dr, 4+dc, g, default_engine()))

    def test_two_steps_illegal(self):
        self.assertFalse(is_legal_move("wK", 4, 4, 4, 6, self._game(), default_engine()))

    def test_no_move(self):
        self.assertFalse(is_legal_move("wK", 4, 4, 4, 4, self._game(), default_engine()))


class TestRookMovement(unittest.TestCase):

    def _game(self):
        g = empty_game()
        g.set_piece(4, 4, "wR")
        return g

    def test_horizontal(self):
        self.assertTrue(is_legal_move("wR", 4, 4, 4, 0, self._game(), default_engine()))

    def test_vertical(self):
        self.assertTrue(is_legal_move("wR", 4, 4, 0, 4, self._game(), default_engine()))

    def test_diagonal_illegal(self):
        self.assertFalse(is_legal_move("wR", 4, 4, 2, 6, self._game(), default_engine()))

    def test_no_move(self):
        self.assertFalse(is_legal_move("wR", 4, 4, 4, 4, self._game(), default_engine()))


class TestBishopMovement(unittest.TestCase):

    def _game(self):
        g = empty_game()
        g.set_piece(4, 4, "wB")
        return g

    def test_diagonal(self):
        self.assertTrue(is_legal_move("wB", 4, 4, 1, 1, self._game(), default_engine()))

    def test_straight_illegal(self):
        self.assertFalse(is_legal_move("wB", 4, 4, 4, 7, self._game(), default_engine()))

    def test_no_move(self):
        self.assertFalse(is_legal_move("wB", 4, 4, 4, 4, self._game(), default_engine()))


class TestQueenMovement(unittest.TestCase):

    def _game(self):
        g = empty_game()
        g.set_piece(4, 4, "wQ")
        return g

    def test_horizontal(self):
        self.assertTrue(is_legal_move("wQ", 4, 4, 4, 0, self._game(), default_engine()))

    def test_diagonal(self):
        self.assertTrue(is_legal_move("wQ", 4, 4, 1, 1, self._game(), default_engine()))

    def test_l_shape_illegal(self):
        self.assertFalse(is_legal_move("wQ", 4, 4, 3, 6, self._game(), default_engine()))


class TestKnightMovement(unittest.TestCase):

    def _game(self):
        g = empty_game()
        g.set_piece(4, 4, "wN")
        return g

    def test_all_l_shapes(self):
        g = self._game()
        for dr, dc in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
            self.assertTrue(is_legal_move("wN", 4, 4, 4+dr, 4+dc, g, default_engine()))

    def test_straight_illegal(self):
        self.assertFalse(is_legal_move("wN", 4, 4, 4, 5, self._game(), default_engine()))


class TestPawnMovement(unittest.TestCase):

    def test_white_one_step_forward(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        self.assertTrue(is_legal_move("wP", 4, 4, 3, 4, g, default_engine()))

    def test_white_two_steps_from_start_row(self):
        g = empty_game(8)
        g.set_piece(7, 4, "wP")
        self.assertTrue(is_legal_move("wP", 7, 4, 5, 4, g, default_engine()))

    def test_white_two_steps_not_from_start_row(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        self.assertFalse(is_legal_move("wP", 4, 4, 2, 4, g, default_engine()))

    def test_white_two_steps_blocked_middle(self):
        g = empty_game()
        g.set_piece(7, 4, "wP")
        g.set_piece(6, 4, "bP")
        self.assertFalse(is_legal_move("wP", 7, 4, 5, 4, g, default_engine()))

    def test_white_forward_blocked(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        g.set_piece(3, 4, "bP")
        self.assertFalse(is_legal_move("wP", 4, 4, 3, 4, g, default_engine()))

    def test_white_capture_diagonal(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        g.set_piece(3, 5, "bP")
        self.assertTrue(is_legal_move("wP", 4, 4, 3, 5, g, default_engine()))

    def test_white_capture_empty_diagonal(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        self.assertFalse(is_legal_move("wP", 4, 4, 3, 5, g, default_engine()))

    def test_white_capture_own_piece(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        g.set_piece(3, 5, "wR")
        self.assertFalse(is_legal_move("wP", 4, 4, 3, 5, g, default_engine()))

    def test_black_one_step_forward(self):
        g = empty_game()
        g.set_piece(3, 4, "bP")
        self.assertTrue(is_legal_move("bP", 3, 4, 4, 4, g, default_engine()))

    def test_black_two_steps_from_start_row(self):
        g = empty_game(8)
        g.set_piece(0, 4, "bP")
        self.assertTrue(is_legal_move("bP", 0, 4, 2, 4, g, default_engine()))

    def test_white_backward_illegal(self):
        g = empty_game()
        g.set_piece(4, 4, "wP")
        self.assertFalse(is_legal_move("wP", 4, 4, 5, 4, g, default_engine()))


class TestUnknownPiece(unittest.TestCase):

    def test_unknown_piece_type_returns_false(self):
        g = empty_game()
        g.set_piece(4, 4, "wZ")
        self.assertFalse(is_legal_move("wZ", 4, 4, 3, 4, g, default_engine()))


# ══════════════════════════════════════════════════════════════════════════════
# actions
# ══════════════════════════════════════════════════════════════════════════════

class TestMovePiece(unittest.TestCase):

    def test_basic_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        move_piece(0, 0, 1, 1, game)
        self.assertEqual(game.get_piece(1, 1), "wK")
        self.assertEqual(game.get_piece(0, 0), ".")

    def test_capture(self):
        game = make_game(["wK bR .", ". . .", ". . ."])
        move_piece(0, 0, 0, 1, game)
        self.assertEqual(game.get_piece(0, 1), "wK")

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
        self.assertEqual(game.get_piece(1, 0), ".")
        self.assertIsNone(game.airborne_piece)

    def test_friendly_no_capture(self):
        game = make_game(["wK . .", "wR . .", ". . ."])
        game.airborne_piece = (0, 0)
        capture_airborne_piece(1, 0, game)
        self.assertEqual(game.get_piece(1, 0), "wR")


class TestPerformMove(unittest.TestCase):

    def test_regular_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        perform_move(0, 0, 1, 1, game)
        self.assertEqual(game.get_piece(1, 1), "wK")

    def test_routes_to_airborne_capture(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        game.airborne_piece = (0, 0)
        perform_move(1, 0, 0, 0, game)
        self.assertEqual(game.get_piece(1, 0), ".")

    def test_no_airborne_does_regular_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        perform_move(0, 0, 2, 2, game)
        self.assertEqual(game.get_piece(2, 2), "wK")


# ══════════════════════════════════════════════════════════════════════════════
# handlers – עזרים
# ══════════════════════════════════════════════════════════════════════════════

class TestPixelToCell(unittest.TestCase):

    def test_origin(self):
        self.assertEqual(_pixel_to_cell(0, 0, 100), (0, 0))

    def test_middle_of_cell(self):
        self.assertEqual(_pixel_to_cell(150, 250, 100), (2, 1))

    def test_exact_boundary(self):
        self.assertEqual(_pixel_to_cell(100, 100, 100), (1, 1))


class TestIsWithinBoard(unittest.TestCase):

    def _game(self):
        return empty_game(8)

    def test_inside(self):
        self.assertTrue(_is_within_board(400, 400, self._game(), 100))

    def test_negative_x(self):
        self.assertFalse(_is_within_board(-1, 400, self._game(), 100))

    def test_negative_y(self):
        self.assertFalse(_is_within_board(400, -1, self._game(), 100))

    def test_exact_max_x(self):
        self.assertFalse(_is_within_board(800, 400, self._game(), 100))

    def test_exact_max_y(self):
        self.assertFalse(_is_within_board(400, 800, self._game(), 100))


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
        handle_click(0, 0, game)
        handle_click(100, 0, game)
        self.assertIsNotNone(game.pending_action)
        self.assertEqual(game.pending_action.action_type, ActionType.MOVE)

    def test_illegal_move_keeps_selection(self):
        game = self._game()
        handle_click(0, 0, game)
        handle_click(200, 0, game)
        self.assertEqual(game.selected_piece, (0, 0))

    def test_switch_selection_to_own_piece(self):
        game = make_game(["wK wQ .", ". . .", ". . ."])
        handle_click(0, 0, game)
        handle_click(100, 0, game)
        self.assertEqual(game.selected_piece, (0, 1))

    def test_click_ignored_during_pending_move(self):
        game = self._game()
        handle_click(0, 0, game)
        handle_click(100, 0, game)
        game.selected_piece = None
        handle_click(0, 0, game)
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
        self.assertEqual(game.pending_action.action_type, ActionType.JUMP)

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
        self.assertEqual(game.pending_action.remaining_time, 1000)


# ══════════════════════════════════════════════════════════════════════════════
# handlers – handle_wait
# ══════════════════════════════════════════════════════════════════════════════

class TestHandleWait(unittest.TestCase):

    def _game_with_move(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_click(0, 0, game)
        handle_click(100, 0, game)
        return game

    def test_advances_game_time(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_wait(300, game)
        self.assertEqual(game.game_time, 300)

    def test_partial_wait_does_not_resolve(self):
        game = self._game_with_move()
        handle_wait(200, game)
        self.assertIsNotNone(game.pending_action)

    def test_full_wait_resolves_move(self):
        game = self._game_with_move()
        handle_wait(500, game)
        self.assertIsNone(game.pending_action)
        self.assertEqual(game.get_piece(0, 1), "wK")

    def test_over_wait_resolves_move(self):
        game = self._game_with_move()
        handle_wait(9999, game)
        self.assertEqual(game.get_piece(0, 1), "wK")

    def test_jump_resolves_after_duration(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_jump(0, 0, game)
        handle_wait(1000, game)
        self.assertIsNone(game.pending_action)
        self.assertIsNone(game.airborne_piece)
        self.assertEqual(game.get_piece(0, 0), "wK")

    def test_wait_without_pending_action(self):
        game = make_game(["wK . .", ". . .", ". . ."])
        handle_wait(500, game)
        self.assertEqual(game.game_time, 500)


# ══════════════════════════════════════════════════════════════════════════════
# אינטגרציה – air capture
# ══════════════════════════════════════════════════════════════════════════════

class TestAirCapture(unittest.TestCase):

    def test_enemy_captures_airborne_piece(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        handle_jump(0, 0, game)
        handle_click(0, 100, game)
        handle_click(0, 0, game)
        handle_wait(500, game)
        self.assertEqual(game.get_piece(1, 0), ".")
        self.assertEqual(game.get_piece(0, 0), "wK")

    def test_friendly_no_air_capture(self):
        game = make_game(["wK . .", "wR . .", ". . ."])
        handle_jump(0, 0, game)
        handle_click(0, 100, game)
        handle_click(0, 0, game)
        handle_wait(500, game)
        self.assertEqual(game.get_piece(1, 0), "wR")

    def test_airborne_cleared_after_capture(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        handle_jump(0, 0, game)
        handle_click(0, 100, game)
        handle_click(0, 0, game)
        handle_wait(500, game)
        self.assertIsNone(game.airborne_piece)


# ══════════════════════════════════════════════════════════════════════════════
# main – parse_input, run_command, main()
# ══════════════════════════════════════════════════════════════════════════════

class TestParseInput(unittest.TestCase):

    def test_basic_parse(self):
        board_part, commands_part = parse_input("Board:\nwK . .\n. . .\nCommands:\nprint")
        self.assertIn("wK", board_part)
        self.assertEqual(commands_part, "print")

    def test_multiple_commands(self):
        _, commands_part = parse_input("Board:\nwK .\n. .\nCommands:\nclick 0 0\nwait 500")
        self.assertIn("click", commands_part)
        self.assertIn("wait", commands_part)


class TestRunCommand(unittest.TestCase):

    def _game(self):
        return make_game(["wK . .", ". . .", ". . ."])

    def test_unknown_command_ignored(self):
        run_command("fly 0 0", self._game())

    def test_empty_command_ignored(self):
        run_command("", self._game())

    def test_print_command(self):
        game = self._game()
        captured = io.StringIO()
        sys.stdout = captured
        try:
            run_command("print", game)
        finally:
            sys.stdout = sys.__stdout__
        self.assertIn("wK", captured.getvalue())

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


class TestMain(unittest.TestCase):

    def _run_main(self, input_text):
        captured = io.StringIO()
        sys.stdin = io.StringIO(input_text)
        sys.stdout = captured
        try:
            main()
        finally:
            sys.stdin = sys.__stdin__
            sys.stdout = sys.__stdout__
        return captured.getvalue()

    def test_valid_input_runs(self):
        output = self._run_main("Board:\nwK . .\n. . .\nCommands:\nprint")
        self.assertIn("wK", output)

    def test_invalid_board_prints_error(self):
        output = self._run_main("Board:\nwK XX\n. .\nCommands:\nprint")
        self.assertIn("ERROR", output)

    def test_full_flow_via_stdin(self):
        output = self._run_main(
            "Board:\nwK . .\n. . .\nCommands:\nclick 0 0\nclick 100 0\nwait 500\nprint"
        )
        self.assertIn("wK", output)


# ══════════════════════════════════════════════════════════════════════════════
# אינטגרציה מלאה
# ══════════════════════════════════════════════════════════════════════════════

class TestFullGameFlow(unittest.TestCase):

    def test_jump_then_enemy_arrives(self):
        game = make_game(["wK . .", "bR . .", ". . ."])
        run_command("jump 0 0", game)
        run_command("click 0 100", game)
        run_command("click 0 0", game)
        run_command("wait 500", game)
        run_command("wait 1000", game)
        self.assertEqual(game.get_piece(0, 0), "wK")
        self.assertEqual(game.get_piece(1, 0), ".")


if __name__ == "__main__":
    unittest.main(verbosity=2)
