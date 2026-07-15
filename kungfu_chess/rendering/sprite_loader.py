from __future__ import annotations
import pathlib
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState

_ASSETS_ROOT = pathlib.Path(__file__).parents[2] / "assets" / "pieces2"


_STATE_DIR = {
    PieceState.IDLE:   "idle",
    PieceState.MOVING: "move",
}


def get_sprite_path(kind: PieceKind, color: PieceColor, state: PieceState) -> pathlib.Path:
    """Return path to frame-1 sprite for the given piece kind/color/state."""
    color_char = "W" if color == PieceColor.WHITE else "B"
    state_dir = _STATE_DIR.get(state, "idle")
    return _ASSETS_ROOT / f"{kind.value}{color_char}" / "states" / state_dir / "sprites" / "1.png"
