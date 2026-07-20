from __future__ import annotations
import asyncio

from kungfu_chess.client.shell_login import prompt_username
from kungfu_chess.client.ws_client import connect_and_join
from kungfu_chess.server.config import load_server_config


async def _main() -> None:
    config = load_server_config()
    username = prompt_username()
    ws = await connect_and_join(config.host, config.port, username)
    print(f"Joined as {username!r}. Waiting for opponent...")
    await ws.close()


if __name__ == "__main__":
    asyncio.run(_main())
