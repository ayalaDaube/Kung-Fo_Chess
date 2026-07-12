from dataclasses import dataclass
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceKind, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


@dataclass(frozen=True)
class MoveResult:
    is_accepted: bool
    reason: str  # "ok" | "game_over" | "motion_in_progress" | reason from RuleEngine


@dataclass
class GameSnapshot:
    """Read-only snapshot for Renderer and BoardPrinter."""
    board_width: int
    board_height: int
    pieces: list[dict]   # each piece: kind, color, cell, state, pixel_pos
    selected_cell: Optional[Position]
    game_over: bool
    airborne_pos: Optional[Position]


class GameEngine:
    """
    Application Service: coordinates Board, RuleEngine, and RealTimeArbiter.
    Tracks game-over condition. Contains no piece-specific movement logic.
    """

    def __init__(self, board: Board, rule_engine: RuleEngine, arbiter: RealTimeArbiter):
        self._board = board
        self._rule_engine = rule_engine
        self._arbiter = arbiter
        self._game_over = False
        self._selected_cell: Optional[Position] = None

    @property
    def game_over(self) -> bool:
        return self._game_over

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        if self._game_over:
            return MoveResult(False, "game_over")

        piece = self._board.get_piece(source)
        if piece is None:
            return MoveResult(False, "empty_source")

        if self._arbiter.has_active_motion(piece):
            return MoveResult(False, "motion_in_progress")

        validation = self._rule_engine.validate_move(self._board, source, destination)
        if not validation.is_valid:
            return MoveResult(False, validation.reason)

        self._arbiter.start_motion(piece, source, destination)
        return MoveResult(True, "ok")

    def request_jump(self, pos: Position) -> MoveResult:
        """Sends a piece airborne (jump mechanic)."""
        if self._game_over:
            return MoveResult(False, "game_over")

        piece = self._board.get_piece(pos)
        if piece is None:
            return MoveResult(False, "empty_source")

        if self._arbiter.has_active_motion(piece):
            return MoveResult(False, "motion_in_progress")

        self._arbiter.start_jump(piece, pos)
        return MoveResult(True, "ok")

    def wait(self, ms: int) -> None:
        """Advances simulated time through RealTimeArbiter and handles arrival events."""
        events = self._arbiter.advance_time(ms)
        for event in events:
            if event.captured_piece is not None and event.captured_piece.kind == PieceKind.KING:
                self._game_over = True

    def snapshot(self, cell_size_px: int = 100) -> GameSnapshot:
        """Creates a read-only snapshot for the Renderer."""
        pieces_data = []
        motion_by_piece = {m.piece: m for m in self._arbiter._active_motions}
        for piece in self._board.all_pieces():
            if piece.state == PieceState.CAPTURED:
                continue
            motion = motion_by_piece.get(piece)
            if motion is not None and motion.to_pos is not None:
                # interpolation: pixel position between source and destination
                total_ms = (max(
                    abs(motion.to_pos.row - motion.from_pos.row),
                    abs(motion.to_pos.col - motion.from_pos.col),
                ) * self._arbiter._ms_per_square)
                elapsed = total_ms - motion.remaining_ms
                t = min(elapsed / total_ms, 1.0) if total_ms > 0 else 1.0
                px = (motion.from_pos.col + t * (motion.to_pos.col - motion.from_pos.col)) * cell_size_px
                py = (motion.from_pos.row + t * (motion.to_pos.row - motion.from_pos.row)) * cell_size_px
            else:
                px = piece.cell.col * cell_size_px
                py = piece.cell.row * cell_size_px

            pieces_data.append({
                "id": piece.id,
                "kind": piece.kind,
                "color": piece.color,
                "cell": piece.cell,
                "state": piece.state,
                "pixel_x": px,
                "pixel_y": py,
            })

        return GameSnapshot(
            board_width=self._board.width,
            board_height=self._board.height,
            pieces=pieces_data,
            selected_cell=self._selected_cell,
            game_over=self._game_over,
            airborne_pos=self._arbiter.airborne_position(),
        )
