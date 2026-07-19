"""
Pure-function tests for protocol.parse_incoming_message.
No I/O, no fakes, no patching.
"""
from __future__ import annotations
import json
import unittest

from kungfu_chess.model.position import Position
from kungfu_chess.server.network.protocol import (
    parse_incoming_message,
    MoveCommand, JumpCommand, ProtocolError,
    CMD_MOVE, CMD_JUMP,
)


def _move(from_row, from_col, to_row, to_col) -> str:
    return json.dumps({
        "cmd": CMD_MOVE,
        "from": {"row": from_row, "col": from_col},
        "to":   {"row": to_row,   "col": to_col},
    })


def _jump(row, col) -> str:
    return json.dumps({"cmd": CMD_JUMP, "pos": {"row": row, "col": col}})


class TestParseValidMove(unittest.TestCase):

    def test_returns_move_command(self):
        result = parse_incoming_message(_move(6, 4, 4, 4))
        self.assertIsInstance(result, MoveCommand)

    def test_from_pos_correct(self):
        result = parse_incoming_message(_move(6, 4, 4, 4))
        self.assertEqual(result.from_pos, Position(6, 4))

    def test_to_pos_correct(self):
        result = parse_incoming_message(_move(6, 4, 4, 4))
        self.assertEqual(result.to_pos, Position(4, 4))


class TestParseValidJump(unittest.TestCase):

    def test_returns_jump_command(self):
        result = parse_incoming_message(_jump(7, 1))
        self.assertIsInstance(result, JumpCommand)

    def test_pos_correct(self):
        result = parse_incoming_message(_jump(7, 1))
        self.assertEqual(result.pos, Position(7, 1))


class TestParseMalformed(unittest.TestCase):

    def test_not_json(self):
        result = parse_incoming_message("not json {{{")
        self.assertIsInstance(result, ProtocolError)

    def test_json_array_not_object(self):
        result = parse_incoming_message("[1, 2, 3]")
        self.assertIsInstance(result, ProtocolError)

    def test_unknown_command(self):
        result = parse_incoming_message(json.dumps({"cmd": "castle"}))
        self.assertIsInstance(result, ProtocolError)
        self.assertIn("castle", result.reason)

    def test_missing_cmd_field(self):
        result = parse_incoming_message(json.dumps({"from": {"row": 0, "col": 0}}))
        self.assertIsInstance(result, ProtocolError)

    def test_move_missing_from(self):
        result = parse_incoming_message(json.dumps({
            "cmd": CMD_MOVE,
            "to": {"row": 4, "col": 4},
        }))
        self.assertIsInstance(result, ProtocolError)

    def test_move_missing_to(self):
        result = parse_incoming_message(json.dumps({
            "cmd": CMD_MOVE,
            "from": {"row": 6, "col": 4},
        }))
        self.assertIsInstance(result, ProtocolError)

    def test_move_from_wrong_type(self):
        result = parse_incoming_message(json.dumps({
            "cmd": CMD_MOVE,
            "from": "e2",
            "to": {"row": 4, "col": 4},
        }))
        self.assertIsInstance(result, ProtocolError)

    def test_move_row_is_string(self):
        result = parse_incoming_message(json.dumps({
            "cmd": CMD_MOVE,
            "from": {"row": "six", "col": 4},
            "to":   {"row": 4, "col": 4},
        }))
        self.assertIsInstance(result, ProtocolError)

    def test_jump_missing_pos(self):
        result = parse_incoming_message(json.dumps({"cmd": CMD_JUMP}))
        self.assertIsInstance(result, ProtocolError)

    def test_jump_pos_wrong_type(self):
        result = parse_incoming_message(json.dumps({"cmd": CMD_JUMP, "pos": [7, 1]}))
        self.assertIsInstance(result, ProtocolError)


if __name__ == "__main__":
    unittest.main(verbosity=2)
