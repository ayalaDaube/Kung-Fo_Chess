from __future__ import annotations
from typing import Optional, Union
from kungfu_chess.model.position import Position
from kungfu_chess.model.piece import Piece, PieceState
from kungfu_chess.realtime.motion import Motion, MotionType, ArrivalEvent, EliminationEvent

RealTimeEvent = Union[ArrivalEvent, EliminationEvent]


class RealTimeArbiter:
    """
    Manages active motions and simulated time. Has no knowledge of the Board.
    Reports ArrivalEvent and EliminationEvent — GameEngine applies them to the Board.
    """

    def __init__(self, ms_per_square: int = 500, jump_duration_ms: int = 1000):
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

    def get_motion_for(self, piece: Piece) -> Optional[Motion]:
        """Returns the active Motion for the given piece, or None."""
        for m in self._active_motions:
            if m.piece is piece:
                return m
        return None

    @property
    def ms_per_square(self) -> int:
        return self._ms_per_square

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

    def _eliminate_simultaneous_collisions(self, arrived: list[Motion]) -> tuple[list[Motion], list[EliminationEvent]]:
        """
        Simultaneous collision: two enemy MOVE motions crossing paths.
        Case 1: both heading to the same destination.
        Case 2: heading to each other's source (head-on swap).
        The one started first (earlier index) wins — the other is eliminated.
        """
        eliminated_ids = set()
        events = []
        for i, m1 in enumerate(arrived):
            if id(m1) in eliminated_ids or m1.motion_type != MotionType.MOVE:
                continue
            for m2 in arrived[i + 1:]:
                if (id(m2) not in eliminated_ids
                        and m2.motion_type == MotionType.MOVE
                        and m2.piece.color != m1.piece.color
                        and (m2.to_pos == m1.to_pos
                             or (m1.to_pos == m2.from_pos and m2.to_pos == m1.from_pos))):
                    m2.piece.state = PieceState.CAPTURED
                    eliminated_ids.add(id(m2))
                    events.append(EliminationEvent(piece=m2.piece, current_pos=m2.from_pos))
        survived = [m for m in arrived if id(m) not in eliminated_ids]
        return survived, events

    def advance_time(self, ms: int) -> list[RealTimeEvent]:
        """
        Advances simulated time. Returns a list of RealTimeEvents (ArrivalEvent / EliminationEvent).
        GameEngine is responsible for applying them to the Board.
        """
        if not self._active_motions:
            return []

        for motion in self._active_motions:
            motion.remaining_ms -= ms

        arrived = [m for m in self._active_motions if m.remaining_ms <= 0]
        self._active_motions = [m for m in self._active_motions if m.remaining_ms > 0]

        arrived, elimination_events = self._eliminate_simultaneous_collisions(arrived)

        # Resolve MOVE before JUMP so air-capture is checked while the piece is still airborne
        arrived.sort(key=lambda m: 0 if m.motion_type == MotionType.MOVE else 1)

        events: list[RealTimeEvent] = list(elimination_events)
        for motion in arrived:
            events.extend(self._resolve_arrival(motion))
        return events

    def _resolve_late_collision(self, motion: Motion) -> list[EliminationEvent]:
        """
        Collision: if another MOVE motion is heading to the same destination,
        the one that started LATER (still moving) loses — the one that arrived first wins.
        """
        events = []
        for other in list(self._active_motions):
            if (other.motion_type == MotionType.MOVE
                    and other.to_pos == motion.to_pos
                    and other.piece.color != motion.piece.color):
                other.piece.state = PieceState.CAPTURED
                self._active_motions.remove(other)
                events.append(EliminationEvent(piece=other.piece, current_pos=other.from_pos))
        return events

    def _resolve_air_capture(self, motion: Motion) -> Optional[EliminationEvent]:
        """
        Air-capture: if the arriving piece reaches the cell of an airborne enemy — the arriving piece is eliminated.
        Returns an EliminationEvent if eliminated, otherwise None.
        """
        if self._airborne_pos != motion.to_pos:
            return None
        airborne_color = self._get_airborne_piece_color(motion)
        if airborne_color is not None and motion.piece.color != airborne_color:
            motion.piece.state = PieceState.CAPTURED
            self._airborne_pos = None
            return EliminationEvent(piece=motion.piece, current_pos=motion.from_pos)
        return None

    def _get_airborne_piece_color(self, motion: Motion):
        """Returns the color of the airborne piece at motion.to_pos, by finding its motion."""
        for m in self._active_motions:
            if m.motion_type == MotionType.JUMP and m.from_pos == motion.to_pos:
                return m.piece.color
        return None

    def _resolve_move(self, motion: Motion) -> list[ArrivalEvent]:
        """Regular MOVE: reports arrival — GameEngine will move the piece on the board."""
        motion.piece.state = PieceState.IDLE
        self._airborne_pos = None
        return [ArrivalEvent(
            arriving_piece=motion.piece,
            from_pos=motion.from_pos,
            destination=motion.to_pos,
        )]

    def _resolve_arrival(self, motion: Motion) -> list[RealTimeEvent]:
        if motion.motion_type == MotionType.JUMP:
            motion.piece.state = PieceState.IDLE
            self._airborne_pos = None
            return []

        events: list[RealTimeEvent] = self._resolve_late_collision(motion)

        elimination = self._resolve_air_capture(motion)
        if elimination:
            return events + [elimination]

        return events + self._resolve_move(motion)
