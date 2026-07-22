from __future__ import annotations
import unittest
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot
from kungfu_chess.input.board_mapper import BoardMapper
from kungfu_chess.input.controller import Controller
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand


def _snapshot(*pieces: PieceSnapshot) -> GameSnapshot:
    return GameSnapshot(
        board_width=8, board_height=8,
        pieces=list(pieces),
        selected_cell=None,
        game_over=False,
        airborne_pos=None,
    )


def _piece(pid: str, pos: Position,
           color: PieceColor = PieceColor.WHITE,
           state: PieceState = PieceState.IDLE) -> PieceSnapshot:
    return PieceSnapshot(
        id=pid, kind=PieceKind.ROOK, color=color,
        cell=pos, state=state,
    )


class TestController(unittest.TestCase):

    def _ctrl(self, snapshot: GameSnapshot | None = None, cols=3, rows=1):
        mapper = BoardMapper(cols, rows, 100)
        snap   = snapshot
        return Controller(mapper, lambda: snap)

    # ── selection-state coverage ──────────────────────────────────────────────

    def test_first_click_selects_piece(self):
        snap = _snapshot(_piece("p1", Position(0, 0)))
        ctrl = self._ctrl(snap)
        result = ctrl.click(50, 50)
        self.assertEqual(result.action, "selected")
        self.assertEqual(ctrl.selected_cell, Position(0, 0))

    def test_first_click_empty_ignored(self):
        snap = _snapshot()
        ctrl = self._ctrl(snap)
        result = ctrl.click(150, 50)
        self.assertEqual(result.action, "ignored")
        self.assertIsNone(ctrl.selected_cell)

    def test_first_click_resting_piece_ignored(self):
        snap = _snapshot(_piece("p1", Position(0, 0), state=PieceState.LONG_REST))
        ctrl = self._ctrl(snap)
        result = ctrl.click(50, 50)
        self.assertEqual(result.action, "ignored")
        self.assertIsNone(ctrl.selected_cell)

    def test_second_click_produces_move_command_and_clears(self):
        snap = _snapshot(_piece("p1", Position(0, 0)))
        ctrl = self._ctrl(snap)
        ctrl.click(50, 50)                    # select
        result = ctrl.click(250, 50)          # move to col 2
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "move_requested")
        self.assertIsInstance(result.command, MoveCommand)
        self.assertEqual(result.command.from_pos, Position(0, 0))
        self.assertEqual(result.command.to_pos,   Position(0, 2))

    def test_second_click_no_engine_mutation(self):
        """Controller never calls engine methods — command is the only output."""
        snap = _snapshot(_piece("p1", Position(0, 0)))
        ctrl = self._ctrl(snap)
        ctrl.click(50, 50)
        result = ctrl.click(250, 50)
        # The only side-effect is the returned command; no engine to check.
        self.assertIsNotNone(result.command)

    def test_outside_click_with_selection_cancels(self):
        snap = _snapshot(_piece("p1", Position(0, 0)))
        ctrl = self._ctrl(snap)
        ctrl.click(50, 50)
        result = ctrl.click(9999, 9999)
        self.assertIsNone(ctrl.selected_cell)
        self.assertEqual(result.action, "cancelled")
        self.assertIsNone(result.command)

    def test_outside_click_without_selection_ignored(self):
        ctrl = self._ctrl()
        result = ctrl.click(9999, 9999)
        self.assertEqual(result.action, "ignored")
        self.assertIsNone(result.command)

    def test_second_click_reselects_same_color_piece(self):
        p1 = _piece("p1", Position(0, 0), PieceColor.WHITE)
        p2 = _piece("p2", Position(0, 1), PieceColor.WHITE)
        snap = _snapshot(p1, p2)
        ctrl = self._ctrl(snap)
        ctrl.click(50, 50)
        result = ctrl.click(150, 50)
        self.assertEqual(result.action, "selected")
        self.assertEqual(ctrl.selected_cell, Position(0, 1))
        self.assertIsNone(result.command)

    def test_second_click_different_color_produces_move(self):
        p1 = _piece("p1", Position(0, 0), PieceColor.WHITE)
        p2 = _piece("p2", Position(0, 1), PieceColor.BLACK)
        snap = _snapshot(p1, p2)
        ctrl = self._ctrl(snap)
        ctrl.click(50, 50)
        result = ctrl.click(150, 50)
        self.assertEqual(result.action, "move_requested")
        self.assertIsInstance(result.command, MoveCommand)

    # ── jump coverage ─────────────────────────────────────────────────────────

    def test_jump_produces_jump_command(self):
        snap = _snapshot(_piece("p1", Position(0, 0)))
        ctrl = self._ctrl(snap)
        result = ctrl.jump(50, 50)
        self.assertEqual(result.action, "jump_requested")
        self.assertIsInstance(result.command, JumpCommand)
        self.assertEqual(result.command.pos, Position(0, 0))

    def test_jump_outside_board_ignored(self):
        ctrl = self._ctrl()
        result = ctrl.jump(9999, 9999)
        self.assertEqual(result.action, "ignored")
        self.assertIsNone(result.command)

    def test_jump_clears_selection(self):
        snap = _snapshot(_piece("p1", Position(0, 0)))
        ctrl = self._ctrl(snap)
        ctrl.click(50, 50)                    # select
        ctrl.jump(50, 50)                     # jump clears selection
        self.assertIsNone(ctrl.selected_cell)

    # ── no-snapshot guard ─────────────────────────────────────────────────────

    def test_click_before_snapshot_arrives_ignored(self):
        ctrl = self._ctrl(snapshot=None)
        result = ctrl.click(50, 50)
        self.assertEqual(result.action, "ignored")


if __name__ == "__main__":
    unittest.main(verbosity=2)
