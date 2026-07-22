from __future__ import annotations
from typing import Optional, Protocol, runtime_checkable
from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot, MoveRecord
from kungfu_chess.model.piece import PieceColor, PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter


@runtime_checkable
class StatsProvider(Protocol):
    """Minimal interface engine needs from a stats tracker. ui.GameStatsTracker satisfies this."""
    @property
    def scores(self) -> dict[PieceColor, int]: ...
    @property
    def move_history(self) -> list[MoveRecord]: ...


def _motion_info(piece, arbiter: RealTimeArbiter) -> tuple[Optional[Position], float]:
    """Returns (target_cell, motion_progress). target_cell is None when piece is settled."""
    motion = arbiter.get_motion_for(piece)
    if motion is None or motion.to_pos is None or motion.to_pos == motion.from_pos:
        return None, 1.0
    total_ms = max(
        abs(motion.to_pos.row - motion.from_pos.row),
        abs(motion.to_pos.col - motion.from_pos.col),
    ) * arbiter.ms_per_square
    elapsed = total_ms - motion.remaining_ms
    t = min(elapsed / total_ms, 1.0) if total_ms > 0 else 1.0
    return motion.to_pos, t


def build_snapshot(board: Board, arbiter: RealTimeArbiter,
                   selected_cell: Optional[Position], game_over: bool,
                   stats: Optional[StatsProvider] = None,
                   winner_color: Optional[PieceColor] = None) -> GameSnapshot:
    """Builds a pixel-agnostic GameSnapshot DTO. All positions are in board-space."""
    pieces_data = []
    for piece in board.all_pieces():
        if piece.state == PieceState.CAPTURED:
            continue
        target_cell, t = _motion_info(piece, arbiter)
        pieces_data.append(PieceSnapshot(
            id=piece.id,
            kind=piece.kind,
            color=piece.color,
            cell=piece.cell,
            state=piece.state,
            motion_progress=t,
            target_cell=target_cell,
        ))

    return GameSnapshot(
        board_width=board.width,
        board_height=board.height,
        pieces=pieces_data,
        selected_cell=selected_cell,
        game_over=game_over,
        airborne_pos=arbiter.airborne_position(),
        scores=stats.scores if stats else {},
        move_history=stats.move_history if stats else [],
        winner_color=winner_color,
    )
