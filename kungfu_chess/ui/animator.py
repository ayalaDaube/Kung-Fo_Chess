"""
Tracks per-piece animation state and returns the correct sprite frame path.
Depends on assets/ for path resolution and config loading — contains no disk I/O itself.

Two improvements over the naive elapsed-clock approach:
  1. motion_progress sync: for moving/jumping pieces the frame index is driven by
     motion_progress (0.0→1.0 from the snapshot) so a 1-square move and a 7-square
     move animate at the correct relative speed, not the same wall-clock rate.
  2. next_state_when_finished: when a non-looping animation finishes its frames before
     the engine sends the next PieceState, frame-1 of the configured next state is shown
     instead of freezing on the last frame. Visual only — piece.state is never touched.
"""
from __future__ import annotations
import pathlib
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState
from kungfu_chess.ui.assets.asset_paths import (
    get_sprite_frame_path, frame_count, REST_STATES,
)
from kungfu_chess.ui.assets.animation_config import (
    load_animation_config, _DEFAULT_ANIMATION_CONFIG,
)

# States whose frame index is driven by motion_progress instead of wall-clock
_MOTION_DRIVEN = frozenset({PieceState.MOVING, PieceState.JUMPING})

def _load_config(kind: PieceKind, color: PieceColor, state: PieceState,
                 resolve_path=None) -> dict:
    """Delegates to load_animation_config; kept for backward-compatible test imports."""
    kwargs = {"resolve_path": resolve_path} if resolve_path is not None else {}
    return load_animation_config(kind, color, state, **kwargs)


def _next_state_name(config: dict) -> str | None:
    """Reads physics.next_state_when_finished from config, returns None if absent."""
    return config.get("physics", {}).get("next_state_when_finished")


class Animator:
    """
    Tracks per-piece animation state and returns the correct sprite frame path.
    advance(ms) must be called every game tick with the same ms passed to engine.wait().
    """

    def __init__(self):
        self._elapsed_ms: float = 0.0
        self._start: dict[str, float] = {}
        self._last_state: dict[str, PieceState] = {}

    def advance(self, ms: float) -> None:
        self._elapsed_ms += ms

    def get_frame(self, piece_id: str, kind: PieceKind, color: PieceColor,
                  state: PieceState, motion_progress: float = 1.0) -> pathlib.Path:
        """
        Returns the sprite path for the correct animation frame.

        For MOVING/JUMPING states, motion_progress (0.0→1.0 from PieceSnapshot)
        drives the frame index so animation speed matches actual movement distance.
        For all other states, wall-clock elapsed time drives the frame index.
        """
        if self._last_state.get(piece_id) != state:
            self._start[piece_id] = self._elapsed_ms
            self._last_state[piece_id] = state

        config = _load_config(kind, color, state)
        total  = frame_count(kind, color, state)

        if state in _MOTION_DRIVEN:
            frame_index = self._motion_driven_frame(motion_progress, total)
        else:
            frame_index = self._clock_driven_frame(piece_id, config, total, kind, color, state)
            if isinstance(frame_index, pathlib.Path):
                return frame_index

        return get_sprite_frame_path(kind, color, state, frame=frame_index + 1)

    def _motion_driven_frame(self, motion_progress: float, total: int) -> int:
        return min(int(motion_progress * total), total - 1)

    def _clock_driven_frame(self, piece_id: str, config: dict, total: int,
                            kind: PieceKind, color: PieceColor,
                            state: PieceState) -> int | pathlib.Path:
        fps        = config["graphics"]["frames_per_sec"]
        is_loop    = config["graphics"]["is_loop"]
        elapsed_ms = self._elapsed_ms - self._start.get(piece_id, 0.0)
        frame_index = int(elapsed_ms / (1000.0 / fps))
        if is_loop:
            return frame_index % total
        if frame_index >= total:
            return self._finished_frame_path(config, kind, color) or (total - 1)
        return min(frame_index, total - 1)

    def _finished_frame_path(self, config: dict, kind: PieceKind,
                             color: PieceColor) -> pathlib.Path | None:
        """Returns frame-1 path of the next state when a non-looping animation finishes."""
        next_state = _next_state_name(config)
        if next_state is None:
            return None
        try:
            return get_sprite_frame_path(kind, color, PieceState(next_state), frame=1)
        except ValueError:
            return None

    def get_rest_progress(self, piece_id: str, kind: PieceKind,
                          color: PieceColor, state: PieceState,
                          rest_duration_ms: float) -> float:
        """Returns rest progress: 0.0 (just started) → 1.0 (done)."""
        if state not in REST_STATES:
            return 0.0
        elapsed_ms = self._elapsed_ms - self._start.get(piece_id, self._elapsed_ms)
        return min(elapsed_ms / rest_duration_ms, 1.0)
