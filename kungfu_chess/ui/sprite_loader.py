from __future__ import annotations
import pathlib
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.ui.asset_paths import get_sprite_frame_path


def get_sprite_path(kind: PieceKind, color: PieceColor, state: PieceState) -> pathlib.Path:
    """Return path to frame-1 sprite for the given piece kind/color/state."""
    return get_sprite_frame_path(kind, color, state, frame=1)
