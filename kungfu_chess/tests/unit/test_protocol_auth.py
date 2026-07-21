"""
Tests for the CMD_LOGIN / CMD_REGISTER additions to protocol.parse_incoming_message.
Pure functions — no I/O, no fakes needed.
"""
from __future__ import annotations
import json
import unittest

from kungfu_chess.server.network.protocol import (
    parse_incoming_message,
    LoginCommand, RegisterCommand, ProtocolError,
    CMD_LOGIN, CMD_REGISTER,
)


def _login(username, password) -> str:
    return json.dumps({"cmd": CMD_LOGIN, "username": username, "password": password})


def _register(username, password) -> str:
    return json.dumps({"cmd": CMD_REGISTER, "username": username, "password": password})


class TestParseValidLogin(unittest.TestCase):

    def test_returns_login_command(self):
        self.assertIsInstance(parse_incoming_message(_login("alice", "secret")), LoginCommand)

    def test_fields_correct(self):
        result = parse_incoming_message(_login("alice", "secret"))
        self.assertEqual(result.username, "alice")
        self.assertEqual(result.password, "secret")


class TestParseValidRegister(unittest.TestCase):

    def test_returns_register_command(self):
        self.assertIsInstance(parse_incoming_message(_register("bob", "pass")), RegisterCommand)

    def test_fields_correct(self):
        result = parse_incoming_message(_register("bob", "pass"))
        self.assertEqual(result.username, "bob")
        self.assertEqual(result.password, "pass")


class TestParseInvalidLogin(unittest.TestCase):

    def test_empty_username(self):
        self.assertIsInstance(parse_incoming_message(_login("", "secret")), ProtocolError)

    def test_missing_username(self):
        raw = json.dumps({"cmd": CMD_LOGIN, "password": "secret"})
        self.assertIsInstance(parse_incoming_message(raw), ProtocolError)

    def test_empty_password(self):
        self.assertIsInstance(parse_incoming_message(_login("alice", "")), ProtocolError)

    def test_missing_password(self):
        raw = json.dumps({"cmd": CMD_LOGIN, "username": "alice"})
        self.assertIsInstance(parse_incoming_message(raw), ProtocolError)

    def test_overlong_username(self):
        self.assertIsInstance(parse_incoming_message(_login("a" * 33, "secret")), ProtocolError)

    def test_overlong_password(self):
        self.assertIsInstance(parse_incoming_message(_login("alice", "x" * 73)), ProtocolError)

    def test_non_string_password(self):
        raw = json.dumps({"cmd": CMD_LOGIN, "username": "alice", "password": 12345})
        self.assertIsInstance(parse_incoming_message(raw), ProtocolError)


class TestParseInvalidRegister(unittest.TestCase):

    def test_empty_username(self):
        self.assertIsInstance(parse_incoming_message(_register("", "pass")), ProtocolError)

    def test_empty_password(self):
        self.assertIsInstance(parse_incoming_message(_register("bob", "")), ProtocolError)

    def test_overlong_password(self):
        self.assertIsInstance(parse_incoming_message(_register("bob", "x" * 73)), ProtocolError)


if __name__ == "__main__":
    unittest.main(verbosity=2)
