"""
Layering guard: engine/ must never import from ui/.
Fast trip-wire — inspects source AST, no runtime import side-effects.
"""
from __future__ import annotations
import ast
import pathlib
import unittest

_ENGINE_DIR = pathlib.Path(__file__).parents[2] / "engine"


def _ui_imports_in(path: pathlib.Path) -> list[str]:
    """Returns all import statements in path that reference kungfu_chess.ui."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("kungfu_chess.ui"):
                    bad.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("kungfu_chess.ui"):
                bad.append(module)
    return bad


class TestEngineLayering(unittest.TestCase):

    def test_no_ui_imports_in_engine_package(self):
        violations = {}
        for py_file in _ENGINE_DIR.glob("*.py"):
            bad = _ui_imports_in(py_file)
            if bad:
                violations[py_file.name] = bad
        self.assertEqual(
            violations, {},
            f"engine/ files import from kungfu_chess.ui: {violations}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
