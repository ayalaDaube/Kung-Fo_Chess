from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional

from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand

# A zero-argument callable that returns the latest snapshot (or None before
# the first snapshot arrives).  Injected so Controller never imports
# GameEngine or any networking module.
SnapshotProvider = Callable[[], Optional[GameSnapshot]]


@dataclass(frozen=True)
class ControllerResult:
    action: str   # "selected" | "move_requested" | "jump_requested" | "cancelled" | "ignored"
    command: Optional[MoveCommand | JumpCommand] = None


def _piece_at(snapshot: GameSnapshot, pos: Position):
    """Return the PieceSnapshot at pos, or None."""
    for p in snapshot.pieces:
        if p.cell == pos:
            return p
    return None


class Controller:
    """
    Manages selection state and translates clicks into protocol commands.

    Does NOT call GameEngine directly — it reads piece state from the latest
    GameSnapshot supplied by the injected ``get_snapshot`` callable, and
    produces MoveCommand / JumpCommand values for the caller to send over
    the WebSocket.  The server is the sole authority on whether a move is
    legal; the controller only handles UI selection logic.
    """

    def __init__(self, mapper: BoardMapper, get_snapshot: SnapshotProvider):
        self._mapper = mapper
        self._get_snapshot = get_snapshot
        self._selected: Optional[Position] = None

    @property
    def selected_cell(self) -> Optional[Position]:
        return self._selected

    def click(self, x: int, y: int) -> ControllerResult:
        """
        First click: select a piece.
        Second click inside the board: produce a MoveCommand and clear selection.
        Click outside the board with selection: cancel selection.
        Click outside the board without selection: ignore.
        """
        cell = self._mapper.pixel_to_cell(x, y)
        snapshot = self._get_snapshot()

        if cell is None:
            if self._selected is not None:
                self._selected = None
                return ControllerResult("cancelled")
            return ControllerResult("ignored")

        if self._selected is None:
            if snapshot is None:
                return ControllerResult("ignored")
            piece = _piece_at(snapshot, cell)
            if piece is None or piece.state in (PieceState.LONG_REST, PieceState.SHORT_REST):
                return ControllerResult("ignored")
            self._selected = cell
            return ControllerResult("selected")

        # Second click inside the board — re-select if clicking a same-color piece.
        if snapshot is not None:
            piece = _piece_at(snapshot, cell)
            selected_piece = _piece_at(snapshot, self._selected)
            if (piece is not None and selected_piece is not None
                    and piece.color == selected_piece.color):
                self._selected = cell
                return ControllerResult("selected")

        source = self._selected
        self._selected = None
        return ControllerResult("move_requested", MoveCommand(from_pos=source, to_pos=cell))

    def jump(self, x: int, y: int) -> ControllerResult:
        """Jump command: sends a piece airborne."""
        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            return ControllerResult("ignored")
        self._selected = None
        return ControllerResult("jump_requested", JumpCommand(pos=cell))
