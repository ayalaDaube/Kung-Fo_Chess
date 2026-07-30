"""
Tests for RoomDirectory fail-open behavior.

Constructs RoomDirectory against a deliberately unreachable host/port to
confirm set/get/delete never raise and get() returns None — same guarantee
EloCache provides.  No mocks.
"""
from __future__ import annotations

import unittest

from kungfu_chess.server.allocator.room_directory import RoomDirectory

_DEAD_HOST = "127.0.0.1"
_DEAD_PORT = 19998  # nothing listening here


class TestRoomDirectoryFailOpen(unittest.TestCase):
    def setUp(self):
        self.rd = RoomDirectory(host=_DEAD_HOST, port=_DEAD_PORT)

    def test_set_does_not_raise(self):
        self.rd.set("room1", "localhost:9000")  # must not raise

    def test_get_returns_none(self):
        self.rd.set("room1", "localhost:9000")
        self.assertIsNone(self.rd.get("room1"))

    def test_delete_does_not_raise(self):
        self.rd.delete("room1")  # must not raise


if __name__ == "__main__":
    unittest.main(verbosity=2)
