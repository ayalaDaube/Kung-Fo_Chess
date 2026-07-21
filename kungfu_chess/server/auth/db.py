"""
SQLite access layer for user persistence.
Fully synchronous — no asyncio. Callers in async code must wrap with asyncio.to_thread.
Never exposes raw cursors, rows, or SQL to callers.
"""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class UserRecord:
    username: str
    password_hash: str
    elo: int


@runtime_checkable
class UserRepository(Protocol):
    def get_user_by_username(self, username: str) -> UserRecord | None: ...
    def create_user(self, username: str, password_hash: str, elo: int) -> None: ...
    def update_elo(self, username: str, new_elo: int) -> None: ...


# ── in-memory implementation (for tests) ─────────────────────────────────────

class InMemoryUserRepository:
    def __init__(self) -> None:
        self._store: dict[str, UserRecord] = {}

    def get_user_by_username(self, username: str) -> UserRecord | None:
        return self._store.get(username)

    def create_user(self, username: str, password_hash: str, elo: int) -> None:
        if username in self._store:
            raise ValueError(f"Username already exists: {username}")
        self._store[username] = UserRecord(username=username, password_hash=password_hash, elo=elo)

    def update_elo(self, username: str, new_elo: int) -> None:
        record = self._store[username]
        self._store[username] = UserRecord(
            username=record.username,
            password_hash=record.password_hash,
            elo=new_elo,
        )


# ── SQLite implementation (production) ───────────────────────────────────────

class SqliteUserRepository:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        # For :memory: databases every connect() call would return a fresh DB,
        # so we keep one persistent connection for the lifetime of this object.
        self._persistent_conn: sqlite3.Connection | None = (
            sqlite3.connect(db_path, check_same_thread=False)
            if db_path == ":memory:" else None
        )
        if self._persistent_conn:
            self._persistent_conn.row_factory = sqlite3.Row
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._persistent_conn is not None:
            return self._persistent_conn
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    username      TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    elo           INTEGER NOT NULL
                )
            """)

    def get_user_by_username(self, username: str) -> UserRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT username, password_hash, elo FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        return UserRecord(username=row["username"], password_hash=row["password_hash"], elo=row["elo"])

    def create_user(self, username: str, password_hash: str, elo: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, elo) VALUES (?, ?, ?)",
                (username, password_hash, elo),
            )

    def update_elo(self, username: str, new_elo: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET elo = ? WHERE username = ?",
                (new_elo, username),
            )
