from typing import Optional
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceState
from kungfu_chess.model.board import Board
from kungfu_chess.realtime.motion import Motion, MotionType, ArrivalEvent


class RealTimeArbiter:
    """
    Responsible for managing everything that happens in real time outside the logical board.
    - Holds a collection of active Motions (move and jump).
    - Advances simulated time and resolves arrivals.
    - Manages airborne state for air-capture.
    Has no knowledge of chess rules, game_over, or rendering.
    """

    def __init__(self, board: Board, ms_per_square: int = 500, jump_duration_ms: int = 1000):
        self._board = board
        self._ms_per_square = ms_per_square
        self._jump_duration_ms = jump_duration_ms
        self._active_motions: list[Motion] = []
        self._airborne_pos: Optional[Position] = None

    # ── queries ───────────────────────────────────────────────────────────────

    def has_active_motion(self, piece: Optional[Piece] = None) -> bool:
        if piece is None:
            return len(self._active_motions) > 0
        return any(m.piece is piece for m in self._active_motions)

    def airborne_position(self) -> Optional[Position]:
        """Returns the position of the piece currently airborne (jump), or None."""
        return self._airborne_pos

    # ── commands ──────────────────────────────────────────────────────────────

    def start_motion(self, piece: Piece, source: Position, destination: Position) -> None:
        """Starts a MOVE motion. Assumes the move has already been validated."""
        distance = max(abs(destination.row - source.row), abs(destination.col - source.col))
        piece.state = PieceState.MOVING
        self._active_motions.append(Motion(
            motion_type=MotionType.MOVE,
            piece=piece,
            from_pos=source,
            to_pos=destination,
            remaining_ms=distance * self._ms_per_square,
        ))

    def start_jump(self, piece: Piece, pos: Position) -> None:
        """
        Sends a piece airborne for a fixed duration.
        The piece remains logically on its cell — airborne_pos marks it as airborne.
        """
        piece.state = PieceState.MOVING
        self._active_motions.append(Motion(
            motion_type=MotionType.JUMP,
            piece=piece,
            from_pos=pos,
            remaining_ms=self._jump_duration_ms,
        ))
        self._airborne_pos = pos

    def advance_time(self, ms: int) -> list[ArrivalEvent]:
        """
        Advances simulated time. Returns a list of ArrivalEvents.
        GameEngine is responsible for interpreting the events (e.g. whether a king was captured).
        """
        if not self._active_motions:
            return []

        for motion in self._active_motions:
            motion.remaining_ms -= ms

        arrived = [m for m in self._active_motions if m.remaining_ms <= 0]
        self._active_motions = [m for m in self._active_motions if m.remaining_ms > 0]

        # Resolve MOVE before JUMP so air-capture is checked while the piece is still airborne
        arrived.sort(key=lambda m: 0 if m.motion_type == MotionType.MOVE else 1)

        events = []
        for motion in arrived:
            events.extend(self._resolve_arrival(motion))
        return events

    # ── private ───────────────────────────────────────────────────────────────

    def _resolve_arrival(self, motion: Motion) -> list[ArrivalEvent]:
        if motion.motion_type == MotionType.JUMP:
            motion.piece.state = PieceState.IDLE
            self._airborne_pos = None
            return []  # jump ends on the same cell — no arrival event

        # air-capture: check before board.move_piece
        # if the arriving piece reaches the cell of an airborne enemy — the arriving piece is eliminated
        if self._airborne_pos == motion.to_pos:
            airborne_piece = self._board.get_piece(motion.to_pos)
            arriving_piece = self._board.get_piece(motion.from_pos)
            if (airborne_piece is not None
                    and arriving_piece is not None
                    and airborne_piece.color != arriving_piece.color):
                self._board.remove_piece(motion.from_pos)
                motion.piece.state = PieceState.CAPTURED
                self._airborne_pos = None
                return []

        # regular MOVE: atomic execution — remove from source, capture, place at destination
        captured = self._board.move_piece(motion.from_pos, motion.to_pos)
        motion.piece.state = PieceState.IDLE
        self._airborne_pos = None
        return [ArrivalEvent(
            arriving_piece=motion.piece,
            destination=motion.to_pos,
            captured_piece=captured,
        )]
