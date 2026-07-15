from __future__ import annotations
import json
import pathlib
from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState

_ASSETS_ROOT = pathlib.Path(__file__).parents[2] / "assets" / "pieces2"
_FRAME_COUNT = 5

_STATE_DIR = {
    PieceState.IDLE:       "idle",
    PieceState.MOVING:     "move",
    PieceState.JUMPING:    "jump",
    PieceState.LONG_REST:  "long_rest",
    PieceState.SHORT_REST: "short_rest",
}


def _state_dir(state: PieceState) -> str:
    return _STATE_DIR.get(state, "idle")


def _load_config(kind: PieceKind, color: PieceColor, state: PieceState) -> dict:
    color_char = "W" if color == PieceColor.WHITE else "B"
    path = _ASSETS_ROOT / f"{kind.value}{color_char}" / "states" / _state_dir(state) / "config.json"
    if not path.exists():
        return {"graphics": {"frames_per_sec": 6, "is_loop": True}}
    with open(path) as f:
        return json.load(f)


_REST_STATES = {PieceState.LONG_REST, PieceState.SHORT_REST}


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
        """Accumulates game time. Call with the same ms as engine.wait(ms)."""
        self._elapsed_ms += ms

    def get_frame(self, piece_id: str, kind: PieceKind, color: PieceColor,
                  state: PieceState) -> pathlib.Path:
        """Returns the sprite path for the correct animation frame."""
        if self._last_state.get(piece_id) != state:
            self._start[piece_id] = self._elapsed_ms
            self._last_state[piece_id] = state

        config = _load_config(kind, color, state)
        fps = config["graphics"]["frames_per_sec"]
        is_loop = config["graphics"]["is_loop"]

        elapsed_ms = self._elapsed_ms - self._start.get(piece_id, 0.0)
        frame_duration_ms = 1000.0 / fps
        frame_index = int(elapsed_ms / frame_duration_ms)

        if is_loop:
            frame_index = frame_index % _FRAME_COUNT
        else:
            frame_index = min(frame_index, _FRAME_COUNT - 1)

        color_char = "W" if color == PieceColor.WHITE else "B"
        return (
            _ASSETS_ROOT
            / f"{kind.value}{color_char}"
            / "states"
            / _state_dir(state)
            / "sprites"
            / f"{frame_index + 1}.png"
        )

    def get_rest_progress(self, piece_id: str, kind: PieceKind,
                          color: PieceColor, state: PieceState) -> float:
        """
        Returns how far along the rest animation is: 0.0 (just started) → 1.0 (done).
        Only meaningful when state is LONG_REST or SHORT_REST.
        """
        if state not in _REST_STATES:
            return 0.0
        config = _load_config(kind, color, state)
        fps = config["graphics"]["frames_per_sec"]
        total_ms = (_FRAME_COUNT / fps) * 1000.0
        elapsed_ms = self._elapsed_ms - self._start.get(piece_id, self._elapsed_ms)
        return min(elapsed_ms / total_ms, 1.0)
