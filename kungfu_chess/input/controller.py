from dataclasses import dataclass
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.engine.game_engine import GameEngine, MoveResult


@dataclass(frozen=True)
class ControllerResult:
    action: str   # "selected" | "move_requested" | "jump_requested" | "cancelled" | "ignored"
    move_result: Optional[MoveResult] = None


class Controller:
    """
    Responsible for selection state and translating clicks into GameEngine commands.
    Does not decide chess legality and does not modify Board directly.
    """

    def __init__(self, mapper: BoardMapper, engine: GameEngine):
        self._mapper = mapper
        self._engine = engine
        self._selected: Optional[Position] = None

    @property
    def selected_cell(self) -> Optional[Position]:
        return self._selected

    def click(self, x: int, y: int) -> ControllerResult:
        """
        First click: select a piece.
        Second click inside the board: request a move and clear selection.
        Click outside the board with selection: cancel selection.
        Click outside the board without selection: ignore.
        """
        cell = self._mapper.pixel_to_cell(x, y)

        if cell is None:
            if self._selected is not None:
                self._selected = None
                return ControllerResult("cancelled")
            return ControllerResult("ignored")

        if self._selected is None:
            piece = self._engine._board.get_piece(cell)
            if piece is None:
                return ControllerResult("ignored")
            self._selected = cell
            return ControllerResult("selected")

        # second click inside the board
        source = self._selected
        self._selected = None
        result = self._engine.request_move(source, cell)
        return ControllerResult("move_requested", result)

    def jump(self, x: int, y: int) -> ControllerResult:
        """Jump command: sends a piece airborne."""
        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            return ControllerResult("ignored")
        self._selected = None
        result = self._engine.request_jump(cell)
        return ControllerResult("jump_requested", result)
