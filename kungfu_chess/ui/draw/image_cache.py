"""
Responsible for loading and caching images from disk.
All other draw layers request images through ImageCache — none load directly.
"""
from __future__ import annotations
import numpy as np
from img import Img


class ImageCache:
    """Loads images from disk on first request and returns cached numpy arrays thereafter."""

    def __init__(self):
        self._cache: dict[tuple, np.ndarray] = {}

    def get(self, path, width: int, height: int, keep_aspect: bool = False) -> np.ndarray:
        key = (str(path), width, height, keep_aspect)
        if key not in self._cache:
            self._cache[key] = Img().read(str(path), size=(width, height), keep_aspect=keep_aspect).img
        return self._cache[key]
