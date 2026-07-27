"""
ConnectionRegistry — owns all connection-scoped state.

Tracks which WebSocket objects exist, which are logged-in, and which room
each connection belongs to.  No game logic, no networking I/O.
"""
from __future__ import annotations
from typing import Any


class ConnectionRegistry:
    """
    Single source of truth for connection ↔ room ↔ identity mappings.
    All other classes receive this via injection and call public methods only.
    """

    def __init__(self) -> None:
        self._connections: dict[str, Any] = {}              # conn_id -> ws
        self._logged_in: dict[str, tuple[str, int]] = {}    # conn_id -> (username, elo)
        self._conn_to_room: dict[str, str] = {}             # conn_id -> room_id

    # ── connection lifecycle ──────────────────────────────────────────────────

    def register(self, conn_id: str, ws: Any) -> None:
        self._connections[conn_id] = ws

    def forget(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
        self._logged_in.pop(conn_id, None)
        self._conn_to_room.pop(conn_id, None)

    def get_ws(self, conn_id: str) -> Any | None:
        return self._connections.get(conn_id)

    def all_conn_ids(self) -> list[str]:
        return list(self._connections.keys())

    # ── login state ───────────────────────────────────────────────────────────

    def mark_logged_in(self, conn_id: str, username: str, elo: int) -> None:
        self._logged_in[conn_id] = (username, elo)

    def identity_of(self, conn_id: str) -> tuple[str, int] | None:
        """Returns (username, elo) or None if not logged in."""
        return self._logged_in.get(conn_id)

    def forget_login(self, conn_id: str) -> None:
        self._logged_in.pop(conn_id, None)

    # ── room assignment ───────────────────────────────────────────────────────

    def assign_room(self, conn_id: str, room_id: str) -> None:
        self._conn_to_room[conn_id] = room_id

    def room_of(self, conn_id: str) -> str | None:
        return self._conn_to_room.get(conn_id)

    def forget_room(self, conn_id: str) -> None:
        self._conn_to_room.pop(conn_id, None)

    def conns_in_room(self, room_id: str) -> list[str]:
        return [c for c, r in self._conn_to_room.items() if r == room_id]

    def remove_room_entries(self, room_id: str) -> None:
        stale = [c for c, r in self._conn_to_room.items() if r == room_id]
        for c in stale:
            del self._conn_to_room[c]
