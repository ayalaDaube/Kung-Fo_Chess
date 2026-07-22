from __future__ import annotations
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.io.board_printer import BoardPrinter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.config_loader import load_config
from kungfu_chess.server.network.protocol import (
    MoveCommand as ProtocolMoveCommand,
    JumpCommand as ProtocolJumpCommand,
)
from kungfu_chess.texttests.script_parser import (
    ScriptParser, BoardCommand, ClickCommand, JumpCommand, WaitCommand, PrintBoardCommand,
)


class ScriptRunner:
    """
    Responsible for executing parsed DSL commands through the public API.
    Does not bypass Controller, GameEngine, or RealTimeArbiter.
    Delegates all parsing to ScriptParser.
    """

    def __init__(self, cell_size: int = None):
        config = load_config()
        self._config = config
        self._cell_size = cell_size if cell_size is not None else config.cell_size
        self._board_parser = BoardParser()
        self._printer = BoardPrinter()
        self._script_parser = ScriptParser()

    def run(self, script: str) -> list[str]:
        """
        Runs a DSL script. Returns a list of comparison errors (empty = all passed).
        """
        commands = self._script_parser.parse(script)
        errors = []
        board = None
        engine: GameEngine = None
        controller: Controller = None

        for cmd in commands:
            if isinstance(cmd, BoardCommand):
                try:
                    board = self._board_parser.parse("\n".join(cmd.lines))
                except ValueError as e:
                    msg = str(e).split(":")[0]
                    errors.append(f"ERROR {msg}")
                    break
                rule_engine = RuleEngine()
                arbiter = RealTimeArbiter(
                    ms_per_square=500,
                    jump_duration_ms=1000,
                )
                engine = GameEngine(board, rule_engine, arbiter)
                mapper = BoardMapper(board.width, board.height, self._cell_size)
                controller = Controller(mapper, lambda: engine.snapshot())

            elif isinstance(cmd, ClickCommand):
                result = controller.click(cmd.x, cmd.y)
                if result.command is not None:
                    if isinstance(result.command, ProtocolMoveCommand):
                        engine.request_move(result.command.from_pos, result.command.to_pos)
                    elif isinstance(result.command, ProtocolJumpCommand):
                        engine.request_jump(result.command.pos)

            elif isinstance(cmd, JumpCommand):
                result = controller.jump(cmd.x, cmd.y)
                if result.command is not None:
                    engine.request_jump(result.command.pos)

            elif isinstance(cmd, WaitCommand):
                engine.wait(cmd.ms)

            elif isinstance(cmd, PrintBoardCommand):
                actual = self._printer.to_string(board)
                print(actual)
                if cmd.expected_lines:
                    expected = "\n".join(cmd.expected_lines)
                    if actual != expected:
                        errors.append(f"MISMATCH:\nExpected:\n{expected}\nActual:\n{actual}")

        return errors
