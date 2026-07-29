"""
CI smoke test: connects to the real running server over a real WebSocket,
registers a brand-new user, then logs in as that user.

This does NOT touch Postgres or Redis directly — it only exercises the
public protocol, the same way a real client would. The workflow verifies
the DB/cache side effects separately (via psql / redis-cli) after this
script exits 0.

Usage: python3 ci_smoke_test.py
Requires: pip install websockets
Env: SERVER_HOST (default "localhost"), SERVER_PORT (default "8765")
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import uuid

import websockets

HOST = os.environ.get("SERVER_HOST", "localhost")
PORT = os.environ.get("SERVER_PORT", "8765")
USERNAME = f"ci_smoke_{uuid.uuid4().hex[:8]}"
PASSWORD = "ci-smoke-test-password"


async def _send_and_expect(ws, payload: dict, expected_type: str) -> dict:
    await ws.send(json.dumps(payload))
    raw = await asyncio.wait_for(ws.recv(), timeout=10)
    msg = json.loads(raw)
    if msg.get("type") != expected_type:
        raise AssertionError(
            f"expected type={expected_type!r} for cmd={payload.get('cmd')!r}, got {msg!r}"
        )
    return msg


async def main() -> None:
    uri = f"ws://{HOST}:{PORT}"
    print(f"[smoke] connecting to {uri}")
    async with websockets.connect(uri) as ws:
        print(f"[smoke] registering username={USERNAME!r}")
        registered = await _send_and_expect(
            ws,
            {"cmd": "register", "username": USERNAME, "password": PASSWORD},
            "registered",
        )
        print(f"[smoke] register OK: {registered}")

    # Fresh connection for login, same as a real client reconnecting.
    async with websockets.connect(uri) as ws:
        print(f"[smoke] logging in as username={USERNAME!r}")
        logged_in = await _send_and_expect(
            ws,
            {"cmd": "login", "username": USERNAME, "password": PASSWORD},
            "logged_in",
        )
        print(f"[smoke] login OK: {logged_in}")

    # Print the username on its own final line so the workflow can capture
    # it into $GITHUB_OUTPUT for later steps (psql / redis-cli lookups).
    print(f"SMOKE_TEST_USERNAME={USERNAME}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - CI smoke test, any failure should fail loudly
        print(f"[smoke] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
