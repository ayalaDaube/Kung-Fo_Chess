"""
הרץ מהשורש:  python preview.py
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import cv2
from kungfu_chess.io.board_parser import BoardParser
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rendering.snapshot_builder import build_snapshot
from kungfu_chess.rendering.renderer import Renderer
from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.config_loader import load_config

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

from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller

cfg      = load_config()
board    = BoardParser().parse(BOARD_TEXT)
arbiter  = RealTimeArbiter(
    ms_per_square=cfg.ms_per_square,
    jump_duration_ms=cfg.jump_duration_ms,
    long_rest_ms=cfg.long_rest_ms,
    short_rest_ms=cfg.short_rest_ms,
)
engine     = GameEngine(board, RuleEngine(), arbiter)
renderer   = Renderer(cell_size=cfg.cell_size)
mapper     = BoardMapper(board.width, board.height, cfg.cell_size)
controller = Controller(mapper, engine)


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDBLCLK:
        controller.jump(x, y)
    elif event == cv2.EVENT_LBUTTONDOWN:
        controller.click(x, y)


cv2.namedWindow("preview")
cv2.setMouseCallback("preview", on_mouse)

import time

DELTA_MS = 16
last = time.monotonic()

while True:
    now = time.monotonic()
    delta_ms = (now - last) * 1000
    last = now

    engine.wait(int(delta_ms))
    snapshot = build_snapshot(board, arbiter, cell_size_px=cfg.cell_size,
                              selected_cell=controller.selected_cell,
                              game_over=engine.game_over)
    frame = renderer.render(snapshot, delta_ms=delta_ms)
    cv2.imshow("preview", frame.img)
    if cv2.waitKey(DELTA_MS) != -1:
        break

cv2.destroyAllWindows()
