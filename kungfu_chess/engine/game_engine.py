from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceKind, PieceColor, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.realtime.motion import ArrivalEvent

# Policy types — injectable, no hard-coded logic
PromotionPolicy = Callable[[Piece, Board], None]  # called on arrival; mutates piece if needed
GameOverPolicy = Callable[[ArrivalEvent], bool]   # returns True if this event ends the game


class MoveReason(Enum):
    OK                  = "ok"
    GAME_OVER           = "game_over"
    MOTION_IN_PROGRESS  = "motion_in_progress"
    EMPTY_SOURCE        = "empty_source"
    OUTSIDE_BOARD       = "outside_board"
    FRIENDLY_DEST       = "friendly_destination"
    ILLEGAL_PIECE_MOVE  = "illegal_piece_move"


def default_promotion_policy(piece: Piece, board: Board) -> None:
    """Promotes a pawn that reaches the opposite end of the board to a queen."""
    if piece.kind != PieceKind.PAWN:
        return
    promotion_row = 0 if piece.color == PieceColor.WHITE else board.height - 1
    if piece.cell.row == promotion_row:
        piece.kind = PieceKind.QUEEN


def default_game_over_policy(event: ArrivalEvent) -> bool:
    """Game ends when a king is captured."""
    return event.captured_piece is not None and event.captured_piece.kind == PieceKind.KING


@dataclass(frozen=True)
class MoveResult:
    is_accepted: bool
    reason: MoveReason


class GameEngine:
    """
    Application Service: coordinates Board, RuleEngine, and RealTimeArbiter.
    Tracks game-over condition. Contains no piece-specific movement logic.
    """

    def __init__(self, board: Board, rule_engine: RuleEngine, arbiter: RealTimeArbiter,
                 promotion_policy: PromotionPolicy = default_promotion_policy,
                 game_over_policy: GameOverPolicy = default_game_over_policy):
        self._board = board
        self._rule_engine = rule_engine
        self._arbiter = arbiter
        self._promotion_policy = promotion_policy
        self._game_over_policy = game_over_policy
        self._game_over = False
        self._selected_cell: Optional[Position] = None

    @property
    def game_over(self) -> bool:
        return self._game_over

    def get_piece_at(self, pos: Position):
        """Returns the piece at the given position, or None."""
        return self._board.get_piece(pos)

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        if self._game_over:
            return MoveResult(False, MoveReason.GAME_OVER)

        piece = self._board.get_piece(source)
        if piece is None:
            return MoveResult(False, MoveReason.EMPTY_SOURCE)

        if self._arbiter.has_active_motion(piece):
            return MoveResult(False, MoveReason.MOTION_IN_PROGRESS)

        validation = self._rule_engine.validate_move(self._board, source, destination)
        if not validation.is_valid:
            try:
                reason = MoveReason(validation.reason)
            except ValueError:
                reason = MoveReason.ILLEGAL_PIECE_MOVE
            return MoveResult(False, reason)

        self._arbiter.start_motion(piece, source, destination)
        return MoveResult(True, MoveReason.OK)

    def request_jump(self, pos: Position) -> MoveResult:
        """Sends a piece airborne (jump mechanic)."""
        if self._game_over:
            return MoveResult(False, MoveReason.GAME_OVER)

        piece = self._board.get_piece(pos)
        if piece is None:
            return MoveResult(False, MoveReason.EMPTY_SOURCE)

        if self._arbiter.has_active_motion(piece):
            return MoveResult(False, MoveReason.MOTION_IN_PROGRESS)

        self._arbiter.start_jump(piece, pos)
        return MoveResult(True, MoveReason.OK)

    def wait(self, ms: int) -> None:
        """Advances simulated time through RealTimeArbiter and handles arrival events."""
        events = self._arbiter.advance_time(ms)
        for event in events:
            self._promotion_policy(event.arriving_piece, self._board)
            if self._game_over_policy(event):
                self._game_over = True

    def snapshot(self, cell_size_px: int = 100) -> GameSnapshot:
        """Creates a read-only snapshot for the Renderer."""
        pieces_data = []
        for piece in self._board.all_pieces():
            if piece.state == PieceState.CAPTURED:
                continue
            motion = self._arbiter.get_motion_for(piece)
            if motion is not None and motion.to_pos is not None:
                # interpolation: pixel position between source and destination
                total_ms = (max(
                    abs(motion.to_pos.row - motion.from_pos.row),
                    abs(motion.to_pos.col - motion.from_pos.col),
                ) * self._arbiter.ms_per_square)
                elapsed = total_ms - motion.remaining_ms
                t = min(elapsed / total_ms, 1.0) if total_ms > 0 else 1.0
                px = (motion.from_pos.col + t * (motion.to_pos.col - motion.from_pos.col)) * cell_size_px
                py = (motion.from_pos.row + t * (motion.to_pos.row - motion.from_pos.row)) * cell_size_px
            else:
                px = piece.cell.col * cell_size_px
                py = piece.cell.row * cell_size_px

            pieces_data.append(PieceSnapshot(
                id=piece.id,
                kind=piece.kind,
                color=piece.color,
                cell=piece.cell,
                state=piece.state,
                pixel_x=px,
                pixel_y=py,
            ))

        return GameSnapshot(
            board_width=self._board.width,
            board_height=self._board.height,
            pieces=pieces_data,
            selected_cell=self._selected_cell,
            game_over=self._game_over,
            airborne_pos=self._arbiter.airborne_position(),
        )
