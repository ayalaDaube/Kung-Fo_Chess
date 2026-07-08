"""
נקודת הכניסה הראשית למשחק: קריאת קלט ולולאת הפקודות.

# Git repo: https://github.com/ayalaDaube/Kung-Fo_Chess
"""

import sys

from handlers import handle_click, handle_wait, handle_jump
from board_logic import validate_board, print_board
from game_state import ChessGame
from movement import RuleEngine


def parse_input(input_data):
    """מפרידה את הקלט לחלק הלוח וחלק הפקודות."""
    parts = input_data.split("Commands:")
    board_part = parts[0].replace("Board:", "").strip()
    commands_part = parts[1].strip()
    return board_part, commands_part


_COMMAND_HANDLERS = {
    "click": lambda args, game, engine: handle_click(int(args[0]), int(args[1]), game, engine),
    "wait":  lambda args, game, engine: handle_wait(int(args[0]), game),
    "print": lambda args, game, engine: print_board(game),
    "jump":  lambda args, game, engine: handle_jump(int(args[0]), int(args[1]), game),
}


def run_command(command, game, engine=None):
    """מריצה פקודה בודדת (click/wait/print/jump) על ה-state של המשחק."""
    parts = command.split()
    if not parts:
        return

    cmd_name, args = parts[0], parts[1:]
    handler = _COMMAND_HANDLERS.get(cmd_name)
    if handler:
        handler(args, game, engine or RuleEngine.default())


def main():
    """קוראת קלט מ-stdin, מאתחלת משחק, ומריצה את כל הפקודות ברצף."""
    input_data = sys.stdin.read()
    board_data, commands_data = parse_input(input_data)

    board_rows = board_data.strip().split("\n")
    error = validate_board(board_rows)
    if error:
        print(error)
        return

    board = [row.split() for row in board_rows]
    game = ChessGame(board)

    for command in commands_data.strip().split("\n"):
        run_command(command, game)


if __name__ == "__main__":  # pragma: no cover
    main()