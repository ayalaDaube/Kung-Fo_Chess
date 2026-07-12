from abc import ABC, abstractmethod
from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import Piece


class PieceMovement(ABC):
    """Base interface: computes legal destinations for a given piece on a given board."""

    @abstractmethod
    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        pass  # pragma: no cover


class KingMovement(PieceMovement):
    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        r, c = piece.cell.row, piece.cell.col
        result = set()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                pos = Position(r + dr, c + dc)
                if board.in_bounds(pos):
                    result.add(pos)
        return result


class RookMovement(PieceMovement):
    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        return _sliding_destinations(board, piece, [(0, 1), (0, -1), (1, 0), (-1, 0)])


class BishopMovement(PieceMovement):
    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        return _sliding_destinations(board, piece, [(1, 1), (1, -1), (-1, 1), (-1, -1)])


class QueenMovement(PieceMovement):
    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        return (
            RookMovement().legal_destinations(board, piece)
            | BishopMovement().legal_destinations(board, piece)
        )


class KnightMovement(PieceMovement):
    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        r, c = piece.cell.row, piece.cell.col
        result = set()
        for dr, dc in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
            pos = Position(r + dr, c + dc)
            if board.in_bounds(pos):
                result.add(pos)
        return result


class PawnMovement(PieceMovement):
    """
    Simplified pawn: one step forward, diagonal capture.
    direction and start_row are set in the constructor for flexibility.
    """

    def __init__(self, direction: Optional[int] = None, start_row: Optional[int] = None):
        self._direction = direction
        self._start_row = start_row

    def legal_destinations(self, board: Board, piece: Piece) -> set[Position]:
        from kungfu_chess.model.piece import PieceColor
        r, c = piece.cell.row, piece.cell.col
        direction = self._direction if self._direction is not None else (
            -1 if piece.color == PieceColor.WHITE else 1
        )
        start_row = self._start_row if self._start_row is not None else (
            board.height - 1 if piece.color == PieceColor.WHITE else 0
        )
        result = set()

        # one step forward only — no double step
        fwd = Position(r + direction, c)
        if board.in_bounds(fwd) and board.get_piece(fwd) is None:
            result.add(fwd)

        # diagonal capture — only if a piece occupies the target (friendly/enemy filtered by RuleEngine)
        for dc in (-1, 1):
            diag = Position(r + direction, c + dc)
            if board.in_bounds(diag) and board.get_piece(diag) is not None:
                result.add(diag)

        return result


# ── internal helper ───────────────────────────────────────────────────────────

def _sliding_destinations(board: Board, piece: Piece, directions: list[tuple]) -> set[Position]:
    """Computes destinations for a sliding piece in given directions, stopping on obstruction."""
    result = set()
    for dr, dc in directions:
        r, c = piece.cell.row + dr, piece.cell.col + dc
        while True:
            pos = Position(r, c)
            if not board.in_bounds(pos):
                break
            occupant = board.get_piece(pos)
            if occupant is not None:
                result.add(pos)  # stop here — RuleEngine will filter friendlies by policy
                break
            result.add(pos)
            r += dr
            c += dc
    return result
