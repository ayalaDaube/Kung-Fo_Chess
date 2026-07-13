from __future__ import annotations
import os
import unittest
from kungfu_chess.texttests.script_runner import ScriptRunner

_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "scripts")


def _load(filename: str) -> str:
    with open(os.path.join(_SCRIPTS_DIR, filename)) as f:
        return f.read()


class TestTextScripts(unittest.TestCase):

    def _run(self, filename: str) -> list[str]:
        return ScriptRunner(cell_size=100).run(_load(filename))

    def test_01_board_parsing(self):
        self.assertEqual(self._run("01_board_parsing.kfc"), [])

    def test_02_click_to_move(self):
        self.assertEqual(self._run("02_click_to_move.kfc"), [])

    def test_03_rook_moves(self):
        self.assertEqual(self._run("03_rook_moves.kfc"), [])

    def test_04_invalid_moves(self):
        self.assertEqual(self._run("04_invalid_moves.kfc"), [])

    def test_05_capture(self):
        self.assertEqual(self._run("05_capture.kfc"), [])

    def test_06_game_over(self):
        self.assertEqual(self._run("06_game_over.kfc"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
