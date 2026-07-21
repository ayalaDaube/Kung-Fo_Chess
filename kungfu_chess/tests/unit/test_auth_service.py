"""
Tests for AuthService — register, login, ELO update.
Uses InMemoryUserRepository injected via constructor. No monkeypatching.
"""
from __future__ import annotations
import asyncio
import unittest

from kungfu_chess.server.auth.auth_service import (
    AuthService, RegisterStatus, LoginStatus,
)
from kungfu_chess.server.auth.db import InMemoryUserRepository
from kungfu_chess.server.config import AuthConfig


def run(coro):
    return asyncio.run(coro)


_CONFIG = AuthConfig(default_starting_elo=1200, elo_k_factor=32, sqlite_db_path=":memory:")


def _make_service() -> AuthService:
    return AuthService(repo=InMemoryUserRepository(), config=_CONFIG)


class TestRegister(unittest.TestCase):

    def test_success(self):
        svc = _make_service()
        result = run(svc.register("alice", "secret"))
        self.assertEqual(result.status, RegisterStatus.SUCCESS)

    def test_duplicate_username(self):
        svc = _make_service()
        run(svc.register("alice", "secret"))
        result = run(svc.register("alice", "other"))
        self.assertEqual(result.status, RegisterStatus.DUPLICATE)

    def test_empty_username(self):
        svc = _make_service()
        result = run(svc.register("", "secret"))
        self.assertEqual(result.status, RegisterStatus.INVALID_INPUT)

    def test_empty_password(self):
        svc = _make_service()
        result = run(svc.register("alice", ""))
        self.assertEqual(result.status, RegisterStatus.INVALID_INPUT)

    def test_overlong_password(self):
        svc = _make_service()
        result = run(svc.register("alice", "x" * 73))
        self.assertEqual(result.status, RegisterStatus.INVALID_INPUT)

    def test_password_not_stored_in_plaintext(self):
        svc = _make_service()
        run(svc.register("alice", "secret"))
        user = svc._repo.get_user_by_username("alice")
        self.assertNotEqual(user.password_hash, "secret")
        self.assertTrue(user.password_hash.startswith("$2b$"))

    def test_starting_elo_from_config(self):
        svc = _make_service()
        run(svc.register("alice", "secret"))
        user = svc._repo.get_user_by_username("alice")
        self.assertEqual(user.elo, _CONFIG.default_starting_elo)


class TestLogin(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()
        run(self.svc.register("alice", "correct"))

    def test_success(self):
        result = run(self.svc.login("alice", "correct"))
        self.assertEqual(result.status, LoginStatus.SUCCESS)
        self.assertIsNotNone(result.user)
        self.assertEqual(result.user.username, "alice")

    def test_wrong_password(self):
        result = run(self.svc.login("alice", "wrong"))
        self.assertEqual(result.status, LoginStatus.INVALID_CREDENTIALS)
        self.assertIsNone(result.user)

    def test_unknown_username(self):
        result = run(self.svc.login("nobody", "secret"))
        self.assertEqual(result.status, LoginStatus.INVALID_CREDENTIALS)
        self.assertIsNone(result.user)

    def test_success_returns_user_record_with_elo(self):
        result = run(self.svc.login("alice", "correct"))
        self.assertEqual(result.user.elo, _CONFIG.default_starting_elo)


class TestEloUpdate(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()
        run(self.svc.register("winner", "pw"))
        run(self.svc.register("loser", "pw"))

    def test_winner_elo_increases(self):
        before = self.svc._repo.get_user_by_username("winner").elo
        run(self.svc.apply_elo_update("winner", "loser"))
        after = self.svc._repo.get_user_by_username("winner").elo
        self.assertGreater(after, before)

    def test_loser_elo_decreases(self):
        before = self.svc._repo.get_user_by_username("loser").elo
        run(self.svc.apply_elo_update("winner", "loser"))
        after = self.svc._repo.get_user_by_username("loser").elo
        self.assertLess(after, before)

    def test_symmetry_equal_elo(self):
        """For equal starting ELO, winner gain should mirror loser loss (within 1 for rounding)."""
        run(self.svc.apply_elo_update("winner", "loser"))
        winner_after = self.svc._repo.get_user_by_username("winner").elo
        loser_after  = self.svc._repo.get_user_by_username("loser").elo
        gain = winner_after - _CONFIG.default_starting_elo
        loss = _CONFIG.default_starting_elo - loser_after
        self.assertAlmostEqual(gain, loss, delta=1)

    def test_k_factor_bounds_max_change(self):
        """Single game change must not exceed K-factor."""
        run(self.svc.apply_elo_update("winner", "loser"))
        winner_after = self.svc._repo.get_user_by_username("winner").elo
        gain = winner_after - _CONFIG.default_starting_elo
        self.assertLessEqual(gain, _CONFIG.elo_k_factor)

    def test_unknown_winner_skipped_gracefully(self):
        run(self.svc.apply_elo_update("ghost", "loser"))  # must not raise
        loser_elo = self.svc._repo.get_user_by_username("loser").elo
        self.assertEqual(loser_elo, _CONFIG.default_starting_elo)

    def test_db_calls_run_in_thread(self):
        """register() and login() must not block the event loop — verify by running
        them concurrently and confirming both complete without deadlock."""
        import asyncio

        async def _run():
            svc1 = _make_service()
            svc2 = _make_service()
            await asyncio.gather(
                svc1.register("u1", "pw"),
                svc2.register("u2", "pw"),
            )
            results = await asyncio.gather(
                svc1.login("u1", "pw"),
                svc2.login("u2", "pw"),
            )
            return results

        results = asyncio.run(_run())
        self.assertTrue(all(r.status == LoginStatus.SUCCESS for r in results))


if __name__ == "__main__":
    unittest.main(verbosity=2)
