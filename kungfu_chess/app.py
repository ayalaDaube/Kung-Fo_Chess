"""
Main entry point for the graphical game.
Run from project root:  python -m kungfu_chess.app

Architecture
------------
Both the cv2 render loop and the asyncio WebSocket connection run on the
*same* OS thread inside a single asyncio event loop.  Between every
rendered frame, ``run_render_loop`` does ``await asyncio.sleep(interval_s)``
which yields control to the network coroutine — no threads, no locks, no
shared mutable state.

cv2.waitKey must be called from the OS main thread; asyncio's default
event loop satisfies this automatically.

Credential flow
---------------
async_main() calls ``prompt_credentials()`` (from client/pregame.py) to ask
for username, login-vs-register choice, and password before connecting.
All I/O callables are injected so the function is testable without real
stdin/getpass.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))

import cv2
from screeninfo import get_monitors

from kungfu_chess.client.logger import setup_client_logging
from kungfu_chess.client.pregame import prompt_credentials, run_pregame
from kungfu_chess.client.render_loop import run_render_loop
from kungfu_chess.client.snapshot_receiver import SnapshotReceiver
from kungfu_chess.config_loader import load_config
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.server.config import load_server_config
from kungfu_chess.ui.renderer import Renderer

logger = logging.getLogger(__name__)


async def _network_loop(ws, receiver: SnapshotReceiver) -> None:
    """
    Consume every incoming WebSocket message, feeding snapshots to the receiver.
    Runs concurrently with the render loop on the same event loop.
    """
    logger.info("Network loop started")
    try:
        async for raw in ws:
            receiver.feed(raw)
    except Exception:
        logger.exception("Network loop error")
    finally:
        logger.info("Network loop ended")


async def async_main(
    *,
    read=input,
    write=print,
    getpass_fn=None,
) -> None:
    """
    Full graphical entry point.

    Parameters ``read``, ``write``, and ``getpass_fn`` are injected so the
    credential-prompt sequence is testable without real stdin/getpass.
    In production all three default to the real system calls.
    """
    cfg = load_config()
    setup_client_logging(cfg.client_log_path)
    logger.info("Client starting")

    # ── Step 1: prompt for credentials ────────────────────────────────────────
    username, password, register = prompt_credentials(
        read=read,
        write=write,
        getpass_fn=getpass_fn,
    )

    # ── Step 2: size the window (needs screen info before connecting) ─────────
    monitor  = get_monitors()[0]
    screen_w = monitor.width
    screen_h = monitor.height

    board_w_cells = 8
    board_h_cells = 8

    cell_size = (screen_h * cfg.screen_fill_pct // 100) // board_h_cells
    board_w   = board_w_cells * cell_size
    board_h   = board_h_cells * cell_size
    coord_pad = cell_size // 3
    table_w   = cell_size * cfg.table_cells_wide
    canvas_w  = board_w + table_w * 2 + coord_pad * 2
    canvas_h  = board_h + coord_pad * 2
    offset_x  = table_w + coord_pad
    offset_y  = coord_pad

    renderer = Renderer(
        cell_size=cell_size,
        board_offset_x=offset_x,
        board_offset_y=offset_y,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        ui=cfg.ui,
        long_rest_ms=cfg.long_rest_ms,
        short_rest_ms=cfg.short_rest_ms,
    )
    mapper = BoardMapper(board_w_cells, board_h_cells, cell_size,
                         offset_x=offset_x, offset_y=offset_y)

    receiver      = SnapshotReceiver()
    controller    = Controller(mapper, receiver.latest)
    command_queue: asyncio.Queue = asyncio.Queue()

    # ── Step 3: pre-game login + room/matchmaking ─────────────────────────────
    server_cfg = load_server_config()
    result = await run_pregame(
        server_cfg.host, server_cfg.port,
        username, password,
        register=register,
        read=read,
        write=write,
    )
    if result is None:
        logger.info("Pre-game exited without joining a room.")
        return

    ws, room_id, role, color = result
    is_player = (role == "player")
    logger.info("Joined room %s as %s (color=%s)", room_id, role, color)

    # ── Step 4: open the graphical window ─────────────────────────────────────
    cv2.namedWindow(cfg.window_title, cv2.WINDOW_NORMAL)
    cv2.moveWindow(cfg.window_title,
                   (screen_w - canvas_w) // 2,
                   (screen_h - canvas_h) // 2)
    cv2.resizeWindow(cfg.window_title, canvas_w, canvas_h)

    def on_mouse(event, x, y, flags, param):
        if not is_player:
            return
        ctrl_result = None
        if event == cv2.EVENT_LBUTTONDBLCLK:
            ctrl_result = controller.jump(x, y)
        elif event == cv2.EVENT_LBUTTONDOWN:
            ctrl_result = controller.click(x, y)
        if ctrl_result is not None and ctrl_result.command is not None:
            command_queue.put_nowait(ctrl_result)

    cv2.setMouseCallback(cfg.window_title, on_mouse)

    # ── Step 5: run render + network loops concurrently ───────────────────────
    render_coro = run_render_loop(
        get_snapshot=receiver.latest,
        renderer=renderer,
        controller=controller,
        window_title=cfg.window_title,
        frame_interval_ms=cfg.frame_interval_ms,
        show_frame=cv2.imshow,
        wait_key=cv2.waitKey,
        ws=ws,
        is_player=is_player,
        get_countdown_ms=lambda: receiver.countdown_ms,
        command_queue=command_queue,
    )

    render_task  = asyncio.ensure_future(render_coro)
    network_task = asyncio.ensure_future(_network_loop(ws, receiver))
    try:
        await render_task
    finally:
        network_task.cancel()
        await asyncio.gather(network_task, return_exceptions=True)
        await ws.close()

    cv2.destroyAllWindows()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
