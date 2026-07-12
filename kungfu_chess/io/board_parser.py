from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceColor, PieceKind, PieceState
from kungfu_chess.model.board import Board

_COLOR_MAP = {"w": PieceColor.WHITE, "b": PieceColor.BLACK}
_KIND_MAP  = {k.value: k for k in PieceKind}
_VALID_COLORS = set(_COLOR_MAP)
_VALID_KINDS  = set(_KIND_MAP)


def _validate(rows: list[list[str]]) -> None:
    width = len(rows[0])
    for r, row in enumerate(rows):
        if len(row) != width:
            raise ValueError("ROW_WIDTH_MISMATCH")
        for token in row:
            if token == ".":
                continue
            if len(token) != 2 or token[0] not in _VALID_COLORS or token[1] not in _VALID_KINDS:
                raise ValueError(f"UNKNOWN_TOKEN: {token}")


class BoardParser:
    """Responsible for converting board text into a Board with Piece objects."""

    def parse(self, text: str) -> Board:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        rows = [line.split() for line in lines]
        _validate(rows)

        height, width = len(rows), len(rows[0])
        board = Board(width, height)
        piece_counter = 0

        for r, row in enumerate(rows):
            for c, token in enumerate(row):
                if token == ".":
                    continue
                color = _COLOR_MAP[token[0]]
                kind  = _KIND_MAP[token[1]]
                piece_counter += 1
                piece = Piece(
                    id=f"p{piece_counter}",
                    color=color,
                    kind=kind,
                    cell=Position(r, c),
                )
                board.add_piece(piece)

        return board
