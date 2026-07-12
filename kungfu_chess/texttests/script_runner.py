from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller


class ScriptRunner:
    """
    Responsible for interpreting the DSL and running it through the public API.
    Does not bypass Controller, GameEngine, or RealTimeArbiter.
    Commands: Board, click, jump, wait, print board.
    """

    def __init__(self, cell_size: int = 100):
        self._cell_size = cell_size
        self._parser = BoardParser()
        self._printer = BoardPrinter()

    def run(self, script: str) -> list[str]:
        """
        Runs a DSL script. Returns a list of comparison errors (empty = all passed).
        """
        lines = [l.rstrip() for l in script.splitlines()]
        errors = []
        i = 0
        engine: GameEngine = None
        controller: Controller = None

        while i < len(lines):
            line = lines[i].strip()

            if line == "Board":
                board_lines, i = self._read_board_lines(lines, i + 1)
                board = self._parser.parse("\n".join(board_lines))
                rule_engine = RuleEngine()
                arbiter = RealTimeArbiter(board, ms_per_square=self._cell_size * 10)
                engine = GameEngine(board, rule_engine, arbiter)
                mapper = BoardMapper(board.width, board.height, self._cell_size)
                controller = Controller(mapper, engine)

            elif line.startswith("click "):
                x, y = int(line.split()[1]), int(line.split()[2])
                controller.click(x, y)
                i += 1

            elif line.startswith("jump "):
                x, y = int(line.split()[1]), int(line.split()[2])
                controller.jump(x, y)
                i += 1

            elif line.startswith("wait "):
                ms = int(line.split()[1])
                engine.wait(ms)
                i += 1

            elif line == "print board":
                expected_lines, i = self._read_board_lines(lines, i + 1)
                actual = self._printer.to_string(engine._board)
                expected = "\n".join(expected_lines)
                if actual != expected:
                    errors.append(f"MISMATCH at line {i}:\nExpected:\n{expected}\nActual:\n{actual}")
            else:
                i += 1

        return errors

    def _read_board_lines(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Reads board lines until an empty line or a new command."""
        result = []
        i = start
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped == "" or stripped in ("print board", "Board") or stripped.startswith(("click ", "jump ", "wait ")):
                break
            result.append(stripped)
            i += 1
        return result, i
