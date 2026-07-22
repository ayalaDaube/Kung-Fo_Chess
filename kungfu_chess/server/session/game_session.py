"""
Manages one game (exactly 2 players + unlimited spectators).
Player state is keyed by stable username, not connection_id.
connection_id is a rebindable pointer so reconnecting players resume
their existing record rather than creating a duplicate.
"""
from __future__ import annotations
from typing import Callable, Optional

from kungfu_chess.engine.game_engine import GameEngine
from kungfu_chess.io.standard_setup import STANDARD_STARTING_POSITION
from kungfu_chess.model.game_state import GameSnapshot
from kungfu_chess.model.piece import PieceColor
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rules.rule_engine import RuleEngine
from kungfu_chess.server.bus.event_bus import EventBus
from kungfu_chess.server.bus import topics
from kungfu_chess.server.network.protocol import MoveCommand, JumpCommand, Command
from kungfu_chess.server.session.player_identity import (
    PlayerRecord, IdentityResolver, default_identity_resolver,
)
from kungfu_chess.ui.game_stats_tracker import GameStatsTracker


def _default_engine_factory() -> GameEngine:
    from kungfu_chess.io.board_parser import BoardParser
    board = BoardParser().parse(STANDARD_STARTING_POSITION)
    return GameEngine(board=board, rule_engine=RuleEngine(), arbiter=RealTimeArbiter())


class GameSession:
    """
    Wraps one GameEngine for exactly one 2-player game.

    Player state is keyed by username (stable across reconnects).
    connection_id is a separate rebindable mapping so a reconnecting
    player is matched to their existing PlayerRecord.

    Spectators: connections beyond the 2-player limit are accepted and
    receive snapshot broadcasts, but own no pieces so all move/jump
    commands are naturally rejected by owns_piece_at().
    """

    MAX_PLAYERS = 2

    def __init__(
        self,
        bus: EventBus,
        piece_scores: dict,
        engine_factory: Callable[[], GameEngine] = _default_engine_factory,
        identity_resolver: IdentityResolver = default_identity_resolver,
        game_id: str = "",
    ) -> None:
        self._bus = bus
        self._engine: GameEngine = engine_factory()
        self._identity_resolver = identity_resolver
        self.game_id = game_id
        self._stats = GameStatsTracker(board_height=self._engine.board.height, piece_scores=piece_scores)

        # username -> PlayerRecord  (stable player state)
        self._players: dict[str, PlayerRecord] = {}
        # connection_id -> username  (rebindable pointer)
        self._conn_to_username: dict[str, str] = {}
        # spectator connection_ids (no PlayerRecord, no color)
        self._spectators: set[str] = set()

    # ── connection management ─────────────────────────────────────────────────

    def players_full(self) -> bool:
        """True when both player slots are taken."""
        return len(self._players) >= self.MAX_PLAYERS

    def has_player(self, username: str) -> bool:
        """True if a PlayerRecord already exists for this username."""
        return username in self._players

    def assign_color(self, connection_id: str) -> PieceColor:
        """
        Assign the next available player color to connection_id.
        Creates a placeholder PlayerRecord keyed by connection_id until
        record_join() renames it to the real username.
        """
        color = PieceColor.WHITE if not self._players else PieceColor.BLACK
        record = PlayerRecord(username=connection_id, color=color, connection_id=connection_id)
        self._players[connection_id] = record
        self._conn_to_username[connection_id] = connection_id
        return color

    def add_spectator(self, connection_id: str) -> None:
        """Register connection_id as a spectator (read-only)."""
        self._spectators.add(connection_id)

    def is_spectator(self, connection_id: str) -> bool:
        return connection_id in self._spectators

    def color_for(self, connection_id: str) -> Optional[PieceColor]:
        username = self._conn_to_username.get(connection_id)
        if username is None:
            return None
        record = self._players.get(username)
        return record.color if record else None

    def owns_piece_at(self, connection_id: str, pos: Position) -> bool:
        """True if the piece at pos belongs to this connection's assigned color."""
        color = self.color_for(connection_id)
        if color is None:
            return False
        piece = self._engine.get_piece_at(pos)
        return piece is not None and piece.color == color

    def username_for(self, connection_id: str) -> Optional[str]:
        return self._conn_to_username.get(connection_id)

    def rebind_connection(self, username: str, new_connection_id: str) -> bool:
        """
        Rebind an existing player to a new connection_id (reconnect).
        Returns True if the player was found and rebound, False otherwise.
        """
        record = self._players.get(username)
        if record is None:
            return False
        old_conn = record.connection_id
        if old_conn and old_conn in self._conn_to_username:
            del self._conn_to_username[old_conn]
        record.connection_id = new_connection_id
        self._conn_to_username[new_connection_id] = username
        return True

    # ── join handling ─────────────────────────────────────────────────────────

    async def record_join(self, connection_id: str, raw_username: str) -> None:
        """
        Resolve raw_username through the IdentityResolver, then bind it
        to the PlayerRecord that was created by assign_color().
        If the resolved username already has a PlayerRecord (reconnect),
        rebind the connection instead of creating a duplicate.
        """
        username = self._identity_resolver(raw_username)

        if username in self._players:
            # Reconnect: rebind connection to existing record
            self.rebind_connection(username, connection_id)
        else:
            # First join: rename the placeholder record
            old_record = self._players.pop(connection_id, None)
            if old_record is not None:
                del self._conn_to_username[connection_id]
                record = PlayerRecord(
                    username=username,
                    color=old_record.color,
                    connection_id=connection_id,
                )
                self._players[username] = record
                self._conn_to_username[connection_id] = username

        await self._bus.publish(
            topics.PLAYER_JOINED,
            {"conn_id": connection_id, "username": username, "game_id": self.game_id},
        )

    # ── command handling ──────────────────────────────────────────────────────

    async def handle_command(self, connection_id: str, command: Command) -> tuple:
        if isinstance(command, MoveCommand):
            result = self._engine.request_move(command.from_pos, command.to_pos)
            topic = topics.MOVE_ACCEPTED if result.is_accepted else topics.MOVE_REJECTED
        else:  # JumpCommand
            result = self._engine.request_jump(command.pos)
            topic = topics.JUMP_ACCEPTED if result.is_accepted else topics.JUMP_REJECTED

        await self._bus.publish(topic, {"game_id": self.game_id, "result": result})
        snapshot = self._engine.snapshot(stats=self._stats)
        await self._bus.publish(topics.SNAPSHOT, {"game_id": self.game_id, "snapshot": snapshot})
        return result, snapshot

    # ── resign ─────────────────────────────────────────────────────────────────

    async def resign(self, username: str) -> GameSnapshot:
        """
        End the game by resignation.  Marks the engine as game-over, publishes
        GAME_ENDED with winner/loser, and returns the final snapshot.
        The caller is responsible for ELO updates.
        """
        winner_username = next(
            (u for u, r in self._players.items() if u != username), None
        )
        winner_color = self._players[winner_username].color if winner_username else None
        self._engine.force_game_over(winner_color=winner_color)
        await self._bus.publish(topics.GAME_ENDED, {
            "game_id": self.game_id,
            "winner": winner_username,
            "loser": username,
        })
        return self._engine.snapshot(stats=self._stats)

    # ── bus access ─────────────────────────────────────────────────────────────

    def subscribe(self, topic: str, handler: Callable) -> None:
        """
        Register handler on this session's event bus. The bus itself stays
        private — callers that need to react to session events (e.g.
        ConnectionRouter wiring in an ActivityLogger) go through this method
        instead of reaching into self._bus directly.
        """
        self._bus.subscribe(topic, handler)

    async def publish_disconnected(self, room_id: str, username: str, conn_id: str) -> None:
        """Publish PLAYER_DISCONNECTED on this session's bus."""
        await self._bus.publish(topics.PLAYER_DISCONNECTED, {
            "game_id": room_id,
            "username": username,
            "conn_id": conn_id,
        })

    async def publish_reconnected(self, room_id: str, username: str, conn_id: str) -> None:
        """Publish PLAYER_RECONNECTED on this session's bus."""
        await self._bus.publish(topics.PLAYER_RECONNECTED, {
            "game_id": room_id,
            "username": username,
            "conn_id": conn_id,
        })

    def other_player_username(self, username: str) -> Optional[str]:
        """Return the opponent's username, or None if not found."""
        return next((u for u in self._players if u != username), None)

    # ── engine access ─────────────────────────────────────────────────────────

    def tick(self, ms: int) -> list:
        """Advance engine time by ms, feed the resulting events to stats, and return them."""
        events = self._engine.wait(ms)
        self._stats.process(events, ms)
        return events

    def build_snapshot(self) -> GameSnapshot:
        """Current snapshot — used by the tick loop and on-demand by the router."""
        return self._engine.snapshot(stats=self._stats)
