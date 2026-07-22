"""
Main rendering coordinator.
Holds a single ImageCache instance and delegates each draw pass to the draw/ layers.

Backward-compatible re-exports kept for existing tests:
  _format_elapsed_ms, _blend_overlay
"""
from __future__ import annotations
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.ui.animator import Animator
from kungfu_chess.ui.draw.image_cache import ImageCache
from kungfu_chess.ui.draw.protocols import DrawLayer, AnimatorProtocol, ImageCacheProtocol
from kungfu_chess.ui.draw.draw_utils import (blend_overlay, format_elapsed_ms, BoardRect,
                                              COORD_FONT_RATIO, SCORE_FONT_RATIO,
                                              HEADER_FONT_RATIO, ROW_FONT_RATIO,
                                              COORD_PAD_DIVISOR, SCORE_X_RATIO,
                                              ROW_H_DIVISOR, ROW_H_MIN,
                                              HEADER_H_DIVISOR, HEADER_H_MIN)
from kungfu_chess.ui.draw.board_layer import BoardLayer
from kungfu_chess.ui.draw.overlay_layer import OverlayLayer
from kungfu_chess.ui.draw.piece_layer import PieceLayer
from kungfu_chess.ui.draw.hud_layer import HudLayer
from kungfu_chess.ui.draw.table_layer import TableLayer

# Backward-compatible aliases used by test_rendering.py
def _format_elapsed_ms(ms: int) -> str:
    return format_elapsed_ms(ms)

def _blend_overlay(roi, color_bgra: tuple, alpha: float) -> None:
    blend_overlay(roi, color_bgra, alpha)


class Renderer:
    """
    Composition design
    Draws a GameSnapshot onto a canvas.
    """

    def __init__(self, cell_size: int = 100, board_offset_x: int = 0, board_offset_y: int = 0,
                 canvas_w: int = 0, canvas_h: int = 0, ui: UiConfig = None,
                 long_rest_ms: int = None, short_rest_ms: int = None):
        # Fall back to config.json defaults if not supplied
        from kungfu_chess.config_loader import load_config as _load_cfg
        _cfg = _load_cfg()
        long_rest_ms  = long_rest_ms  if long_rest_ms  is not None else _cfg.long_rest_ms
        short_rest_ms = short_rest_ms if short_rest_ms is not None else _cfg.short_rest_ms
        self.cell_size  = cell_size
        self._offset_x  = board_offset_x
        self._offset_y  = board_offset_y
        self._canvas_w  = canvas_w
        self._canvas_h  = canvas_h
        self._ui        = ui
        self.board_rect: BoardRect | None = None

        self._animator: AnimatorProtocol = Animator()
        self._cache: ImageCacheProtocol    = ImageCache()

        self._board_layer   = BoardLayer(cell_size, board_offset_x, board_offset_y,
                                         canvas_w, canvas_h, ui, self._cache)
        self._overlay_layer = OverlayLayer(cell_size, board_offset_x, board_offset_y, ui)
        self._piece_layer   = PieceLayer(cell_size, board_offset_x, board_offset_y,
                                         ui, self._animator, self._cache,
                                         long_rest_ms, short_rest_ms)
        self._hud_layer     = HudLayer(cell_size, board_offset_y, canvas_w, ui)
        self._table_layer   = TableLayer(cell_size, board_offset_x, ui)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self, snapshot: GameSnapshot, delta_ms: float = 0,
               countdown_ms: int | None = None, error_message: str | None = None,
               my_color=None) -> Img:
        """Build and return a fully-drawn Img. delta_ms = same ms passed to engine.wait()."""
        self._animator.advance(delta_ms)

        board_w  = snapshot.board_width  * self.cell_size
        board_h  = snapshot.board_height * self.cell_size
        canvas_w = self._canvas_w if self._canvas_w > 0 else board_w + self._offset_x
        canvas_h = self._canvas_h if self._canvas_h > 0 else board_h + self._offset_y

        self.board_rect = self._board_layer.get_board_rect(snapshot)

        canvas = Img()
        self._board_layer.draw(canvas, snapshot)
        self._overlay_layer.draw(canvas, snapshot)
        self._piece_layer.draw(canvas, snapshot)
        self._hud_layer.draw(canvas, snapshot, canvas_h,
                             countdown_ms=countdown_ms, error_message=error_message,
                             my_color=my_color)
        self._table_layer.draw(canvas, snapshot, canvas_h)

        return canvas

    def show(self, snapshot: GameSnapshot) -> None:
        self.render(snapshot).show()

    # ------------------------------------------------------------------
    # Sizing helpers — kept for backward-compatible test assertions
    # ------------------------------------------------------------------

    def _coord_font_size(self) -> float:
        return self.cell_size / COORD_FONT_RATIO

    def _table_font_size(self) -> float:
        return self.cell_size / ROW_FONT_RATIO

    def _table_header_font_size(self) -> float:
        return self.cell_size / HEADER_FONT_RATIO

    def _score_font_size(self) -> float:
        return self.cell_size / SCORE_FONT_RATIO

    def _row_height(self) -> int:
        return max(self.cell_size // ROW_H_DIVISOR, ROW_H_MIN)

    def _header_height(self) -> int:
        return max(self.cell_size // HEADER_H_DIVISOR, HEADER_H_MIN)

    def _coord_pad(self) -> int:
        return self.cell_size // COORD_PAD_DIVISOR

    def _score_x_offset(self) -> int:
        return int(self.cell_size * SCORE_X_RATIO)
