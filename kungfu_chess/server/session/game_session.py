"""
Manages one game (exactly 2 players). Owns a GameEngine and publishes
results to the EventBus. Has no knowledge of WebSocket connections.
"""
from __future__ import annotations
import asyncio
import json
from dataclasses import asdict
from typing import Callable

from kungfu_chess.engine.game_engine import GameEngine, MoveResult
from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot
from kungfu_chess.model.piece import PieceColor, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.bus import topics
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand, Command

_STARTING_POSITION = """\
bR bN bB bQ bK bB bN bR
bP bP bP bP bP bP bP bP
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
.  .  .  .  .  .  .  .
wP wP wP wP wP wP wP wP
wR wN wB wQ wK wB wN wR
"""


def _default_engine_factory() -> GameEngine:
    from kungfu_chess.io.board_parser import BoardParser
    board = BoardParser().parse(_STARTING_POSITION)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


class GameSession:
    """
    Wraps one GameEngine for exactly one 2-player game.
    Color assignment: first connection = White, second = Black.
    Publishes snapshots to the EventBus; never touches WebSocket objects.
    """

    MAX_PLAYERS = 2

    def __init__(
        self,
        bus: EventBus,
        engine_factory: Callable[[], GameEngine] = _default_engine_factory,
    ) -> None:
        self._bus = bus
        self._engine: GameEngine = engine_factory()
        self._colors: dict[str, PieceColor] = {}  # connection_id -> PieceColor

    # ── connection management ─────────────────────────────────────────────────

    def is_full(self) -> bool:
        return len(self._colors) >= self.MAX_PLAYERS

    def assign_color(self, connection_id: str) -> PieceColor:
        """
        First caller gets White, second gets Black.
        Phase 6 (rooms) replaces only this method's internals.
        """
        color = PieceColor.WHITE if not self._colors else PieceColor.BLACK
        self._colors[connection_id] = color
        return color

    def color_for(self, connection_id: str) -> PieceColor | None:
        return self._colors.get(connection_id)

    # ── command handling ──────────────────────────────────────────────────────

    async def handle_command(self, connection_id: str, command: Command) -> tuple[MoveResult, GameSnapshot]:
        """
        Applies a validated Command to the engine and publishes the result event.
        Returns (MoveResult, GameSnapshot) so ws_server can broadcast the snapshot.
        """
        if isinstance(command, MoveCommand):
            result = self._engine.request_move(command.from_pos, command.to_pos)
            topic = topics.MOVE_ACCEPTED if result.is_accepted else topics.MOVE_REJECTED
        else:  # JumpCommand
            result = self._engine.request_jump(command.pos)
            topic = topics.JUMP_ACCEPTED if result.is_accepted else topics.JUMP_REJECTED

        await self._bus.publish(topic, result)
        snapshot = self._build_snapshot()
        await self._bus.publish(topics.SNAPSHOT, snapshot)
        return result, snapshot

    def build_snapshot(self) -> GameSnapshot:
        """Public accessor for ws_server to get the current snapshot on demand."""
        return self._build_snapshot()

    def _build_snapshot(self) -> GameSnapshot:
        board = self._engine._board
        arbiter = self._engine._arbiter
        pieces = []
        for piece in board.all_pieces():
            motion = arbiter.get_motion_for(piece)
            if motion is not None:
                elapsed = motion.remaining_ms  # remaining; progress = 1 - remaining/total
                total_ms = (
                    arbiter.ms_per_square
                    * max(abs((motion.to_pos.row - motion.from_pos.row) if motion.to_pos else 0),
                          abs((motion.to_pos.col - motion.from_pos.col) if motion.to_pos else 0))
                ) or 1
                progress = max(0.0, min(1.0, 1.0 - elapsed / total_ms))
            else:
                progress = 1.0
            pieces.append(PieceSnapshot(
                id=piece.id,
                kind=piece.kind,
                color=piece.color,
                cell=piece.cell,
                state=piece.state,
                pixel_x=float(piece.cell.col),
                pixel_y=float(piece.cell.row),
                motion_progress=progress,
            ))
        return GameSnapshot(
            board_width=board.width,
            board_height=board.height,
            pieces=pieces,
            selected_cell=None,
            game_over=self._engine.game_over,
            airborne_pos=arbiter.airborne_position(),
        )
