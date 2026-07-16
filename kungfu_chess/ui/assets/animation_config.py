"""
Responsible for reading animation config.json files from the asset folder.
Knows nothing about timing or frame selection — only disk I/O.
"""
from __future__ import annotations
import json
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.ui.assets.asset_paths import get_config_path

_DEFAULT_ANIMATION_CONFIG = {"graphics": {"frames_per_sec": 6, "is_loop": True}}


def load_animation_config(kind: PieceKind, color: PieceColor, state: PieceState) -> dict:
    """Returns the animation config for a piece state. Falls back to defaults if missing."""
    path = get_config_path(kind, color, state)
    if not path.exists():
        return _DEFAULT_ANIMATION_CONFIG
    with open(path, "rb") as f:
        return json.load(f)
