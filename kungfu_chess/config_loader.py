import json
import os
from dataclasses import dataclass, field

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.json")


@dataclass(frozen=True)
class UiConfig:
    table_margin: int
    table_inner_pad: int
    time_col_ratio: float
    min_table_width: int
    bg_color: tuple
    text_color: tuple
    header_color: tuple
    black_header_color: tuple
    white_header_color: tuple
    black_row_even: tuple
    black_row_odd: tuple
    white_row_even: tuple
    white_row_odd: tuple
    black_text_color: tuple
    white_text_color: tuple
    black_line_color: tuple
    white_line_color: tuple
    selected_cell_color: tuple
    airborne_cell_color: tuple
    cooldown_color: tuple
    game_over_color: tuple
    game_over_font_size: float
    game_over_thickness: int


@dataclass(frozen=True)
class GameConfig:
    ms_per_pixel: int
    ms_per_square: int
    jump_duration_ms: int
    long_rest_ms: int
    short_rest_ms: int
    cell_size: int
    ui: UiConfig
    piece_scores: dict
    screen_fill_pct: int
    table_cells_wide: int
    window_title: str
    frame_interval_ms: int
    client_log_path: str

    @property
    def computed_ms_per_square(self) -> int:
        """ms_per_square derived from cell_size * ms_per_pixel (used when ms_per_square not set explicitly)."""
        return self.cell_size * self.ms_per_pixel


_DEFAULT_UI = {
    "table_margin": 5,
    "table_inner_pad": 4,
    "time_col_ratio": 0.52,
    "min_table_width": 40,
    "bg_color": [105, 105, 105],
    "text_color": [230, 230, 230],
    "header_color": [255, 255, 255],
    "black_header_color": [40, 40, 80],
    "white_header_color": [80, 60, 20],
    "black_row_even": [50, 50, 90],
    "black_row_odd": [35, 35, 70],
    "white_row_even": [90, 65, 25],
    "white_row_odd": [70, 50, 15],
    "black_text_color": [220, 220, 255],
    "white_text_color": [255, 240, 200],
    "black_line_color": [120, 120, 180],
    "white_line_color": [180, 150, 80],
    "selected_cell_color": [100, 200, 100],
    "airborne_cell_color": [100, 100, 220],
    "cooldown_color": [255, 215, 0],
    "game_over_color": [255, 0, 0],
    "game_over_font_size": 2.0,
    "game_over_thickness": 4,
}

_DEFAULT_PIECE_SCORES = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 0}


def _to_bgra(rgb: list) -> tuple:
    """Converts an [R, G, B] list from config to (B, G, R, A) tuple for OpenCV."""
    return (rgb[2], rgb[1], rgb[0], 255)


def _to_bgra_alpha(rgb: list, alpha: int) -> tuple:
    """Converts an [R, G, B] list with a given alpha to (B, G, R, A) tuple for OpenCV."""
    return (rgb[2], rgb[1], rgb[0], alpha)


def load_config(path: str = _CONFIG_PATH) -> GameConfig:
    """Loads game configuration from a JSON file. Falls back to defaults if file is missing."""
    defaults = {
        "ms_per_pixel": 10,
        "ms_per_square": 1000,
        "jump_duration_ms": 1000,
        "long_rest_ms": 5000,
        "short_rest_ms": 2500,
        "cell_size": 100,
        "screen_fill_pct": 75,
        "table_cells_wide": 3,
        "window_title": "Kung-Fo Chess",
        "frame_interval_ms": 16,
        "client_log_path": "client.log",
    }
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except FileNotFoundError:  # pragma: no cover
        data = {}

    merged = {**defaults, **data}
    ui_raw = {**_DEFAULT_UI, **merged.get("ui", {})}
    scores = {**_DEFAULT_PIECE_SCORES, **merged.get("piece_scores", {})}

    ui = UiConfig(
        table_margin=ui_raw["table_margin"],
        table_inner_pad=ui_raw["table_inner_pad"],
        time_col_ratio=ui_raw["time_col_ratio"],
        min_table_width=ui_raw["min_table_width"],
        bg_color=_to_bgra(ui_raw["bg_color"]),
        text_color=_to_bgra(ui_raw["text_color"]),
        header_color=_to_bgra(ui_raw["header_color"]),
        black_header_color=_to_bgra(ui_raw["black_header_color"]),
        white_header_color=_to_bgra(ui_raw["white_header_color"]),
        black_row_even=_to_bgra(ui_raw["black_row_even"]),
        black_row_odd=_to_bgra(ui_raw["black_row_odd"]),
        white_row_even=_to_bgra(ui_raw["white_row_even"]),
        white_row_odd=_to_bgra(ui_raw["white_row_odd"]),
        black_text_color=_to_bgra(ui_raw["black_text_color"]),
        white_text_color=_to_bgra(ui_raw["white_text_color"]),
        black_line_color=_to_bgra(ui_raw["black_line_color"]),
        white_line_color=_to_bgra(ui_raw["white_line_color"]),
        selected_cell_color=_to_bgra_alpha(ui_raw["selected_cell_color"], 100),
        airborne_cell_color=_to_bgra_alpha(ui_raw["airborne_cell_color"], 100),
        cooldown_color=_to_bgra_alpha(ui_raw["cooldown_color"], 160),
        game_over_color=_to_bgra(ui_raw["game_over_color"]),
        game_over_font_size=ui_raw["game_over_font_size"],
        game_over_thickness=ui_raw["game_over_thickness"],
    )

    return GameConfig(
        ms_per_pixel=merged["ms_per_pixel"],
        ms_per_square=merged["ms_per_square"],
        jump_duration_ms=merged["jump_duration_ms"],
        long_rest_ms=merged["long_rest_ms"],
        short_rest_ms=merged["short_rest_ms"],
        cell_size=merged["cell_size"],
        ui=ui,
        piece_scores=scores,
        screen_fill_pct=merged["screen_fill_pct"],
        table_cells_wide=merged["table_cells_wide"],
        window_title=merged["window_title"],
        frame_interval_ms=merged["frame_interval_ms"],
        client_log_path=merged["client_log_path"],
    )
