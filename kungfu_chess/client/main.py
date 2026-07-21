from __future__ import annotations
import asyncio

from kungfu_chess.client.shell_login import prompt_username
from kungfu_chess.client.ws_client import connect_and_join
from kungfu_chess.server.config import load_server_config


async def _main() -> None:
    config = load_server_config()
    username = prompt_username()

    raw = input("Enter a room ID to join, or leave blank to create a new room: ").strip()
    room_id = raw or None

    ws, room_id, role, color = await connect_and_join(config.host, config.port, username, room_id)
    print(f"Room ID: {room_id}")
    if role == "player":
        print(f"Joined as {username!r} — color: {color}. Waiting for opponent...")
    else:
        print(f"Joined as spectator in room {room_id!r}.")
    await ws.close()


if __name__ == "__main__":
    asyncio.run(_main())
