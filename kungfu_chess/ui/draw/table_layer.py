"""
Responsible for drawing the move-history tables on both sides of the board.
"""
from __future__ import annotations
import cv2
from img import Img
from kungfu_chess.config_loader import UiConfig
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceColor
from kungfu_chess.ui.draw.draw_utils import format_elapsed_ms, HEADER_FONT_RATIO, ROW_FONT_RATIO, ROW_H_DIVISOR, ROW_H_MIN, HEADER_H_DIVISOR, HEADER_H_MIN


class TableLayer:
    """Draws Black and White move-history tables on the left and right of the board."""

    def __init__(self, cell_size: int, offset_x: int, ui: UiConfig):
        self._cell_size          = cell_size
        self._offset_x           = offset_x
        self._table_margin       = ui.table_margin       if ui else 5
        self._table_inner_pad    = ui.table_inner_pad    if ui else 4
        self._time_col_ratio     = ui.time_col_ratio     if ui else 0.52
        self._min_table_width    = ui.min_table_width    if ui else 40
        self._header_color       = ui.header_color       if ui else (255, 255, 255, 255)
        self._black_header_color = ui.black_header_color if ui else (80, 40, 40, 255)
        self._white_header_color = ui.white_header_color if ui else (20, 60, 80, 255)
        self._black_row_even     = ui.black_row_even     if ui else (90, 50, 50, 255)
        self._black_row_odd      = ui.black_row_odd      if ui else (70, 35, 35, 255)
        self._white_row_even     = ui.white_row_even     if ui else (25, 65, 90, 255)
        self._white_row_odd      = ui.white_row_odd      if ui else (15, 50, 70, 255)
        self._black_text_color   = ui.black_text_color   if ui else (220, 220, 255, 255)
        self._white_text_color   = ui.white_text_color   if ui else (255, 240, 200, 255)
        self._black_line_color   = ui.black_line_color   if ui else (120, 120, 180, 255)
        self._white_line_color   = ui.white_line_color   if ui else (180, 150, 80, 255)

    def draw(self, canvas: Img, snapshot: GameSnapshot, canvas_h: int) -> None:
        cs        = self._cell_size
        board_w_px = snapshot.board_width * cs
        table_w  = self._offset_x - self._table_margin * 2
        row_h    = max(cs // ROW_H_DIVISOR, ROW_H_MIN)
        header_h = max(cs // HEADER_H_DIVISOR, HEADER_H_MIN)
        col1_w   = int(table_w * self._time_col_ratio)

        black_moves = [m for m in snapshot.move_history if m.color == PieceColor.BLACK]
        white_moves = [m for m in snapshot.move_history if m.color == PieceColor.WHITE]

        self._draw_table(canvas, black_moves, self._table_margin, table_w,
                         row_h, header_h, col1_w, "Black", canvas_h, is_black=True)
        self._draw_table(canvas, white_moves, self._offset_x + board_w_px + self._table_margin,
                         table_w, row_h, header_h, col1_w, "White", canvas_h, is_black=False)

    def _draw_table(self, canvas: Img, moves: list, tx: int, table_w: int,
                    row_h: int, header_h: int, col1_w: int,
                    label: str, canvas_h: int, is_black: bool) -> None:
        if table_w <= self._min_table_width:
            return

        text_y_off = row_h * 3 // 4
        header_fsz = self._cell_size / HEADER_FONT_RATIO
        row_fsz    = self._cell_size / ROW_FONT_RATIO
        pad        = self._table_inner_pad

        header_bg  = self._black_header_color if is_black else self._white_header_color
        row_even   = self._black_row_even      if is_black else self._white_row_even
        row_odd    = self._black_row_odd       if is_black else self._white_row_odd
        text_color = self._black_text_color    if is_black else self._white_text_color
        line_color = self._black_line_color    if is_black else self._white_line_color

        # title bar
        cv2.rectangle(canvas.img, (tx, 0), (tx + table_w, header_h), header_bg, -1)
        canvas.put_text(label, tx + table_w // 2 - col1_w // 4, text_y_off + header_h // 6,
                        font_size=header_fsz, color=self._header_color, thickness=1)

        # column header
        hy = header_h
        col_header_bg = tuple(max(0, c - 20) for c in header_bg)
        cv2.rectangle(canvas.img, (tx, hy), (tx + table_w, hy + row_h), col_header_bg, -1)
        canvas.put_text("Time", tx + pad, hy + text_y_off,
                        font_size=header_fsz, color=self._header_color, thickness=1)
        canvas.put_text("Move", tx + col1_w + pad, hy + text_y_off,
                        font_size=header_fsz, color=self._header_color, thickness=1)
        cv2.line(canvas.img, (tx + col1_w, hy), (tx + col1_w, hy + row_h), line_color, 1)

        # rows — newest first
        max_rows = (canvas_h - hy - row_h) // row_h
        visible  = moves[-max_rows:] if len(moves) > max_rows else moves

        for i, record in enumerate(reversed(visible)):
            ry = hy + row_h + i * row_h
            cv2.rectangle(canvas.img, (tx, ry), (tx + table_w, ry + row_h),
                          row_even if i % 2 == 0 else row_odd, -1)
            canvas.put_text(format_elapsed_ms(record.elapsed_ms),
                            tx + pad, ry + text_y_off,
                            font_size=row_fsz, color=text_color, thickness=1)
            canvas.put_text(record.notation, tx + col1_w + pad, ry + text_y_off,
                            font_size=row_fsz, color=text_color, thickness=1)
            cv2.line(canvas.img, (tx + col1_w, ry), (tx + col1_w, ry + row_h), line_color, 1)
