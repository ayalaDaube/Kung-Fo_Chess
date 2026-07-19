from __future__ import annotations
import json
import os
from dataclasses import dataclass

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "server.json")

_DEFAULTS = {"host": "localhost", "port": 8765}


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int


def load_server_config(path: str = _CONFIG_PATH) -> ServerConfig:
    """Loads server configuration from a JSON file. Falls back to defaults if missing."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    merged = {**_DEFAULTS, **data}
    return ServerConfig(host=merged["host"], port=merged["port"])
