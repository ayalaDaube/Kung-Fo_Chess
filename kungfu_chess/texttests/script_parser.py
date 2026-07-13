from __future__ import annotations
from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class BoardCommand:
    lines: list[str]

@dataclass(frozen=True)
class ClickCommand:
    x: int
    y: int

@dataclass(frozen=True)
class JumpCommand:
    x: int
    y: int

@dataclass(frozen=True)
class WaitCommand:
    ms: int

@dataclass(frozen=True)
class PrintBoardCommand:
    expected_lines: list[str]


ScriptCommand = Union[BoardCommand, ClickCommand, JumpCommand, WaitCommand, PrintBoardCommand]


class ScriptParser:
    """Responsible for parsing DSL text into a list of ScriptCommands."""

    def parse(self, script: str) -> list[ScriptCommand]:
        lines = [l.rstrip() for l in script.splitlines()]
        commands = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line in ("Board", "Board:"):
                board_lines, i = self._read_block(lines, i + 1)
                commands.append(BoardCommand(lines=board_lines))
            elif line.startswith("click "):
                parts = line.split()
                commands.append(ClickCommand(x=int(parts[1]), y=int(parts[2])))
                i += 1
            elif line.startswith("jump "):
                parts = line.split()
                commands.append(JumpCommand(x=int(parts[1]), y=int(parts[2])))
                i += 1
            elif line.startswith("wait "):
                commands.append(WaitCommand(ms=int(line.split()[1])))
                i += 1
            elif line == "print board":
                expected_lines, i = self._read_block(lines, i + 1)
                commands.append(PrintBoardCommand(expected_lines=expected_lines))
            elif line in ("Commands", "Commands:"):
                i += 1
            else:
                i += 1
        return commands

    def _read_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Reads lines until an empty line or a new command keyword."""
        result = []
        i = start
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped == "" or stripped in ("print board", "Board", "Board:", "Commands", "Commands:") or \
               stripped.startswith(("click ", "jump ", "wait ")):

                break
            result.append(stripped)
            i += 1
        return result, i
