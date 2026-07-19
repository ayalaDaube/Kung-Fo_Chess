# Repository: <PUT_YOUR_GIT_URL_HERE>
"""Entry point: loads ServerConfig and starts the WebSocket server."""
from __future__ import annotations
import asyncio
import logging

import websockets

from kungfu_chess.server.config import load_server_config
from kungfu_chess.server.network.ws_server import WsServer

logging.basicConfig(level=logging.INFO)


async def _main() -> None:
    config = load_server_config()
    server = WsServer()
    async with websockets.serve(server.handle, config.host, config.port):
        logging.info("Kung-Fo Chess server listening on %s:%s", config.host, config.port)
        await asyncio.get_running_loop().create_future()  # run forever


if __name__ == "__main__":
    asyncio.run(_main())
