"""
Main entry point for the graphical game.
Run from project root:  python -m kungfu_chess.app
"""
import sys
import time
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

import cv2
import numpy as np
from screeninfo import get_monitors

from kungfu_chess.config_loader import load_config
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.rendering.snapshot_builder import build_snapshot
from kungfu_chess.rendering.renderer import Renderer
from kungfu_chess.rendering.game_stats_tracker import GameStatsTracker

BOARD_TEXT = """
bR bN bB bQ bK bB bN bR
bP bP bP bP bP bP bP bP
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
wP wP wP wP wP wP wP wP
wR wN wB wQ wK wB wN wR
"""


def main():
    cfg     = load_config()
    board   = BoardParser().parse(BOARD_TEXT)
    arbiter = RealTimeArbiter(
        ms_per_square=cfg.ms_per_square,
        jump_duration_ms=cfg.jump_duration_ms,
        long_rest_ms=cfg.long_rest_ms,
        short_rest_ms=cfg.short_rest_ms,
    )
    engine = GameEngine(board, RuleEngine(), arbiter)
    stats  = GameStatsTracker(board_height=board.height, piece_scores=cfg.piece_scores)

    monitor  = get_monitors()[0]
    screen_w = monitor.width
    screen_h = monitor.height

    # cell_size: לוח יתפוס 75% מגובה המסך
    cell_size = (screen_h * 75 // 100) // board.height

    board_w   = board.width  * cell_size
    board_h   = board.height * cell_size
    coord_pad = cell_size // 3
    table_w   = cell_size * 3          # רוחב טבלת היסטוריה משני הצדדים
    canvas_w  = board_w + table_w * 2 + coord_pad * 2
    canvas_h  = board_h + coord_pad * 2
    offset_x  = table_w + coord_pad
    offset_y  = coord_pad

    renderer   = Renderer(cell_size=cell_size, board_offset_x=offset_x, board_offset_y=offset_y,
                           canvas_w=canvas_w, canvas_h=canvas_h, ui=cfg.ui,
                           long_rest_ms=cfg.long_rest_ms, short_rest_ms=cfg.short_rest_ms)
    mapper     = BoardMapper(board.width, board.height, cell_size, offset_x=offset_x, offset_y=offset_y)
    controller = Controller(mapper, engine)

    cv2.namedWindow("Kung-Fo Chess", cv2.WINDOW_NORMAL)
    cv2.moveWindow("Kung-Fo Chess", (screen_w - canvas_w) // 2, (screen_h - canvas_h) // 2)
    cv2.resizeWindow("Kung-Fo Chess", canvas_w, canvas_h)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDBLCLK:
            controller.jump(x, y)
        elif event == cv2.EVENT_LBUTTONDOWN:
            controller.click(x, y)

    cv2.setMouseCallback("Kung-Fo Chess", on_mouse)

    last = time.monotonic()
    while True:
        now      = time.monotonic()
        delta_ms = (now - last) * 1000
        last     = now

        events   = engine.wait(int(delta_ms))
        stats.process(events, int(delta_ms))
        snapshot = build_snapshot(
            board, arbiter,
            cell_size_px=cell_size,
            selected_cell=controller.selected_cell,
            game_over=engine.game_over,
            stats=stats,
        )
        frame = renderer.render(snapshot, delta_ms=delta_ms)
        cv2.imshow("Kung-Fo Chess", frame.img)
        if cv2.waitKey(1) != -1:
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
