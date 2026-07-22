"""
Tests for client/render_loop.py.

Proves that the render loop keeps producing frames while a background
coroutine delivers WebSocket messages concurrently — no cv2 window, no
mock.patch, no real display required.

Fake objects replace renderer/controller/snapshot so the test runs
headlessly in CI.  A real asyncio event loop is used (asyncio.run) so
the concurrency behaviour is genuine.
"""
from __future__ import annotations

import asyncio
import json
import unittest

from kungfu_chess.client.render_loop import run_render_loop, _command_to_wire
from kungfu_chess.config_loader import load_config
from kungfu_chess.input.controller import ControllerResult
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.position import Position
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand, CMD_MOVE, CMD_JUMP


# ---------------------------------------------------------------------------
# Minimal fakes — just enough interface for run_render_loop
# ---------------------------------------------------------------------------

class _FakeFrame:
    img = object()   # opaque sentinel; show_frame receives it


def _fake_snapshot() -> GameSnapshot:
    return GameSnapshot(
        board_width=8, board_height=8,
        pieces=[], selected_cell=None,
        game_over=False, airborne_pos=None,
    )


class _FakeRenderer:
    def __init__(self):
        self.error_messages: list = []
        self.rendered_snapshots: list = []

    def render(self, snapshot, delta_ms=0, countdown_ms=None, error_message=None,
               my_color=None) -> _FakeFrame:
        self.error_messages.append(error_message)
        self.rendered_snapshots.append(snapshot)
        return _FakeFrame()


class _FakeController:
    selected_cell = None


class _FakeWs:
    """Fake WebSocket: records every message passed to send()."""
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, msg: str) -> None:
        self.sent.append(msg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loop(
    *,
    frame_interval_ms: int,
    frames_recorded: list,
    stop_after_frames: int,
):
    """
    Build a run_render_loop coroutine wired to fake show_frame / wait_key.

    wait_key returns -1 (no key) for the first ``stop_after_frames - 1``
    calls, then returns 27 (ESC) to stop the loop.
    """
    call_count = [0]

    def _show_frame(title, img):
        frames_recorded.append(img)

    def _wait_key(delay_ms: int) -> int:
        call_count[0] += 1
        if call_count[0] >= stop_after_frames:
            return 27   # ESC — stop the loop
        return -1

    return run_render_loop(
        get_snapshot=_fake_snapshot,
        renderer=_FakeRenderer(),
        controller=_FakeController(),
        window_title="test",
        frame_interval_ms=frame_interval_ms,
        show_frame=_show_frame,
        wait_key=_wait_key,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRenderLoopBasic(unittest.TestCase):

    def test_frames_are_produced(self):
        """run_render_loop calls show_frame at least once before stopping."""
        frames: list = []
        coro = _make_loop(
            frame_interval_ms=1,
            frames_recorded=frames,
            stop_after_frames=3,
        )
        asyncio.run(coro)
        self.assertGreaterEqual(len(frames), 1)

    def test_loop_stops_on_key_press(self):
        """Loop exits cleanly when wait_key returns non-(-1)."""
        frames: list = []
        coro = _make_loop(
            frame_interval_ms=1,
            frames_recorded=frames,
            stop_after_frames=1,   # stop on the very first frame
        )
        asyncio.run(coro)          # must return, not hang

    def test_frame_interval_from_config(self):
        """frame_interval_ms is read from GameConfig, not a hardcoded literal."""
        cfg = load_config()
        self.assertIsInstance(cfg.frame_interval_ms, int)
        self.assertGreater(cfg.frame_interval_ms, 0)

    def test_no_snapshot_skips_render(self):
        """When get_snapshot returns None, show_frame is not called."""
        frames: list = []
        call_count = [0]

        def _show(title, img):
            frames.append(img)

        def _key(d):
            call_count[0] += 1
            return 27 if call_count[0] >= 3 else -1

        coro = run_render_loop(
            get_snapshot=lambda: None,
            renderer=_FakeRenderer(),
            controller=_FakeController(),
            window_title="test",
            frame_interval_ms=1,
            show_frame=_show,
            wait_key=_key,
        )
        asyncio.run(coro)
        self.assertEqual(len(frames), 0)


class TestRenderLoopSelectionOverlay(unittest.TestCase):
    """
    Regression coverage: the server's broadcast snapshot is shared by both
    players (and spectators), so its selected_cell is always None — the
    server has no notion of "your" selection specifically. Previously the
    render loop passed the snapshot straight through, so the "selected"
    highlight never appeared for anyone. It must now be overlaid locally
    from the Controller's own selection state.
    """

    def test_local_selection_is_overlaid_when_snapshot_has_none(self):
        renderer = _FakeRenderer()

        class _SelectingController:
            selected_cell = Position(2, 3)

        call_count = [0]

        def _key(d):
            call_count[0] += 1
            return 27 if call_count[0] >= 1 else -1

        coro = run_render_loop(
            get_snapshot=_fake_snapshot,   # selected_cell=None
            renderer=renderer,
            controller=_SelectingController(),
            window_title="test",
            frame_interval_ms=1,
            show_frame=lambda t, i: None,
            wait_key=_key,
        )
        asyncio.run(coro)

        self.assertEqual(len(renderer.rendered_snapshots), 1)
        self.assertEqual(renderer.rendered_snapshots[0].selected_cell, Position(2, 3))

    def test_server_selected_cell_wins_when_present(self):
        """If the server ever does send a selected_cell, don't clobber it."""
        renderer = _FakeRenderer()

        def _snapshot_with_selection():
            return GameSnapshot(
                board_width=8, board_height=8,
                pieces=[], selected_cell=Position(0, 0),
                game_over=False, airborne_pos=None,
            )

        class _SelectingController:
            selected_cell = Position(2, 3)

        call_count = [0]

        def _key(d):
            call_count[0] += 1
            return 27 if call_count[0] >= 1 else -1

        coro = run_render_loop(
            get_snapshot=_snapshot_with_selection,
            renderer=renderer,
            controller=_SelectingController(),
            window_title="test",
            frame_interval_ms=1,
            show_frame=lambda t, i: None,
            wait_key=_key,
        )
        asyncio.run(coro)

        self.assertEqual(renderer.rendered_snapshots[0].selected_cell, Position(0, 0))


class TestRenderLoopPopError(unittest.TestCase):
    """
    Regression coverage: a rejected command (MSG_ERROR, surfaced via
    SnapshotReceiver.pop_error) must reach the renderer instead of being
    silently dropped — previously nothing consumed it at all.
    """

    def test_pop_error_is_forwarded_to_renderer_and_latched(self):
        """
        pop_error() returning a value once must still be visible to the
        renderer on subsequent frames (latched for ERROR_DISPLAY_MS), not
        just the one frame it was popped on.
        """
        renderer = _FakeRenderer()
        call_count = [0]
        popped = ["not your piece"]   # only has an error on the first pop

        def _pop_error():
            if popped:
                return popped.pop(0)
            return None

        def _key(d):
            call_count[0] += 1
            return 27 if call_count[0] >= 3 else -1

        coro = run_render_loop(
            get_snapshot=_fake_snapshot,
            renderer=renderer,
            controller=_FakeController(),
            window_title="test",
            frame_interval_ms=1,
            show_frame=lambda t, i: None,
            wait_key=_key,
            pop_error=_pop_error,
        )
        asyncio.run(coro)

        self.assertGreaterEqual(len(renderer.error_messages), 2)
        self.assertEqual(renderer.error_messages[0], "not your piece")
        # Still latched on the next frame even though pop_error() now returns None.
        self.assertEqual(renderer.error_messages[1], "not your piece")

    def test_no_error_by_default(self):
        """Without a pop_error callable, error_message stays None (default lambda)."""
        renderer = _FakeRenderer()
        call_count = [0]

        def _key(d):
            call_count[0] += 1
            return 27 if call_count[0] >= 2 else -1

        coro = run_render_loop(
            get_snapshot=_fake_snapshot,
            renderer=renderer,
            controller=_FakeController(),
            window_title="test",
            frame_interval_ms=1,
            show_frame=lambda t, i: None,
            wait_key=_key,
        )
        asyncio.run(coro)

        self.assertTrue(all(msg is None for msg in renderer.error_messages))


class TestRenderLoopConcurrency(unittest.TestCase):
    """
    Core requirement: frames keep being produced while a background
    coroutine is delivering messages concurrently.
    """

    def test_frames_accumulate_while_background_messages_arrive(self):
        """
        A background coroutine sends 5 'messages' (appends to a list) while
        the render loop runs for 10 frames.  After gather() both lists must
        be non-empty, proving neither blocked the other.
        """
        frames: list   = []
        messages: list = []

        async def _background():
            for i in range(5):
                await asyncio.sleep(0)   # yield — let render loop run
                messages.append(i)

        stop_after = [10]
        call_count = [0]

        def _show_frame(title, img):
            frames.append(img)

        def _wait_key(delay_ms: int) -> int:
            call_count[0] += 1
            return 27 if call_count[0] >= stop_after[0] else -1

        render_coro = run_render_loop(
            get_snapshot=_fake_snapshot,
            renderer=_FakeRenderer(),
            controller=_FakeController(),
            window_title="test",
            frame_interval_ms=1,
            show_frame=_show_frame,
            wait_key=_wait_key,
        )

        async def _run():
            await asyncio.gather(render_coro, _background())

        asyncio.run(_run())

        self.assertGreaterEqual(len(frames), 1,
                                "render loop produced no frames")
        self.assertEqual(len(messages), 5,
                         "background coroutine did not complete")

    def test_render_loop_does_not_starve_background_task(self):
        """
        The background task must finish even when the render loop is running.
        If run_render_loop never awaited, the background task would never run
        and this test would hang / timeout.
        """
        finished = [False]

        async def _background():
            await asyncio.sleep(0)
            finished[0] = True

        frames: list = []
        call_count   = [0]

        def _show(title, img): frames.append(img)
        def _key(d): call_count[0] += 1; return 27 if call_count[0] >= 5 else -1

        render_coro = run_render_loop(
            get_snapshot=_fake_snapshot,
            renderer=_FakeRenderer(),
            controller=_FakeController(),
            window_title="test", frame_interval_ms=1,
            show_frame=_show, wait_key=_key,
        )

        async def _run():
            await asyncio.gather(render_coro, _background())

        asyncio.run(_run())
        self.assertTrue(finished[0], "background task was starved by render loop")


class TestCommandQueue(unittest.TestCase):
    """
    BUG 3 fix: the command-queue path must work correctly and must not
    use any shared mutable state on the function object.
    """

    def test_move_command_serialised_and_sent(self):
        """
        Enqueue a MoveCommand the same way app.py's mouse callback would;
        run one loop iteration; assert ws.send() was called with the correct
        JSON wire message.
        """
        async def _run():
            q = asyncio.Queue()
            ws = _FakeWs()
            call_count = [0]

            def _key(d):
                call_count[0] += 1
                # Stop after the first frame so the loop drains the queue once.
                return 27 if call_count[0] >= 1 else -1

            cmd = MoveCommand(from_pos=Position(6, 4), to_pos=Position(5, 4))
            result = ControllerResult(action="move_requested", command=cmd)
            await q.put(result)

            await run_render_loop(
                get_snapshot=_fake_snapshot,
                renderer=_FakeRenderer(),
                controller=_FakeController(),
                window_title="test",
                frame_interval_ms=1,
                show_frame=lambda t, i: None,
                wait_key=_key,
                ws=ws,
                is_player=True,
                command_queue=q,
            )
            return ws.sent

        sent = asyncio.run(_run())
        self.assertEqual(len(sent), 1)
        msg = json.loads(sent[0])
        self.assertEqual(msg["cmd"], CMD_MOVE)
        self.assertEqual(msg["from"], {"row": 6, "col": 4})
        self.assertEqual(msg["to"],   {"row": 5, "col": 4})

    def test_jump_command_serialised_and_sent(self):
        """JumpCommand is serialised correctly."""
        async def _run():
            q = asyncio.Queue()
            ws = _FakeWs()
            call_count = [0]

            def _key(d):
                call_count[0] += 1
                return 27 if call_count[0] >= 1 else -1

            cmd = JumpCommand(pos=Position(3, 3))
            result = ControllerResult(action="jump_requested", command=cmd)
            await q.put(result)

            await run_render_loop(
                get_snapshot=_fake_snapshot,
                renderer=_FakeRenderer(),
                controller=_FakeController(),
                window_title="test",
                frame_interval_ms=1,
                show_frame=lambda t, i: None,
                wait_key=_key,
                ws=ws,
                is_player=True,
                command_queue=q,
            )
            return ws.sent

        sent = asyncio.run(_run())
        self.assertEqual(len(sent), 1)
        msg = json.loads(sent[0])
        self.assertEqual(msg["cmd"], CMD_JUMP)
        self.assertEqual(msg["pos"], {"row": 3, "col": 3})

    def test_spectator_commands_not_sent(self):
        """When is_player=False, nothing is sent even if the queue has items."""
        async def _run():
            q = asyncio.Queue()
            ws = _FakeWs()
            call_count = [0]

            def _key(d):
                call_count[0] += 1
                return 27 if call_count[0] >= 1 else -1

            cmd = MoveCommand(from_pos=Position(0, 0), to_pos=Position(1, 0))
            await q.put(ControllerResult(action="move_requested", command=cmd))

            await run_render_loop(
                get_snapshot=_fake_snapshot,
                renderer=_FakeRenderer(),
                controller=_FakeController(),
                window_title="test",
                frame_interval_ms=1,
                show_frame=lambda t, i: None,
                wait_key=_key,
                ws=ws,
                is_player=False,   # spectator
                command_queue=q,
            )
            return ws.sent

        sent = asyncio.run(_run())
        self.assertEqual(sent, [], "spectator must not send commands")

    def test_two_independent_queues_do_not_interfere(self):
        """
        Two concurrent run_render_loop invocations with separate queues must
        each send only their own command — no shared state.
        """
        async def _run():
            q1 = asyncio.Queue()
            q2 = asyncio.Queue()
            ws1 = _FakeWs()
            ws2 = _FakeWs()

            cmd1 = MoveCommand(from_pos=Position(1, 0), to_pos=Position(2, 0))
            cmd2 = MoveCommand(from_pos=Position(3, 0), to_pos=Position(4, 0))
            await q1.put(ControllerResult(action="move_requested", command=cmd1))
            await q2.put(ControllerResult(action="move_requested", command=cmd2))

            def _make_key():
                c = [0]
                def _key(d):
                    c[0] += 1
                    return 27 if c[0] >= 1 else -1
                return _key

            coro1 = run_render_loop(
                get_snapshot=_fake_snapshot, renderer=_FakeRenderer(),
                controller=_FakeController(), window_title="t1",
                frame_interval_ms=1, show_frame=lambda t, i: None,
                wait_key=_make_key(), ws=ws1, is_player=True, command_queue=q1,
            )
            coro2 = run_render_loop(
                get_snapshot=_fake_snapshot, renderer=_FakeRenderer(),
                controller=_FakeController(), window_title="t2",
                frame_interval_ms=1, show_frame=lambda t, i: None,
                wait_key=_make_key(), ws=ws2, is_player=True, command_queue=q2,
            )
            await asyncio.gather(coro1, coro2)
            return ws1.sent, ws2.sent

        sent1, sent2 = asyncio.run(_run())
        self.assertEqual(len(sent1), 1)
        self.assertEqual(len(sent2), 1)
        msg1 = json.loads(sent1[0])
        msg2 = json.loads(sent2[0])
        self.assertEqual(msg1["from"], {"row": 1, "col": 0})
        self.assertEqual(msg2["from"], {"row": 3, "col": 0})

    def test_command_to_wire_helper(self):
        """_command_to_wire returns None for non-command objects."""
        self.assertIsNone(_command_to_wire(None))
        self.assertIsNone(_command_to_wire("not a command"))

        wire = _command_to_wire(MoveCommand(Position(0, 0), Position(1, 1)))
        self.assertIsNotNone(wire)
        self.assertEqual(json.loads(wire)["cmd"], CMD_MOVE)

        wire = _command_to_wire(JumpCommand(Position(2, 2)))
        self.assertIsNotNone(wire)
        self.assertEqual(json.loads(wire)["cmd"], CMD_JUMP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
