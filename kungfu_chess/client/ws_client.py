from __future__ import annotations
import json
from typing import Any

import websockets

from kungfu_chess.server.network.protocol import CMD_JOIN, MSG_ASSIGNED, MSG_JOINED


async def connect_and_join(host: str, port: int, username: str) -> Any:
    """
    Opens a WebSocket connection, reads the server's color-assignment message,
    sends a join command, awaits the joined ack, and returns the open connection.
    """
    uri = f"ws://{host}:{port}"
    ws = await websockets.connect(uri)

    assigned = json.loads(await ws.recv())
    if assigned.get("type") != MSG_ASSIGNED:
        await ws.close()
        raise RuntimeError(f"Expected '{MSG_ASSIGNED}', got: {assigned}")

    await ws.send(json.dumps({"cmd": CMD_JOIN, "username": username}))

    ack = json.loads(await ws.recv())
    if ack.get("type") != MSG_JOINED:
        await ws.close()
        raise RuntimeError(f"Expected '{MSG_JOINED}', got: {ack}")

    return ws
