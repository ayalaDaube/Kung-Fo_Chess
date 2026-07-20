"""
Manages one game (exactly 2 players). Owns a GameEngine and publishes
results to the EventBus. Has no knowledge of WebSocket connections.
"""
from __future__ import annotations
from typing import Callable

from kungfu_chess.engine.game_engine import GameEngine, MoveResult
from kungfu_chess.io.standard_setup import STANDARD_STARTING_POSITION
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceColor
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.bus import topics
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand, Command


def _default_engine_factory() -> GameEngine:
    from kungfu_chess.io.board_parser import BoardParser
    board = BoardParser().parse(STANDARD_STARTING_POSITION)
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
        color = PieceColor.WHITE if not self._colors else PieceColor.BLACK
        self._colors[connection_id] = color
        return color

    def color_for(self, connection_id: str) -> PieceColor | None:
        return self._colors.get(connection_id)

    # ── command handling ──────────────────────────────────────────────────────

    async def handle_command(self, connection_id: str, command: Command) -> tuple[MoveResult, GameSnapshot]:
        if isinstance(command, MoveCommand):
            result = self._engine.request_move(command.from_pos, command.to_pos)
            topic = topics.MOVE_ACCEPTED if result.is_accepted else topics.MOVE_REJECTED
        else:  # JumpCommand
            result = self._engine.request_jump(command.pos)
            topic = topics.JUMP_ACCEPTED if result.is_accepted else topics.JUMP_REJECTED

        await self._bus.publish(topic, result)
        snapshot = self._engine.snapshot()
        await self._bus.publish(topics.SNAPSHOT, snapshot)
        return result, snapshot

    def build_snapshot(self) -> GameSnapshot:
        """Public accessor for ws_server to get the current snapshot on demand."""
        return self._engine.snapshot()
