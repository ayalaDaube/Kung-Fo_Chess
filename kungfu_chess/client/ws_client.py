from __future__ import annotations
import json
from typing import Any

import websockets

from kungfu_chess.server.network.protocol import (
    CMD_CREATE_ROOM, CMD_JOIN_ROOM,
    MSG_ROOM_CREATED, MSG_ROOM_JOINED, MSG_ASSIGNED,
)


async def connect_and_join(
    host: str,
    port: int,
    username: str,
    room_id: str | None = None,
) -> tuple[Any, str, str, str | None]:
    """
    Opens a WebSocket, optionally creates a room, then joins it.

    If room_id is None a new room is created and its id is returned.
    Returns (ws, room_id, role, color_or_None).
    role is 'player' or 'spectator'; color is 'w'/'b' for players, None for spectators.
    """
    uri = f"ws://{host}:{port}"
    ws = await websockets.connect(uri)

    if room_id is None:
        await ws.send(json.dumps({"cmd": CMD_CREATE_ROOM}))
        created = json.loads(await ws.recv())
        if created.get("type") != MSG_ROOM_CREATED:
            await ws.close()
            raise RuntimeError(f"Expected '{MSG_ROOM_CREATED}', got: {created}")
        room_id = created["room_id"]

    await ws.send(json.dumps({"cmd": CMD_JOIN_ROOM, "room_id": room_id, "username": username}))
    joined = json.loads(await ws.recv())
    if joined.get("type") != MSG_ROOM_JOINED:
        await ws.close()
        raise RuntimeError(f"Expected '{MSG_ROOM_JOINED}', got: {joined}")

    role = joined["role"]
    color: str | None = None
    if role == "player":
        assigned = json.loads(await ws.recv())
        if assigned.get("type") != MSG_ASSIGNED:
            await ws.close()
            raise RuntimeError(f"Expected '{MSG_ASSIGNED}', got: {assigned}")
        color = assigned["color"]

    return ws, room_id, role, color
