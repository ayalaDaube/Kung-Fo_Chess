"""
Responsible for drawing the HUD: score labels and game-over overlay.
"""
from __future__ import annotations
from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceColor
from kungfu_chess.ui.draw.draw_utils import COORD_PAD_DIVISOR, SCORE_FONT_RATIO, SCORE_X_RATIO


class HudLayer:
    """Draws score labels above/below the board and the GAME OVER banner."""

    def __init__(self, cell_size: int, offset_y: int, canvas_w: int, ui: UiConfig):
        self._cell_size           = cell_size
        self._offset_y            = offset_y
        self._canvas_w            = canvas_w
        self._header_color        = ui.header_color        if ui else (255, 255, 255, 255)
        self._game_over_color     = ui.game_over_color     if ui else (0, 0, 255, 255)
        self._game_over_font_size = ui.game_over_font_size if ui else 2.0
        self._game_over_thickness = ui.game_over_thickness if ui else 4

    def draw(self, canvas: Img, snapshot: GameSnapshot, canvas_h: int) -> None:
        self._draw_scores(canvas, snapshot)
        if snapshot.game_over:
            self._draw_game_over(canvas, canvas_h)

    def _draw_scores(self, canvas: Img, snapshot: GameSnapshot) -> None:
        cs         = self._cell_size
        pad        = cs // COORD_PAD_DIVISOR
        fsz        = cs / SCORE_FONT_RATIO
        cx         = self._canvas_w // 2 - int(cs * SCORE_X_RATIO)
        board_h_px = snapshot.board_height * cs

        canvas.put_text(f"Score: {snapshot.scores.get(PieceColor.BLACK, 0)}",
                        cx, self._offset_y - pad // 2,
                        font_size=fsz, color=self._header_color, thickness=2)
        canvas.put_text(f"Score: {snapshot.scores.get(PieceColor.WHITE, 0)}",
                        cx, self._offset_y + board_h_px + pad,
                        font_size=fsz, color=self._header_color, thickness=2)

    def _draw_game_over(self, canvas: Img, canvas_h: int) -> None:
        canvas.put_text("GAME OVER", self._canvas_w // 6, canvas_h // 2,
                        font_size=self._game_over_font_size,
                        color=self._game_over_color,
                        thickness=self._game_over_thickness)
