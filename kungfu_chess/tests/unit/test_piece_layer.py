"""
Unit tests for PieceLayer._pixel_position — pure interpolation logic, no canvas needed.
"""
from __future__ import annotations
import unittest

from kungfu_chess.model.game_state import PieceSnapshot
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.ui.draw.piece_layer import PieceLayer


def _make_layer(cell_size: int = 100, offset_x: int = 0, offset_y: int = 0) -> PieceLayer:
    return PieceLayer(
        cell_size=cell_size, offset_x=offset_x, offset_y=offset_y,
        ui=None, animator=None, cache=None,
        long_rest_ms=5000, short_rest_ms=2500,
    )


def _make_piece(cell: Position, target_cell: Position | None,
                motion_progress: float = 1.0) -> PieceSnapshot:
    return PieceSnapshot(
        id="p1", kind=PieceKind.ROOK, color=PieceColor.WHITE,
        cell=cell, state=PieceState.IDLE,
        motion_progress=motion_progress,
        target_cell=target_cell,
    )


class TestPixelPosition(unittest.TestCase):

    def test_settled_piece_uses_cell_directly(self):
        layer = _make_layer(cell_size=100, offset_x=0, offset_y=0)
        piece = _make_piece(cell=Position(2, 3), target_cell=None)
        x, y = layer._pixel_position(piece)
        self.assertEqual(x, 300)   # col=3 * 100
        self.assertEqual(y, 200)   # row=2 * 100

    def test_settled_piece_with_offset(self):
        layer = _make_layer(cell_size=100, offset_x=50, offset_y=30)
        piece = _make_piece(cell=Position(0, 0), target_cell=None)
        x, y = layer._pixel_position(piece)
        self.assertEqual(x, 50)
        self.assertEqual(y, 30)

    def test_mid_motion_halfway(self):
        layer = _make_layer(cell_size=100, offset_x=0, offset_y=0)
        # moving from (0,0) to (0,4), halfway through
        piece = _make_piece(cell=Position(0, 0), target_cell=Position(0, 4),
                            motion_progress=0.5)
        x, y = layer._pixel_position(piece)
        self.assertEqual(x, 200)   # col = 0 + 0.5*(4-0) = 2 → 200px
        self.assertEqual(y, 0)

    def test_mid_motion_at_start(self):
        layer = _make_layer(cell_size=100, offset_x=0, offset_y=0)
        piece = _make_piece(cell=Position(1, 1), target_cell=Position(3, 5),
                            motion_progress=0.0)
        x, y = layer._pixel_position(piece)
        self.assertEqual(x, 100)   # col stays at 1
        self.assertEqual(y, 100)   # row stays at 1

    def test_mid_motion_at_end(self):
        layer = _make_layer(cell_size=100, offset_x=0, offset_y=0)
        piece = _make_piece(cell=Position(1, 1), target_cell=Position(3, 5),
                            motion_progress=1.0)
        x, y = layer._pixel_position(piece)
        self.assertEqual(x, 500)   # col=5
        self.assertEqual(y, 300)   # row=3

    def test_diagonal_motion(self):
        layer = _make_layer(cell_size=50, offset_x=10, offset_y=20)
        piece = _make_piece(cell=Position(0, 0), target_cell=Position(2, 2),
                            motion_progress=0.5)
        x, y = layer._pixel_position(piece)
        self.assertEqual(x, 10 + int(1 * 50))   # col=1 → 50 + offset 10
        self.assertEqual(y, 20 + int(1 * 50))   # row=1 → 50 + offset 20


if __name__ == "__main__":
    unittest.main(verbosity=2)
