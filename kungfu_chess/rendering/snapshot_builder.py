from __future__ import annotations
from typing import Optional
from kungfu_chess.model.board import Board
from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot
from kungfu_chess.model.piece import PieceState
from kungfu_chess.model.position import Position
from kungfu_chess.realtime.real_time_arbiter import RealTimeArbiter
from kungfu_chess.rendering.game_stats_tracker import GameStatsTracker


def _piece_pixel_position(piece, arbiter: RealTimeArbiter, cell_size_px: int) -> tuple[float, float]:
    motion = arbiter.get_motion_for(piece)
    if motion is not None and motion.to_pos is not None:
        total_ms = (max(
            abs(motion.to_pos.row - motion.from_pos.row),
            abs(motion.to_pos.col - motion.from_pos.col),
        ) * arbiter.ms_per_square)
        elapsed = total_ms - motion.remaining_ms
        t = min(elapsed / total_ms, 1.0) if total_ms > 0 else 1.0
        px = (motion.from_pos.col + t * (motion.to_pos.col - motion.from_pos.col)) * cell_size_px
        py = (motion.from_pos.row + t * (motion.to_pos.row - motion.from_pos.row)) * cell_size_px
    else:
        px = piece.cell.col * cell_size_px
        py = piece.cell.row * cell_size_px
    return px, py


def build_snapshot(board: Board, arbiter: RealTimeArbiter, cell_size_px: int,
                   selected_cell: Optional[Position], game_over: bool,
                   stats: Optional[GameStatsTracker] = None) -> GameSnapshot:
    """Builds a read-only GameSnapshot DTO for the Renderer, with pixel-interpolated piece positions."""
    pieces_data = []
    for piece in board.all_pieces():
        if piece.state == PieceState.CAPTURED:
            continue
        px, py = _piece_pixel_position(piece, arbiter, cell_size_px)
        pieces_data.append(PieceSnapshot(
            id=piece.id,
            kind=piece.kind,
            color=piece.color,
            cell=piece.cell,
            state=piece.state,
            pixel_x=px,
            pixel_y=py,
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
    )
