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

    def draw(self, canvas: Img, snapshot: GameSnapshot, canvas_h: int,
             countdown_ms: int | None = None, error_message: str | None = None,
             my_color: PieceColor | None = None) -> None:
        self._draw_scores(canvas, snapshot)
        if snapshot.game_over:
            self._draw_game_over(canvas, canvas_h, snapshot.winner_color, my_color)
        elif countdown_ms is not None:
            self._draw_countdown(canvas, canvas_h, countdown_ms)
        elif error_message:
            self._draw_error(canvas, canvas_h, error_message)

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

    def _draw_game_over(self, canvas: Img, canvas_h: int,
                        winner_color: PieceColor | None, my_color: PieceColor | None) -> None:
        # winner_color is only known for a resignation (see GameSession.resign).
        # A natural king-capture ending leaves it None — the board itself
        # already shows the result there, so "GAME OVER" alone is unambiguous.
        if winner_color is not None and my_color is not None:
            text = "YOU WIN" if winner_color == my_color else "YOU LOSE"
        else:
            text = "GAME OVER"
        canvas.put_text(text, self._canvas_w // 6, canvas_h // 2,
                        font_size=self._game_over_font_size,
                        color=self._game_over_color,
                        thickness=self._game_over_thickness)

    def _draw_countdown(self, canvas: Img, canvas_h: int, countdown_ms: int) -> None:
        secs = max(0, countdown_ms) // 1000
        text = f"Opponent disconnected: {secs}s"
        canvas.put_text(text, self._canvas_w // 6, canvas_h // 2,
                        font_size=self._game_over_font_size,
                        color=self._game_over_color,
                        thickness=self._game_over_thickness)

    def _draw_error(self, canvas: Img, canvas_h: int, message: str) -> None:
        """Transient feedback for a rejected move — see render_loop's ERROR_DISPLAY_MS."""
        canvas.put_text(f"Move rejected: {message}", self._canvas_w // 6, canvas_h // 2,
                        font_size=self._game_over_font_size * 0.5,
                        color=self._game_over_color,
                        thickness=2)
