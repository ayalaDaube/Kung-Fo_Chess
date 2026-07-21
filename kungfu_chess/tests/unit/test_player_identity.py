"""
Tests for player_identity module.
"""
from __future__ import annotations
import unittest

from kungfu_chess.model.piece import PieceColor
from kungfu_chess.server.session.player_identity import (
    PlayerRecord, default_identity_resolver,
)


class TestPlayerRecord(unittest.TestCase):

    def test_fields(self):
        r = PlayerRecord(username="alice", color=PieceColor.WHITE, connection_id="conn-1")
        self.assertEqual(r.username, "alice")
        self.assertEqual(r.color, PieceColor.WHITE)
        self.assertEqual(r.connection_id, "conn-1")

    def test_connection_id_defaults_to_none(self):
        r = PlayerRecord(username="alice", color=PieceColor.BLACK)
        self.assertIsNone(r.connection_id)

    def test_connection_id_is_rebindable(self):
        r = PlayerRecord(username="alice", color=PieceColor.WHITE, connection_id="old")
        r.connection_id = "new"
        self.assertEqual(r.connection_id, "new")


class TestDefaultIdentityResolver(unittest.TestCase):

    def test_returns_name_unchanged(self):
        self.assertEqual(default_identity_resolver("alice"), "alice")

    def test_does_not_strip_or_transform(self):
        self.assertEqual(default_identity_resolver("  Bob  "), "  Bob  ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
