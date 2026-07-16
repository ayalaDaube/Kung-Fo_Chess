"""
Responsible for drawing the background, board image, and coordinate labels (a-h / 1-8).
"""
from __future__ import annotations
import pathlib
import numpy as np
from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.ui.assets.asset_paths import COL_LETTERS
from kungfu_chess.ui.draw.protocols import ImageCacheProtocol
from kungfu_chess.ui.draw.draw_utils import BoardRect, COORD_FONT_RATIO, COORD_PAD_DIVISOR, CHAR_W_DIVISOR

_BOARD_IMG = pathlib.Path(__file__).parents[3] / "assets" / "board.png"


class BoardLayer:
    """Draws background fill, board image, and coordinate labels."""

    def __init__(self, cell_size: int, offset_x: int, offset_y: int,
                 canvas_w: int, canvas_h: int, ui: UiConfig, cache: ImageCacheProtocol):
        self._cell_size = cell_size
        self._offset_x  = offset_x
        self._offset_y  = offset_y
        self._canvas_w  = canvas_w
        self._canvas_h  = canvas_h
        self._bg_color  = ui.bg_color  if ui else (105, 105, 105, 255)
        self._text_color = ui.text_color if ui else (230, 230, 230, 255)
        self._cache     = cache
        self._bg_canvas: np.ndarray | None = None

    def draw(self, canvas: Img, snapshot: GameSnapshot) -> None:
        canvas.img = self._get_bg_canvas(snapshot)
        self._draw_coordinates(canvas, snapshot)

    def get_board_rect(self, snapshot: GameSnapshot) -> BoardRect:
        return BoardRect(
            x=self._offset_x,
            y=self._offset_y,
            width=snapshot.board_width  * self._cell_size,
            height=snapshot.board_height * self._cell_size,
        )

    def _get_bg_canvas(self, snapshot: GameSnapshot) -> np.ndarray:
        if self._bg_canvas is None:
            board_w = snapshot.board_width  * self._cell_size
            board_h = snapshot.board_height * self._cell_size
            bg = np.full((self._canvas_h, self._canvas_w, 4), self._bg_color, dtype=np.uint8)
            board_arr = self._cache.get(_BOARD_IMG, board_w, board_h)
            ox, oy = self._offset_x, self._offset_y
            if board_arr.shape[2] == 4:
                alpha = board_arr[..., 3:4].astype(np.float32) / 255.0
                src   = board_arr[..., :3].astype(np.float32)
                dst   = bg[oy:oy+board_h, ox:ox+board_w, :3].astype(np.float32)
                bg[oy:oy+board_h, ox:ox+board_w, :3] = (src * alpha + dst * (1 - alpha)).astype(np.uint8)
            else:
                bg[oy:oy+board_h, ox:ox+board_w, :3] = board_arr
            self._bg_canvas = bg
        return self._bg_canvas.copy()

    def _draw_coordinates(self, canvas: Img, snapshot: GameSnapshot) -> None:
        cs     = self._cell_size
        ox, oy = self._offset_x, self._offset_y
        bw, bh = snapshot.board_width, snapshot.board_height
        pad    = cs // COORD_PAD_DIVISOR
        fsz    = cs / COORD_FONT_RATIO
        char_w = cs // CHAR_W_DIVISOR

        for i in range(bw):
            letter = COL_LETTERS[i]
            cx = ox + i * cs + cs // 2 - char_w
            canvas.put_text(letter, cx, oy - pad // 2,      font_size=fsz, color=self._text_color, thickness=1)
            canvas.put_text(letter, cx, oy + bh * cs + pad, font_size=fsz, color=self._text_color, thickness=1)

        for i in range(bh):
            cy = oy + i * cs + cs // 2 + char_w
            canvas.put_text(str(bh - i), ox - pad,                cy, font_size=fsz, color=self._text_color, thickness=1)
            canvas.put_text(str(bh - i), ox + bw * cs + pad // 2, cy, font_size=fsz, color=self._text_color, thickness=1)
