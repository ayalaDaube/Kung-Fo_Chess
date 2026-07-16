"""
Responsible for drawing cell highlights: selected piece and airborne piece.
"""
from __future__ import annotations
from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.ui.draw.draw_utils import blend_overlay


class OverlayLayer:
    """Draws translucent color overlays on selected and airborne cells."""

    def __init__(self, cell_size: int, offset_x: int, offset_y: int, ui: UiConfig):
        self._cell_size           = cell_size
        self._offset_x            = offset_x
        self._offset_y            = offset_y
        self._selected_cell_color = ui.selected_cell_color if ui else (100, 200, 100, 100)
        self._airborne_cell_color = ui.airborne_cell_color if ui else (100, 100, 220, 100)

    def draw(self, canvas: Img, snapshot: GameSnapshot) -> None:
        for pos, color in (
            (snapshot.selected_cell, self._selected_cell_color),
            (snapshot.airborne_pos,  self._airborne_cell_color),
        ):
            if pos is None:
                continue
            cs = self._cell_size
            x  = self._offset_x + pos.col * cs
            y  = self._offset_y + pos.row * cs
            roi = canvas.img[y:y + cs, x:x + cs]
            blend_overlay(roi, color, color[3] / 255.0)
