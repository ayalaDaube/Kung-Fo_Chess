"""
Tests for db.py — SqliteUserRepository and InMemoryUserRepository.
Uses a real SQLite :memory: database for SqliteUserRepository tests.
No monkeypatching.
"""
from __future__ import annotations
import sqlite3
import unittest

from kungfu_chess.server.auth.db import (
    InMemoryUserRepository, SqliteUserRepository, UserRecord, UserRepository,
)


class TestUserRecord(unittest.TestCase):

    def test_fields(self):
        r = UserRecord(username="alice", password_hash="hash", elo=1200)
        self.assertEqual(r.username, "alice")
        self.assertEqual(r.password_hash, "hash")
        self.assertEqual(r.elo, 1200)


class TestInMemoryUserRepository(unittest.TestCase):

    def setUp(self):
        self.repo = InMemoryUserRepository()

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.repo.get_user_by_username("nobody"))

    def test_create_and_retrieve(self):
        self.repo.create_user("alice", "hash", 1200)
        user = self.repo.get_user_by_username("alice")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.elo, 1200)

    def test_create_duplicate_raises(self):
        self.repo.create_user("alice", "hash", 1200)
        with self.assertRaises(ValueError):
            self.repo.create_user("alice", "other", 1000)

    def test_update_elo(self):
        self.repo.create_user("alice", "hash", 1200)
        self.repo.update_elo("alice", 1250)
        self.assertEqual(self.repo.get_user_by_username("alice").elo, 1250)

    def test_implements_protocol(self):
        self.assertIsInstance(self.repo, UserRepository)


class TestSqliteUserRepository(unittest.TestCase):

    def setUp(self):
        # :memory: gives a fresh DB per test
        self.repo = SqliteUserRepository(":memory:")

    def test_get_unknown_returns_none(self):
        self.assertIsNone(self.repo.get_user_by_username("nobody"))

    def test_create_and_retrieve(self):
        self.repo.create_user("bob", "hash", 1200)
        user = self.repo.get_user_by_username("bob")
        self.assertIsNotNone(user)
        self.assertEqual(user.username, "bob")
        self.assertEqual(user.password_hash, "hash")
        self.assertEqual(user.elo, 1200)

    def test_create_duplicate_raises_integrity_error(self):
        self.repo.create_user("bob", "hash", 1200)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_user("bob", "other", 1000)

    def test_update_elo(self):
        self.repo.create_user("bob", "hash", 1200)
        self.repo.update_elo("bob", 1300)
        self.assertEqual(self.repo.get_user_by_username("bob").elo, 1300)

    def test_no_asyncio_import(self):
        """db.py must not import asyncio — it is a synchronous module."""
        import kungfu_chess.server.auth.db as db_module
        self.assertNotIn("asyncio", dir(db_module))

    def test_implements_protocol(self):
        self.assertIsInstance(self.repo, UserRepository)


if __name__ == "__main__":
    unittest.main(verbosity=2)
