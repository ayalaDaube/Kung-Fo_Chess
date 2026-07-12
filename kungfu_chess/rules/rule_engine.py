from dataclasses import dataclass
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import PieceKind
from kungfu_chess.rules.piece_rules import (
    PieceMovement, KingMovement, QueenMovement, RookMovement,
    BishopMovement, KnightMovement, PawnMovement,
)


@dataclass(frozen=True)
class MoveValidation:
    is_valid: bool
    reason: str  # "ok" | "outside_board" | "empty_source" | "friendly_destination" | "illegal_piece_move"


class RuleEngine:
    """
    Validates the legality of a requested move — read-only with respect to Board.
    Does not move pieces, does not start motions, has no knowledge of game_over.
    """

    _DEFAULT_MOVEMENTS: dict[PieceKind, PieceMovement] = {
        PieceKind.KING:   KingMovement(),
        PieceKind.QUEEN:  QueenMovement(),
        PieceKind.ROOK:   RookMovement(),
        PieceKind.BISHOP: BishopMovement(),
        PieceKind.KNIGHT: KnightMovement(),
        PieceKind.PAWN:   PawnMovement(),
    }

    def __init__(
        self,
        allow_friendly_capture: bool = False,
        movements: Optional[dict[PieceKind, PieceMovement]] = None,
    ):
        """
        allow_friendly_capture: fixed game policy.
            False (default) = standard chess, capturing friendly pieces is forbidden.
            True = friendly capture allowed (for future rule variants).
        movements: option to replace/extend movement rules for a specific piece kind.
        """
        self._allow_friendly_capture = allow_friendly_capture
        self._movements = movements or dict(self._DEFAULT_MOVEMENTS)

    def validate_move(self, board: Board, source: Position, destination: Position) -> MoveValidation:
        if not board.in_bounds(source) or not board.in_bounds(destination):
            return MoveValidation(False, "outside_board")

        piece = board.get_piece(source)
        if piece is None:
            return MoveValidation(False, "empty_source")

        target = board.get_piece(destination)
        if target is not None and target.color == piece.color and not self._allow_friendly_capture:
            return MoveValidation(False, "friendly_destination")

        movement = self._movements.get(piece.kind)
        if movement is None:
            return MoveValidation(False, "illegal_piece_move")

        legal = movement.legal_destinations(board, piece)
        if destination not in legal:
            return MoveValidation(False, "illegal_piece_move")

        return MoveValidation(True, "ok")
