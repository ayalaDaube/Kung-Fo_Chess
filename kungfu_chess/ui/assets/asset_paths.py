"""
Single source of truth for all sprite asset path construction and shared UI constants.
No other module should build piece asset paths or redefine these constants independently.
"""
from __future__ import annotations
import pathlib
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState

_ASSETS_ROOT = pathlib.Path(__file__).parents[3] / "assets" / "pieces2"

_STATE_DIR: dict[PieceState, str] = {
    PieceState.IDLE:       "idle",
    PieceState.MOVING:     "move",
    PieceState.JUMPING:    "jump",
    PieceState.LONG_REST:  "long_rest",
    PieceState.SHORT_REST: "short_rest",
}

_FRAME_COUNT_FALLBACK = 5  # used only when sprite folder is missing or empty

COL_LETTERS = "abcdefghijklmnopqrstuvwxyz"
REST_STATES = frozenset({PieceState.LONG_REST, PieceState.SHORT_REST})

_sprite_frame_count_cache: dict[tuple, int] = {}


def _color_char(color: PieceColor) -> str:
    return "w" if color == PieceColor.WHITE else "b"


def _state_dir(state: PieceState) -> str:
    return _STATE_DIR.get(state, "idle")


def get_piece_root(kind: PieceKind, color: PieceColor) -> pathlib.Path:
    return _ASSETS_ROOT / f"{_color_char(color)}{kind.value}"


def get_config_path(kind: PieceKind, color: PieceColor, state: PieceState) -> pathlib.Path:
    return get_piece_root(kind, color) / "states" / _state_dir(state) / "config.json"


def get_sprite_frame_path(kind: PieceKind, color: PieceColor,
                          state: PieceState, frame: int) -> pathlib.Path:
    return get_piece_root(kind, color) / "states" / _state_dir(state) / "sprites" / f"{frame}.png"


def frame_count(kind: PieceKind = None, color: PieceColor = None,
                state: PieceState = None) -> int:
    """Returns the actual frame count by counting .png files in the sprites folder.
    Falls back to _FRAME_COUNT_FALLBACK if the folder is missing or empty.
    Called with no args returns the fallback (used by tests and as a safe default)."""
    if kind is None or color is None or state is None:
        return _FRAME_COUNT_FALLBACK
    key = (kind, color, state)
    if key not in _sprite_frame_count_cache:
        sprites_dir = get_piece_root(kind, color) / "states" / _state_dir(state) / "sprites"
        frames = list(sprites_dir.glob("*.png")) if sprites_dir.exists() else []
        _sprite_frame_count_cache[key] = len(frames) if frames else _FRAME_COUNT_FALLBACK
    return _sprite_frame_count_cache[key]
