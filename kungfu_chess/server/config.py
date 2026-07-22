from __future__ import annotations
import json
import os
from dataclasses import dataclass

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "server.json")

_DEFAULTS = {"host": "localhost", "port": 8765}

_AUTH_DEFAULTS = {
    "default_starting_elo": 1200,
    "elo_k_factor": 32,
    "sqlite_db_path": "kungfu_chess.db",
}

_REALTIME_DEFAULTS = {
    "tick_interval_ms": 50,
    "auto_resign_ms": 20000,
}

_MATCHMAKING_DEFAULTS = {
    "elo_range": 100,
    "elo_widen_step": 50,
    "widen_interval_ms": 5000,
    "timeout_ms": 60000,
}

_STATS_DEFAULTS = {
    "piece_scores": {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0},
}


@dataclass(frozen=True)
class AuthConfig:
    default_starting_elo: int
    elo_k_factor: int
    sqlite_db_path: str


@dataclass(frozen=True)
class RealtimeConfig:
    tick_interval_ms: int
    auto_resign_ms: int


@dataclass(frozen=True)
class MatchmakingConfig:
    elo_range: int
    elo_widen_step: int
    widen_interval_ms: int
    timeout_ms: int


@dataclass(frozen=True)
class StatsConfig:
    piece_scores: dict


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    auth: AuthConfig
    realtime: RealtimeConfig
    matchmaking: MatchmakingConfig
    stats: StatsConfig


def load_server_config(path: str = _CONFIG_PATH) -> ServerConfig:
    """Loads server configuration from a JSON file. Falls back to defaults if missing."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    merged = {**_DEFAULTS, **data}
    auth_raw = {**_AUTH_DEFAULTS, **data.get("auth", {})}
    realtime_raw = {**_REALTIME_DEFAULTS, **data.get("realtime", {})}
    mm_raw = {**_MATCHMAKING_DEFAULTS, **data.get("matchmaking", {})}
    stats_raw = {**_STATS_DEFAULTS, **data.get("stats", {})}
    return ServerConfig(
        host=merged["host"],
        port=merged["port"],
        auth=AuthConfig(
            default_starting_elo=auth_raw["default_starting_elo"],
            elo_k_factor=auth_raw["elo_k_factor"],
            sqlite_db_path=auth_raw["sqlite_db_path"],
        ),
        realtime=RealtimeConfig(
            tick_interval_ms=realtime_raw["tick_interval_ms"],
            auto_resign_ms=realtime_raw["auto_resign_ms"],
        ),
        matchmaking=MatchmakingConfig(
            elo_range=mm_raw["elo_range"],
            elo_widen_step=mm_raw["elo_widen_step"],
            widen_interval_ms=mm_raw["widen_interval_ms"],
            timeout_ms=mm_raw["timeout_ms"],
        ),
        stats=StatsConfig(
            piece_scores=stats_raw["piece_scores"],
        ),
    )
