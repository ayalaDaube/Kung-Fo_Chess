"""
Responsible for drawing chess pieces and their cooldown bars.
"""
from __future__ import annotations
from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceState
from kungfu_chess.ui.assets.asset_paths import REST_STATES
from kungfu_chess.ui.draw.protocols import AnimatorProtocol, ImageCacheProtocol
from kungfu_chess.ui.draw.draw_utils import blend_overlay


class PieceLayer:
    """Draws each piece sprite and a cooldown bar when the piece is resting."""

    def __init__(self, cell_size: int, offset_x: int, offset_y: int,
                 ui: UiConfig, animator: AnimatorProtocol, cache: ImageCacheProtocol,
                 long_rest_ms: float, short_rest_ms: float):
        self._cell_size      = cell_size
        self._offset_x       = offset_x
        self._offset_y       = offset_y
        self._cooldown_color = ui.cooldown_color if ui else (0, 215, 255, 160)
        self._animator       = animator
        self._cache          = cache
        self._long_rest_ms   = long_rest_ms
        self._short_rest_ms  = short_rest_ms

    def draw(self, canvas: Img, snapshot: GameSnapshot) -> None:
        for piece in snapshot.pieces:
            self._draw_piece(canvas, piece)

    def _pixel_position(self, piece) -> tuple[int, int]:
        cs = self._cell_size
        if piece.target_cell is None:
            col = piece.cell.col
            row = piece.cell.row
        else:
            t   = piece.motion_progress
            col = piece.cell.col + t * (piece.target_cell.col - piece.cell.col)
            row = piece.cell.row + t * (piece.target_cell.row - piece.cell.row)
        return self._offset_x + int(col * cs), self._offset_y + int(row * cs)

    def _draw_piece(self, canvas: Img, piece) -> None:
        cs          = self._cell_size
        sprite_path = self._animator.get_frame(
            piece.id, piece.kind, piece.color, piece.state,
            piece.motion_progress,
        )
        if not sprite_path.exists():
            return
        sprite     = Img()
        sprite.img = self._cache.get(sprite_path, cs, cs, keep_aspect=True)
        x, y = self._pixel_position(piece)
        if 0 <= x < canvas.img.shape[1] and 0 <= y < canvas.img.shape[0]:
            sprite.draw_on(canvas, x, y)
            if piece.state in REST_STATES:
                rest_ms = self._long_rest_ms if piece.state == PieceState.LONG_REST else self._short_rest_ms
                self._draw_cooldown_bar(canvas, x, y, piece, rest_ms)

    def _draw_cooldown_bar(self, canvas: Img, x: int, y: int, piece, rest_duration_ms: float) -> None:
        cs       = self._cell_size
        progress = self._animator.get_rest_progress(
            piece.id, piece.kind, piece.color, piece.state, rest_duration_ms
        )
        filled_h = int(cs * (1.0 - progress))
        if filled_h <= 0:
            return
        x1 = max(x, 0)
        y1 = max(y + cs - filled_h, 0)
        y2 = min(y + cs, canvas.img.shape[0])
        x2 = min(x1 + cs, canvas.img.shape[1])
        roi = canvas.img[y1:y2, x1:x2]
        blend_overlay(roi, self._cooldown_color, self._cooldown_color[3] / 255.0)
