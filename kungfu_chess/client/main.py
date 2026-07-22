"""
Alternate CLI entry point for the Kung-Fo Chess graphical client.
Run from project root:  python -m kungfu_chess.client.main

This module is a thin shim that delegates to app.async_main(), which owns
the full flow: credential prompting → pre-game menu → graphical render loop.
Having a separate entry point here lets the package be launched either as
  python -m kungfu_chess.app
or
  python -m kungfu_chess.client.main
with identical behaviour and zero duplicated logic.
"""
from __future__ import annotations

import asyncio
import logging

from kungfu_chess.app import async_main


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
