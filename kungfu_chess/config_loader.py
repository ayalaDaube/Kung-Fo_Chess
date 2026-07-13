import json
import os
from dataclasses import dataclass

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")


@dataclass(frozen=True)
class GameConfig:
    ms_per_pixel: int
    ms_per_square: int
    jump_duration_ms: int
    cell_size: int


def load_config(path: str = _CONFIG_PATH) -> GameConfig:
    """Loads game configuration from a JSON file. Falls back to defaults if file is missing."""
    defaults = {
        "ms_per_pixel": 10,
        "ms_per_square": 1000,
        "jump_duration_ms": 1000,
        "cell_size": 100,
    }
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:  # pragma: no cover
        data = {}

    merged = {**defaults, **data}
    return GameConfig(
        ms_per_pixel=merged["ms_per_pixel"],
        ms_per_square=merged["ms_per_square"],
        jump_duration_ms=merged["jump_duration_ms"],
        cell_size=merged["cell_size"],
    )
