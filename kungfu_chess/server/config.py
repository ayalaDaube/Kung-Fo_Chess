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

_LOGGING_DEFAULTS = {
    "log_path": "server_activity.log",
}

_DATABASE_DEFAULTS = {
    "host": "localhost",
    "port": 5432,
    "user": "kungfu",
    "password": "kungfu",
    "dbname": "kungfu_chess",
}

_REDIS_DEFAULTS = {
    "host": "localhost",
    "port": 6379,
    "elo_ttl_seconds": 300,
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
class LoggingConfig:
    log_path: str


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    elo_ttl_seconds: int


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    auth: AuthConfig
    realtime: RealtimeConfig
    matchmaking: MatchmakingConfig
    stats: StatsConfig
    logging: LoggingConfig
    database: DatabaseConfig
    redis: RedisConfig


def load_server_config(path: str = _CONFIG_PATH) -> ServerConfig:
    """Loads server configuration from a JSON file. Falls back to defaults if missing."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    merged = {
        **_DEFAULTS,
        **data,
        "host": os.environ.get("SERVER_HOST", data.get("host", _DEFAULTS["host"])),
        "port": int(os.environ.get("SERVER_PORT", data.get("port", _DEFAULTS["port"]))),
    }
    auth_raw = {**_AUTH_DEFAULTS, **data.get("auth", {})}
    realtime_raw = {**_REALTIME_DEFAULTS, **data.get("realtime", {})}
    mm_raw = {**_MATCHMAKING_DEFAULTS, **data.get("matchmaking", {})}
    stats_raw = {**_STATS_DEFAULTS, **data.get("stats", {})}
    logging_raw = {**_LOGGING_DEFAULTS, **data.get("logging", {})}
    db_raw = {
        **_DATABASE_DEFAULTS,
        "host":     os.environ.get("POSTGRES_HOST",     _DATABASE_DEFAULTS["host"]),
        "port": int(os.environ.get("POSTGRES_PORT",     str(_DATABASE_DEFAULTS["port"]))),
        "user":     os.environ.get("POSTGRES_USER",     _DATABASE_DEFAULTS["user"]),
        "password": os.environ.get("POSTGRES_PASSWORD", _DATABASE_DEFAULTS["password"]),
        "dbname":   os.environ.get("POSTGRES_DB",       _DATABASE_DEFAULTS["dbname"]),
        **data.get("database", {}),
    }
    redis_raw = {
        **_REDIS_DEFAULTS,
        "host": os.environ.get("REDIS_HOST", _REDIS_DEFAULTS["host"]),
        "port": int(os.environ.get("REDIS_PORT", str(_REDIS_DEFAULTS["port"]))),
        **data.get("redis", {}),
    }
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
        logging=LoggingConfig(
            log_path=logging_raw["log_path"],
        ),
        database=DatabaseConfig(
            host=db_raw["host"],
            port=db_raw["port"],
            user=db_raw["user"],
            password=db_raw["password"],
            dbname=db_raw["dbname"],
        ),
        redis=RedisConfig(
            host=redis_raw["host"],
            port=redis_raw["port"],
            elo_ttl_seconds=redis_raw["elo_ttl_seconds"],
        ),
    )
