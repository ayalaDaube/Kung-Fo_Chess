from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceKind, PieceColor, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.realtime.motion import ArrivalEvent, EliminationEvent, RestEvent, IdleEvent
from kungfu_chess.engine.snapshot_builder import build_snapshot, StatsProvider

# Policy types — injectable, no hard-coded logic
PromotionPolicy = Callable[[Piece, Board], None]  # called on arrival; mutates piece if needed
GameOverPolicy = Callable[[Piece], bool]           # returns True if this captured piece ends the game


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


def default_game_over_policy(captured: Piece) -> bool:
    """Game ends when a king is captured."""
    return captured.kind == PieceKind.KING


@dataclass(frozen=True)
class MoveResult:
    is_accepted: bool
    reason: MoveReason


class GameEngine:
    """
    Application Service: coordinates Board, RuleEngine, and RealTimeArbiter.
    Applies board mutations from RealTimeEvents. Tracks game-over condition.
    Contains no piece-specific movement logic.
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
        self._winner_color: Optional[PieceColor] = None

    def force_game_over(self, winner_color: Optional[PieceColor] = None) -> None:
        """
        Force the game-over flag without a capture — used by resignation.
        winner_color is surfaced on the snapshot so clients can tell the
        player the outcome (e.g. after an opponent's auto-resign) instead of
        just a bare "GAME OVER" with no indication of who won.
        """
        self._game_over = True
        self._winner_color = winner_color

    @property
    def game_over(self) -> bool:
        return self._game_over

    @property
    def board(self) -> Board:
        return self._board

    def get_piece_at(self, pos: Position):
        """Returns the piece at the given position, or None."""
        return self._board.get_piece(pos)

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        if self._game_over:
            return MoveResult(False, MoveReason.GAME_OVER)

        piece = self._board.get_piece(source)
        if piece is None:
            return MoveResult(False, MoveReason.EMPTY_SOURCE)

        if self._arbiter.has_active_motion(piece) or piece.state in (PieceState.LONG_REST, PieceState.SHORT_REST):
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

        if self._arbiter.has_active_motion(piece) or piece.state in (PieceState.LONG_REST, PieceState.SHORT_REST):
            return MoveResult(False, MoveReason.MOTION_IN_PROGRESS)

        if self._arbiter.airborne_position() is not None:
            return MoveResult(False, MoveReason.MOTION_IN_PROGRESS)

        self._arbiter.start_jump(piece, pos)
        return MoveResult(True, MoveReason.OK)

    def _apply_elimination(self, event: EliminationEvent) -> None:
        self._board.remove_piece(event.current_pos)
        if self._game_over_policy(event.piece):
            self._game_over = True

    def _apply_arrival(self, event: ArrivalEvent) -> ArrivalEvent:
        # pre_promotion_kind must be captured before calling promotion_policy,
        # because promotion_policy mutates arriving_piece.kind in-place.
        kind_before_promotion = event.arriving_piece.kind
        captured = self._board.move_piece(event.from_pos, event.destination)
        self._promotion_policy(event.arriving_piece, self._board)
        if captured is not None and self._game_over_policy(captured):
            self._game_over = True
        return ArrivalEvent(
            arriving_piece=event.arriving_piece,
            from_pos=event.from_pos,
            destination=event.destination,
            captured_piece=captured,
            pre_promotion_kind=kind_before_promotion,
        )

    def _apply_rest(self, event: RestEvent) -> None:
        event.piece.state = event.rest_state

    def _apply_idle(self, event: IdleEvent) -> None:
        event.piece.state = PieceState.IDLE

    def wait(self, ms: int) -> list:
        """Advances simulated time, applies all resulting board changes, and returns the events."""
        raw_events = self._arbiter.advance_time(ms)
        result = []
        for event in raw_events:
            if isinstance(event, EliminationEvent):
                self._apply_elimination(event)
                result.append(event)
            elif isinstance(event, ArrivalEvent):
                result.append(self._apply_arrival(event))
            elif isinstance(event, RestEvent):
                self._apply_rest(event)
                result.append(event)
            elif isinstance(event, IdleEvent):
                self._apply_idle(event)
                result.append(event)
        return result

    def snapshot(self, selected_cell: Optional[Position] = None,
                 stats: Optional[StatsProvider] = None) -> GameSnapshot:
        """Returns a pixel-agnostic GameSnapshot. The only sanctioned way to read game state."""
        return build_snapshot(self._board, self._arbiter, selected_cell, self._game_over, stats,
                              winner_color=self._winner_color)
