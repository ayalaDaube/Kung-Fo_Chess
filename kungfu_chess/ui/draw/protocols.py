"""
Protocol interfaces for the draw layer.
All concrete implementations satisfy these via duck-typing — no inheritance required.
Enables fake/stub implementations in tests without opening a cv2 window or touching disk.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
import pathlib
import numpy as np
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState


@runtime_checkable
class DrawLayer(Protocol):
    """Any object that can draw itself onto a canvas given a snapshot."""
    def draw(self, canvas, snapshot) -> None: ...


@runtime_checkable
class AnimatorProtocol(Protocol):
    """Minimal surface of Animator that PieceLayer depends on."""
    def advance(self, ms: float) -> None: ...
    def get_frame(self, piece_id: str, kind: PieceKind, color: PieceColor,
                  state: PieceState, motion_progress: float) -> pathlib.Path: ...
    def get_rest_progress(self, piece_id: str, kind: PieceKind, color: PieceColor,
                          state: PieceState, rest_duration_ms: float) -> float: ...


@runtime_checkable
class ImageCacheProtocol(Protocol):
    """Minimal surface of ImageCache that draw layers depend on."""
    def get(self, path, width: int, height: int, keep_aspect: bool) -> np.ndarray: ...
