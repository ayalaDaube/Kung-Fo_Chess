from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceColor, PieceKind
from kungfu_chess.engine.game_engine import MoveResult, MoveReason
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller


class FakeEngine:
    """Minimal fake GameEngine for Controller unit tests — no real logic."""

    def __init__(self, piece_at: dict = None, move_accepted: bool = True, jump_accepted: bool = True):
        self._piece_at = piece_at or {}
        self._move_result = MoveResult(move_accepted, MoveReason.OK if move_accepted else MoveReason.ILLEGAL_PIECE_MOVE)
        self._jump_result = MoveResult(jump_accepted, MoveReason.OK if jump_accepted else MoveReason.MOTION_IN_PROGRESS)
        self.move_calls = []
        self.jump_calls = []

    def get_piece_at(self, pos: Position):
        return self._piece_at.get(pos)

    def request_move(self, source: Position, destination: Position) -> MoveResult:
        self.move_calls.append((source, destination))
        return self._move_result

    def request_jump(self, pos: Position) -> MoveResult:
        self.jump_calls.append(pos)
        return self._jump_result


def _piece(pos: Position) -> Piece:
    return Piece("p1", PieceColor.WHITE, PieceKind.ROOK, pos)


class TestController(unittest.TestCase):

    def _ctrl(self, cols=3, rows=1, piece_at=None, move_accepted=True, jump_accepted=True):
        engine = FakeEngine(piece_at=piece_at, move_accepted=move_accepted, jump_accepted=jump_accepted)
        mapper = BoardMapper(cols, rows, 100)
        return Controller(mapper, engine), engine

    def test_first_click_selects_piece(self):
        p = _piece(Position(0, 0))
        ctrl, _ = self._ctrl(piece_at={Position(0, 0): p})
        ctrl.click(50, 50)
        self.assertEqual(ctrl.selected_cell, Position(0, 0))

    def test_first_click_empty_ignored(self):
        ctrl, _ = self._ctrl()
        ctrl.click(150, 50)
        self.assertIsNone(ctrl.selected_cell)

    def test_second_click_requests_move_and_clears(self):
        p = _piece(Position(0, 0))
        ctrl, engine = self._ctrl(piece_at={Position(0, 0): p})
        ctrl.click(50, 50)
        result = ctrl.click(250, 50)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "move_requested")
        self.assertEqual(engine.move_calls, [(Position(0, 0), Position(0, 2))])

    def test_second_click_rejected_move_clears_selection(self):
        p = _piece(Position(0, 0))
        ctrl, _ = self._ctrl(piece_at={Position(0, 0): p}, move_accepted=False)
        ctrl.click(50, 50)
        result = ctrl.click(250, 50)
        self.assertIsNone(ctrl.selected_cell)
        self.assertFalse(result.move_result.is_accepted)

    def test_outside_click_with_selection_cancels(self):
        p = _piece(Position(0, 0))
        ctrl, _ = self._ctrl(piece_at={Position(0, 0): p})
        ctrl.click(50, 50)
        result = ctrl.click(9999, 9999)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "cancelled")

    def test_outside_click_without_selection_ignored(self):
        ctrl, _ = self._ctrl()
        result = ctrl.click(9999, 9999)
        self.assertEqual(result.action, "ignored")

    def test_jump_command_accepted(self):
        p = _piece(Position(0, 0))
        ctrl, engine = self._ctrl(piece_at={Position(0, 0): p})
        result = ctrl.jump(50, 50)
        self.assertEqual(result.action, "jump_requested")
        self.assertTrue(result.move_result.is_accepted)
        self.assertEqual(engine.jump_calls, [Position(0, 0)])

    def test_jump_outside_board_ignored(self):
        ctrl, engine = self._ctrl()
        result = ctrl.jump(9999, 9999)
        self.assertEqual(result.action, "ignored")
        self.assertEqual(engine.jump_calls, [])

    def test_second_click_reselects_same_color_piece(self):
        p1 = Piece("p1", PieceColor.WHITE, PieceKind.ROOK, Position(0, 0))
        p2 = Piece("p2", PieceColor.WHITE, PieceKind.ROOK, Position(0, 1))
        ctrl, _ = self._ctrl(cols=3, rows=1, piece_at={Position(0, 0): p1, Position(0, 1): p2})
        ctrl.click(50, 50)
        result = ctrl.click(150, 50)
        self.assertEqual(result.action, "selected")
        self.assertEqual(ctrl.selected_cell, Position(0, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
