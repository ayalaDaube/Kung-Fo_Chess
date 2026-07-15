from __future__ import annotations
import pathlib
import sys

import cv2
import numpy as np
from dataclasses import dataclass

# Allow running from project root
sys.path.insert(0, str(pathlib.Path(__file__).parents[2]))

from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot, MoveRecord
from kungfu_chess.model.piece import PieceState, PieceColor
from kungfu_chess.rendering.animator import Animator

_ASSETS_ROOT = pathlib.Path(__file__).parents[2] / "assets"
_BOARD_IMG   = _ASSETS_ROOT / "board.png"

_SEL = (100, 200, 100, 100)
_AIR = (100, 100, 220, 100)

_REST_STATES    = {PieceState.LONG_REST, PieceState.SHORT_REST}
_COOLDOWN_COLOR = (0, 215, 255, 160)
_COL_LETTERS    = "abcdefghijklmnopqrstuvwxyz"
_MIN_TABLE_WIDTH = 40
_TABLE_LINE      = (160, 160, 160, 255)


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
      1. Grey background
      2. Board
      3. Coordinates (a-h, 1-8)
      4. Selected-cell / airborne highlights
      5. Pieces (sprites)
      6. Score labels
      7. Move history tables
      8. Game-over text
    """

    def __init__(self, cell_size: int = 100, board_offset_x: int = 0, board_offset_y: int = 0,
                 canvas_w: int = 0, canvas_h: int = 0, ui: UiConfig = None,
                 long_rest_ms: int = 833, short_rest_ms: int = 625):
        self._img_cache: dict[tuple, np.ndarray] = {}
        self._bg_canvas: np.ndarray | None = None  # pre-composited background+board
        self.cell_size   = cell_size
        self.board_rect: BoardRect | None = None
        self._offset_x   = board_offset_x
        self._offset_y   = board_offset_y
        self._canvas_w   = canvas_w
        self._canvas_h   = canvas_h
        self._animator   = Animator()
        self._long_rest_ms  = long_rest_ms
        self._short_rest_ms = short_rest_ms
        self._ui         = ui
        self._bg_color     = ui.bg_color     if ui else (105, 105, 105, 255)
        self._text_color   = ui.text_color   if ui else (230, 230, 230, 255)
        self._header_color = ui.header_color if ui else (255, 255, 255, 255)
        self._table_margin    = ui.table_margin    if ui else 5
        self._table_inner_pad = ui.table_inner_pad if ui else 4
        self._time_col_ratio  = ui.time_col_ratio  if ui else 0.52
        self._black_header_color = ui.black_header_color if ui else (80, 40, 40, 255)
        self._white_header_color = ui.white_header_color if ui else (20, 60, 80, 255)
        self._black_row_even     = ui.black_row_even     if ui else (90, 50, 50, 255)
        self._black_row_odd      = ui.black_row_odd      if ui else (70, 35, 35, 255)
        self._white_row_even     = ui.white_row_even     if ui else (25, 65, 90, 255)
        self._white_row_odd      = ui.white_row_odd      if ui else (15, 50, 70, 255)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self, snapshot: GameSnapshot, delta_ms: float = 0) -> Img:
        """Build and return a fully-drawn Img. delta_ms = same ms passed to engine.wait()."""
        self._animator.advance(delta_ms)
        board_w  = snapshot.board_width  * self.cell_size
        board_h  = snapshot.board_height * self.cell_size
        canvas_w = self._canvas_w if self._canvas_w > 0 else board_w + self._offset_x
        canvas_h = self._canvas_h if self._canvas_h > 0 else board_h + self._offset_y

        self.board_rect = BoardRect(self._offset_x, self._offset_y, board_w, board_h)

        canvas = Img()
        canvas.img = self._get_bg_canvas(canvas_w, canvas_h, board_w, board_h)

        self._draw_coordinates(canvas, snapshot)
        self._draw_highlights(canvas, snapshot)
        self._draw_pieces(canvas, snapshot)
        self._draw_scores(canvas, snapshot, canvas_w)
        self._draw_move_tables(canvas, snapshot, canvas_w, canvas_h)
        if snapshot.game_over:
            self._draw_game_over(canvas, canvas_w, canvas_h)

        return canvas

    def show(self, snapshot: GameSnapshot) -> None:
        self.render(snapshot).show()

    def _coord_font_size(self) -> float:
        return self.cell_size / 180.0

    def _table_font_size(self) -> float:
        return self.cell_size / 160.0

    def _table_header_font_size(self) -> float:
        return self.cell_size / 140.0

    def _score_font_size(self) -> float:
        return self.cell_size / 120.0

    def _row_height(self) -> int:
        return max(self.cell_size // 3, 24)

    def _header_height(self) -> int:
        return max(self.cell_size // 2, 36)

    def _coord_pad(self) -> int:
        return self.cell_size // 3

    def _score_x_offset(self) -> int:
        """Horizontal offset from center to align score text."""
        return int(self.cell_size * 0.6)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cached_img(self, path, w: int, h: int, keep_aspect: bool = False) -> np.ndarray:
        key = (str(path), w, h, keep_aspect)
        if key not in self._img_cache:
            self._img_cache[key] = Img().read(str(path), size=(w, h), keep_aspect=keep_aspect).img
        return self._img_cache[key]

    def _get_bg_canvas(self, canvas_w: int, canvas_h: int, board_w: int, board_h: int) -> np.ndarray:
        """Returns a pre-composited background+board array (copied each frame)."""
        if self._bg_canvas is None:
            bg = np.full((canvas_h, canvas_w, 4), self._bg_color, dtype=np.uint8)
            board_arr = self._cached_img(_BOARD_IMG, board_w, board_h)
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

    def _draw_board(self, canvas: Img, snapshot: GameSnapshot) -> None:
        pass  # handled by _get_bg_canvas

    def _draw_coordinates(self, canvas: Img, snapshot: GameSnapshot) -> None:
        cs   = self.cell_size
        ox   = self._offset_x
        oy   = self._offset_y
        bw   = snapshot.board_width
        bh   = snapshot.board_height
        pad  = self._coord_pad()
        fsz  = self._coord_font_size()
        thk  = 1
        char_w = cs // 12  # approximate half-char width for centering

        for i in range(bw):
            letter = _COL_LETTERS[i]
            cx = ox + i * cs + cs // 2 - char_w
            canvas.put_text(letter, cx, oy - pad // 2,       font_size=fsz, color=self._text_color, thickness=thk)
            canvas.put_text(letter, cx, oy + bh * cs + pad,  font_size=fsz, color=self._text_color, thickness=thk)

        for i in range(bh):
            number = str(bh - i)
            cy = oy + i * cs + cs // 2 + char_w
            canvas.put_text(number, ox - pad,                  cy, font_size=fsz, color=self._text_color, thickness=thk)
            canvas.put_text(number, ox + bw * cs + pad // 2,   cy, font_size=fsz, color=self._text_color, thickness=thk)

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
            roi   = canvas.img[y:y + cs, x:x + cs]
            alpha = overlay_color[3] / 255.0
            roi[..., :3] = (roi[..., :3].astype(np.float32) * (1 - alpha) + np.array(overlay_color[:3], np.float32) * alpha).astype(np.uint8)

    def _draw_pieces(self, canvas: Img, snapshot: GameSnapshot) -> None:
        cs = self.cell_size
        for piece in snapshot.pieces:
            sprite_path = self._animator.get_frame(
                piece.id, piece.kind, piece.color, piece.state
            )
            if not sprite_path.exists():
                continue
            sprite = Img()
            sprite.img = self._cached_img(sprite_path, cs, cs, keep_aspect=True)
            x = self._offset_x + int(piece.pixel_x)
            y = self._offset_y + int(piece.pixel_y)
            if 0 <= x < canvas.img.shape[1] and 0 <= y < canvas.img.shape[0]:
                sprite.draw_on(canvas, x, y)
                if piece.state in _REST_STATES:
                    rest_ms = self._long_rest_ms if piece.state == PieceState.LONG_REST else self._short_rest_ms
                    self._draw_cooldown_bar(canvas, x, y, piece, rest_ms)

    def _draw_cooldown_bar(self, canvas: Img, x: int, y: int, piece, rest_duration_ms: float) -> None:
        cs       = self.cell_size
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
        roi   = canvas.img[y1:y2, x1:x2]
        alpha = _COOLDOWN_COLOR[3] / 255.0
        roi[..., :3] = (roi[..., :3].astype(np.float32) * (1 - alpha) + np.array(_COOLDOWN_COLOR[:3], np.float32) * alpha).astype(np.uint8)

    def _draw_scores(self, canvas: Img, snapshot: GameSnapshot, canvas_w: int) -> None:
        """Score: Black למעלה באמצע, White למטה באמצע."""
        oy          = self._offset_y
        board_h_px  = snapshot.board_height * self.cell_size
        cx          = canvas_w // 2 - self._score_x_offset()
        pad         = self._coord_pad()
        fsz         = self._score_font_size()

        black_score = snapshot.scores.get(PieceColor.BLACK, 0)
        white_score = snapshot.scores.get(PieceColor.WHITE, 0)

        canvas.put_text(f"Score: {black_score}", cx, oy - pad // 2,
                        font_size=fsz, color=self._header_color, thickness=2)
        canvas.put_text(f"Score: {white_score}", cx, oy + board_h_px + pad,
                        font_size=fsz, color=self._header_color, thickness=2)

    def _draw_move_tables(self, canvas: Img, snapshot: GameSnapshot,
                          canvas_w: int, canvas_h: int) -> None:
        ox        = self._offset_x
        board_w   = snapshot.board_width * self.cell_size
        table_w   = ox - self._table_margin * 2
        table_x_l = self._table_margin
        table_x_r = ox + board_w + self._table_margin
        row_h     = self._row_height()
        header_h  = self._header_height()
        col1_w    = int(table_w * self._time_col_ratio)

        black_moves = [m for m in snapshot.move_history if m.color == PieceColor.BLACK]
        white_moves = [m for m in snapshot.move_history if m.color == PieceColor.WHITE]

        for moves, tx, label, is_black in (
            (black_moves, table_x_l, "Black", True),
            (white_moves, table_x_r, "White", False),
        ):
            self._draw_single_table(canvas, moves, tx, 0,
                                    table_w, row_h, header_h, col1_w, label, canvas_h, is_black)

    def _draw_single_table(self, canvas: Img, moves: list, tx: int, oy: int,
                           table_w: int, row_h: int, header_h: int,
                           col1_w: int, label: str, canvas_h: int, is_black: bool = True) -> None:
        if table_w <= _MIN_TABLE_WIDTH:
            return

        text_y_offset = row_h * 3 // 4
        header_fsz    = self._table_header_font_size()
        row_fsz       = self._table_font_size()
        inner_pad     = self._table_inner_pad

        header_bg  = self._black_header_color if is_black else self._white_header_color
        row_even   = self._black_row_even      if is_black else self._white_row_even
        row_odd    = self._black_row_odd       if is_black else self._white_row_odd
        text_color = (220, 220, 255, 255)      if is_black else (255, 240, 200, 255)
        line_color = (120, 120, 180, 255)      if is_black else (180, 150, 80, 255)

        # title bar
        cv2.rectangle(canvas.img, (tx, oy), (tx + table_w, oy + header_h), header_bg, -1)
        canvas.put_text(label, tx + table_w // 2 - col1_w // 4, oy + text_y_offset + header_h // 6,
                        font_size=header_fsz, color=self._header_color, thickness=1)

        # column header row
        hy = oy + header_h
        col_header_bg = tuple(max(0, c - 20) for c in header_bg)
        cv2.rectangle(canvas.img, (tx, hy), (tx + table_w, hy + row_h), col_header_bg, -1)
        canvas.put_text("Time", tx + inner_pad, hy + text_y_offset,
                        font_size=header_fsz, color=self._header_color, thickness=1)
        canvas.put_text("Move", tx + col1_w + inner_pad, hy + text_y_offset,
                        font_size=header_fsz, color=self._header_color, thickness=1)
        cv2.line(canvas.img, (tx + col1_w, hy), (tx + col1_w, hy + row_h), line_color, 1)

        # move rows - newest first
        max_rows = (canvas_h - hy - row_h) // row_h
        visible  = moves[-max_rows:] if len(moves) > max_rows else moves

        for i, record in enumerate(reversed(visible)):
            ry = hy + row_h + i * row_h
            bg = row_even if i % 2 == 0 else row_odd
            cv2.rectangle(canvas.img, (tx, ry), (tx + table_w, ry + row_h), bg, -1)

            ms       = record.elapsed_ms
            mins     = ms // 60_000
            secs     = (ms % 60_000) // 1000
            millis   = ms % 1000
            time_str = f"{mins:02d}:{secs:02d}.{millis:03d}"

            canvas.put_text(time_str,        tx + inner_pad,          ry + text_y_offset,
                            font_size=row_fsz, color=text_color, thickness=1)
            canvas.put_text(record.notation, tx + col1_w + inner_pad, ry + text_y_offset,
                            font_size=row_fsz, color=text_color, thickness=1)
            cv2.line(canvas.img, (tx + col1_w, ry), (tx + col1_w, ry + row_h), line_color, 1)

    def _draw_game_over(self, canvas: Img, w: int, h: int) -> None:
        canvas.put_text("GAME OVER", w // 6, h // 2,
                        font_size=2.0, color=(0, 0, 255, 255), thickness=4)
