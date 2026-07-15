from __future__ import annotations
import pathlib
import sys

import cv2
import numpy as np
from dataclasses import dataclass

# Allow running from project root
sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from img import Img
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceState
from kungfu_chess.rendering.animator import Animator

_ASSETS_ROOT = pathlib.Path(__file__).parents[2] / "assets"
_BOARD_IMG   = _ASSETS_ROOT / "board.png"

_SEL = (100, 200, 100, 100)
_AIR = (100, 100, 220, 100)

_REST_STATES    = {PieceState.LONG_REST, PieceState.SHORT_REST}
_COOLDOWN_COLOR = (0, 215, 255, 160)  # צהוב זהב semi-transparent (BGRA)


@dataclass(frozen=True)
class BoardRect:
    x: int
    y: int
    width: int
    height: int


class Renderer:
    """
    Draws a GameSnapshot onto a canvas using only the Img class.

    Layers (bottom → top):
      1. Board
      2. Selected-cell / airborne highlights
      3. Pieces (sprites)
      4. Game-over text
    """

    def __init__(self, cell_size: int = 100, board_offset_x: int = 0, board_offset_y: int = 0):
        self.cell_size = cell_size
        self.board_rect: BoardRect | None = None
        self._offset_x = board_offset_x
        self._offset_y = board_offset_y
        self._animator = Animator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self, snapshot: GameSnapshot, delta_ms: float = 0) -> Img:
        """Build and return a fully-drawn Img. delta_ms = same ms passed to engine.wait()."""
        self._animator.advance(delta_ms)
        board_w = snapshot.board_width  * self.cell_size
        board_h = snapshot.board_height * self.cell_size
        canvas_w = board_w + self._offset_x
        canvas_h = board_h + self._offset_y

        self.board_rect = BoardRect(self._offset_x, self._offset_y, board_w, board_h)

        canvas = Img()
        canvas.img = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)

        self._draw_board(canvas, snapshot)
        self._draw_highlights(canvas, snapshot)
        self._draw_pieces(canvas, snapshot)
        if snapshot.game_over:
            self._draw_game_over(canvas, canvas_w, canvas_h)

        return canvas

    def show(self, snapshot: GameSnapshot) -> None:
        """Render snapshot and display in an OpenCV window (blocks until key press)."""
        self.render(snapshot).show()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _draw_board(self, canvas: Img, snapshot: GameSnapshot) -> None:
        board_w = snapshot.board_width  * self.cell_size
        board_h = snapshot.board_height * self.cell_size
        board = Img().read(_BOARD_IMG, size=(board_w, board_h))
        board.draw_on(canvas, self._offset_x, self._offset_y)

    def _draw_highlights(self, canvas: Img, snapshot: GameSnapshot) -> None:
        cs = self.cell_size
        for pos, overlay_color in (
            (snapshot.selected_cell, _SEL),
            (snapshot.airborne_pos,  _AIR),
        ):
            if pos is None:
                continue
            x = self._offset_x + pos.col * cs
            y = self._offset_y + pos.row * cs
            roi = canvas.img[y:y + cs, x:x + cs].astype(np.float32)
            alpha = overlay_color[3] / 255.0
            for c in range(3):
                roi[..., c] = roi[..., c] * (1 - alpha) + overlay_color[c] * alpha
            canvas.img[y:y + cs, x:x + cs] = roi.astype(np.uint8)

    def _draw_pieces(self, canvas: Img, snapshot: GameSnapshot) -> None:
        cs = self.cell_size
        for piece in snapshot.pieces:
            sprite_path = self._animator.get_frame(
                piece.id, piece.kind, piece.color, piece.state
            )
            if not sprite_path.exists():
                continue
            sprite = Img().read(str(sprite_path), size=(cs, cs), keep_aspect=True)
            x = self._offset_x + int(piece.pixel_x)
            y = self._offset_y + int(piece.pixel_y)
            if 0 <= x < canvas.img.shape[1] and 0 <= y < canvas.img.shape[0]:
                sprite.draw_on(canvas, x, y)
                if piece.state in _REST_STATES:
                    self._draw_cooldown_bar(canvas, x, y, piece)

    def _draw_cooldown_bar(self, canvas: Img, x: int, y: int, piece) -> None:
        """Overlay צהוב על המשבצת שיורד מלמעלה למטה עם התקדמות המנוחה."""
        cs       = self.cell_size
        progress = self._animator.get_rest_progress(
            piece.id, piece.kind, piece.color, piece.state
        )
        # הצהוב מתחיל מלמעלה ומתכווץ כלפי מטה - החלק העליון נשאר אחרון
        filled_h = int(cs * (1.0 - progress))
        if filled_h <= 0:
            return
        x1 = max(x, 0)
        y1 = max(y + cs - filled_h, 0)
        y2 = min(y + cs, canvas.img.shape[0])
        x2 = min(x1 + cs, canvas.img.shape[1])
        roi = canvas.img[y1:y2, x1:x2].astype(np.float32)
        alpha = _COOLDOWN_COLOR[3] / 255.0
        for c in range(3):
            roi[..., c] = roi[..., c] * (1 - alpha) + _COOLDOWN_COLOR[c] * alpha
        canvas.img[y1:y2, x1:x2] = roi.astype(np.uint8)

    def _draw_game_over(self, canvas: Img, w: int, h: int) -> None:
        canvas.put_text("GAME OVER", w // 6, h // 2,
                        font_size=2.0, color=(0, 0, 255, 255), thickness=4)
