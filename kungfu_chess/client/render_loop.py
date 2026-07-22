"""
Async render-loop coroutine for the non-authoritative client.

Reads the latest GameSnapshot from a SnapshotProvider (SnapshotReceiver.latest),
renders it each frame, and sends any MoveCommand/JumpCommand produced by the
Controller over the WebSocket.

cv2.waitKey must be called from the OS main thread; asyncio's default event
loop satisfies this automatically.

SRP: this module knows nothing about WebSocket protocol details or game rules.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from typing import Any, Callable, Optional

from kungfu_chess.server.network.protocol import (
    CMD_MOVE, CMD_JUMP, MoveCommand, JumpCommand,
)

logger = logging.getLogger(__name__)

SnapshotProviderProtocol = Any
RendererProtocol         = Any
ControllerProtocol       = Any

ERROR_DISPLAY_MS = 2500


def _command_to_wire(cmd) -> Optional[str]:
    """Serialise a MoveCommand or JumpCommand to a JSON wire string."""
    if isinstance(cmd, MoveCommand):
        return json.dumps({
            "cmd": CMD_MOVE,
            "from": {"row": cmd.from_pos.row, "col": cmd.from_pos.col},
            "to":   {"row": cmd.to_pos.row,   "col": cmd.to_pos.col},
        })
    if isinstance(cmd, JumpCommand):
        return json.dumps({
            "cmd": CMD_JUMP,
            "pos": {"row": cmd.pos.row, "col": cmd.pos.col},
        })
    return None


async def run_render_loop(
    *,
    get_snapshot: SnapshotProviderProtocol,
    renderer: RendererProtocol,
    controller: ControllerProtocol,
    window_title: str,
    frame_interval_ms: int,
    show_frame: Callable[[str, Any], None],
    wait_key: Callable[[int], int],
    ws=None,
    is_player: bool = True,
    get_countdown_ms: Callable[[], Optional[int]] = lambda: None,
    command_queue: Optional[asyncio.Queue] = None,
    pop_error: Callable[[], Optional[str]] = lambda: None,
    my_color: Any = None,
) -> None:
    """
    Drive one render frame per ``frame_interval_ms``, then yield.

    Parameters
    ----------
    get_snapshot
        Zero-argument callable returning the latest GameSnapshot or None.
    renderer
        Renderer whose .render(snapshot, delta_ms) returns a frame with .img.
    controller
        Controller whose .click()/.jump() produce ControllerResult values.
        Mouse callbacks in app.py push ControllerResult onto ``command_queue``;
        the loop drains it each frame and sends the serialised wire message.
    window_title
        cv2 window name.
    frame_interval_ms
        Target inter-frame delay; comes from GameConfig.
    show_frame
        Callable(title, img) — wraps cv2.imshow in production.
    wait_key
        Callable(delay_ms) -> int — wraps cv2.waitKey; non-(-1) stops the loop.
    ws
        Open WebSocket (or None in offline/spectator-without-ws mode).
        Commands are sent here when is_player is True.
    is_player
        False for spectators — controller commands are never sent.
    get_countdown_ms
        Zero-argument callable returning the remaining auto-resign countdown
        in ms (from SnapshotReceiver.countdown_ms), or None when inactive.
        The loop ticks it down locally each frame so the display is smooth.
    command_queue
        Per-invocation asyncio.Queue created by the caller (app.py).
        The mouse callback pushes ControllerResult objects onto it;
        the loop drains it each frame (non-blocking).  None means no
        commands are expected (spectator mode or tests that don't need it).
        Using a caller-owned queue means multiple independent loop
        invocations never share state.
    pop_error
        Zero-argument callable returning the latest rejected-command reason
        (from SnapshotReceiver.pop_error), or None if none is pending.
        Each call consumes the pending error, so the loop latches it into
        a locally-ticking display for ERROR_DISPLAY_MS — otherwise a
        rejected move (wrong piece, resting piece, illegal move, ...) would
        vanish with no on-screen feedback at all.
    my_color
        This client's own assigned PieceColor (or None for a spectator, or
        before it is known). Threaded through to the renderer so a
        resignation game-over can say "YOU WIN"/"YOU LOSE" instead of a
        bare "GAME OVER" with no indication of the outcome.
    """
    interval_s = frame_interval_ms / 1000.0
    last = time.monotonic()
    # Local countdown: ticks down each frame from the server-supplied value.
    _local_countdown: Optional[int] = None
    _last_server_countdown: Optional[int] = None
    # Local error display: latched for ERROR_DISPLAY_MS after each MSG_ERROR.
    _error_text: Optional[str] = None
    _error_remaining_ms = 0

    while True:
        now      = time.monotonic()
        delta_ms = int((now - last) * 1000)
        last     = now

        # Sync local countdown from server value; tick it down each frame.
        server_cd = get_countdown_ms()
        if server_cd != _last_server_countdown:
            _local_countdown = server_cd
            _last_server_countdown = server_cd
        elif _local_countdown is not None:
            _local_countdown = max(0, _local_countdown - delta_ms)

        new_error = pop_error()
        if new_error is not None:
            _error_text = new_error
            _error_remaining_ms = ERROR_DISPLAY_MS
        elif _error_remaining_ms > 0:
            _error_remaining_ms = max(0, _error_remaining_ms - delta_ms)

        snapshot = get_snapshot()
        if snapshot is not None:
            # The server's broadcast snapshot is shared by both players (and
            # any spectators), so it can never carry a per-viewer selection —
            # selected_cell arrives as None. Overlay this client's own local
            # selection (tracked by Controller from its own clicks) so the
            # "selected" highlight is visible again.
            local_selected = getattr(controller, "selected_cell", None)
            if snapshot.selected_cell is None and local_selected is not None:
                snapshot = dataclasses.replace(snapshot, selected_cell=local_selected)

            frame = renderer.render(
                snapshot, delta_ms=delta_ms,
                countdown_ms=_local_countdown,
                error_message=_error_text if _error_remaining_ms > 0 else None,
                my_color=my_color,
            )
            show_frame(window_title, frame.img)

        # Drain all queued commands and send them.
        if is_player and ws is not None and command_queue is not None:
            while True:
                try:
                    result = command_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                wire = _command_to_wire(result.command) if result.command is not None else None
                if wire is not None:
                    try:
                        await ws.send(wire)
                        logger.info("Command sent: %s", wire)
                    except Exception:
                        logger.exception("Failed to send command")

        key = wait_key(1)
        if key != -1:
            logger.info("Key pressed (%d) — stopping render loop", key)
            break

        await asyncio.sleep(interval_s)
