"""
Shared drawing utilities: pure functions and data types used by all draw layers.
No dependency on GameSnapshot or UiConfig — only numpy primitives.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class BoardRect:
    x: int
    y: int
    width: int
    height: int


# Named scaling ratios — all derived from cell_size, no magic numbers in draw layers
COORD_FONT_RATIO   = 180.0   # cell_size / COORD_FONT_RATIO   → coordinate label font size
SCORE_FONT_RATIO   = 120.0   # cell_size / SCORE_FONT_RATIO   → score label font size
HEADER_FONT_RATIO  = 140.0   # cell_size / HEADER_FONT_RATIO  → table header font size
ROW_FONT_RATIO     = 160.0   # cell_size / ROW_FONT_RATIO     → table row font size
COORD_PAD_DIVISOR  = 3       # cell_size // COORD_PAD_DIVISOR → padding around coordinates
CHAR_W_DIVISOR     = 12      # cell_size // CHAR_W_DIVISOR    → half-width of a coord character
SCORE_X_RATIO      = 0.6     # cell_size * SCORE_X_RATIO      → score label x offset from centre
ROW_H_DIVISOR      = 3       # cell_size // ROW_H_DIVISOR     → table row height
ROW_H_MIN          = 24      # minimum row height in pixels
HEADER_H_DIVISOR   = 2       # cell_size // HEADER_H_DIVISOR  → table header height
HEADER_H_MIN       = 36      # minimum header height in pixels


def blend_overlay(roi: np.ndarray, color_bgra: tuple, alpha: float) -> None:
    """Alpha-blends a solid color onto a numpy ROI in-place."""
    roi[..., :3] = (
        roi[..., :3].astype(np.float32) * (1 - alpha)
        + np.array(color_bgra[:3], np.float32) * alpha
    ).astype(np.uint8)


def format_elapsed_ms(ms: int) -> str:
    """Formats elapsed milliseconds as MM:SS.mmm."""
    mins   = ms // 60_000
    secs   = (ms % 60_000) // 1000
    millis = ms % 1000
    return f"{mins:02d}:{secs:02d}.{millis:03d}"
