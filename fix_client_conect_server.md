Summary
Files changed and which bug each belongs to:

BUG 2 — kungfu_chess/texttests/script_runner.py

Added top-level imports of ProtocolMoveCommand / ProtocolJumpCommand (aliased to avoid name collision with the DSL JumpCommand)

Changed Controller(mapper, engine) → Controller(mapper, lambda: engine.snapshot())

After each ClickCommand/ JumpCommand, applied the returned protocol command directly to the local engine via engine.request_move() / engine.request_jump() — necessary because there is no server in this harness

BUG 3 — kungfu_chess/client/render_loop.py

Removed the run_render_loop._queue_command = ... function-attribute hack entirely

Added command_queue: asyncio.Queue | None = None parameter — caller-owned, per-invocation, no shared state

Loop drains the queue each frame with get_nowait() in a non-blocking loop

BUG 3 — kungfu_chess/app.py

Creates command_queue = asyncio.Queue() before the render loop

Mouse callback uses command_queue.put_nowait(ctrl_result) instead of reaching into the coroutine

Passes command_queue=command_queue to run_render_loop

BUG 3 — kungfu_chess/tests/unit/test_render_loop.py

Added _FakeWs with async send()

Added TestCommandQueue class: 5 tests covering move sent, jump sent, spectator blocked, two independent queues don't interfere, _command_to_wire helper

BUG 1 — kungfu_chess/client/pregame.py

Added prompt_credentials(*, read, write, getpass_fn) — the single shared function that asks for username, login/register choice, and password; all I/O injected

BUG 1 — kungfu_chess/app.py

Replaced cfg.username if hasattr(cfg, "username") else "local" hack with a call to prompt_credentials()

async_main() now accepts injected read, write, getpass_fn for testability

BUG 1 — kungfu_chess/client/main.py

Rewritten as a one-line shim that calls app.async_main() — zero duplication, both entry points ( python -m kungfu_chess.app and python -m kungfu_chess.client.main) are identical in behaviour

BUG 1 — kungfu_chess/tests/unit/test_app_credentials_e2e.py (new)

6 tests: prompt_credentials unit tests (login/register choice, no hardcoded identity), and 3 e2e tests driving the full credential → login → room-join sequence with real sockets and injected I/O

Choice for client/main.py: option (b) — kept as a real alternate entry point that delegates to app.async_main(). This means zero duplicated logic (one line of code), both entry points work identically, and nothing is deleted that might be referenced by existing documentation or scripts.