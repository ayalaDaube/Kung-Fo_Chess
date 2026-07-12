from kungfu_chess.model.board import Board
from kungfu_chess.model.piece import PieceState


class BoardPrinter:
    """Responsible for converting logical board state to text. Has no knowledge of pixels or animation."""

    def to_string(self, board: Board) -> str:
        rows = []
        for r in range(board.height):
            row = []
            for c in range(board.width):
                from kungfu_chess.model.position import Position
                piece = board.get_piece(Position(r, c))
                if piece is None or piece.state == PieceState.CAPTURED:
                    row.append(".")
                else:
                    row.append(piece.code)
            rows.append(" ".join(row))
        return "\n".join(rows)

    def print(self, board: Board) -> None:
        print(self.to_string(board))
