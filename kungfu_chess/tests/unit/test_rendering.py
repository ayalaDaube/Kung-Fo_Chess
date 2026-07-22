"""
Unit tests for the UI rendering layer:
  - asset_paths
  - animator
  - renderer (pure logic: _format_elapsed_ms, _blend_overlay, sizing helpers)
  - game_stats_tracker (EliminationEvent branch)
"""
from __future__ import annotations
import pathlib
import unittest

import numpy as np

from kungfu_chess.model.piece import PieceColor, PieceKind, PieceState, Piece
from kungfu_chess.model.position import Position
from kungfu_chess.model.game_state import GameSnapshot, PieceSnapshot, MoveRecord
from kungfu_chess.ui.assets.asset_paths import (
    get_piece_root, get_config_path, get_sprite_frame_path,
    frame_count, COL_LETTERS, REST_STATES, _state_dir, _color_char,
)
from kungfu_chess.ui.animator import Animator, _load_config, _DEFAULT_ANIMATION_CONFIG
from kungfu_chess.ui.renderer import _format_elapsed_ms, _blend_overlay, Renderer


# ---------------------------------------------------------------------------
# asset_paths
# ---------------------------------------------------------------------------

class TestAssetPaths(unittest.TestCase):

    def test_color_char_white(self):
        self.assertEqual(_color_char(PieceColor.WHITE), "w")

    def test_color_char_black(self):
        self.assertEqual(_color_char(PieceColor.BLACK), "b")

    def test_state_dir_known(self):
        self.assertEqual(_state_dir(PieceState.IDLE), "idle")
        self.assertEqual(_state_dir(PieceState.MOVING), "move")
        self.assertEqual(_state_dir(PieceState.JUMPING), "jump")
        self.assertEqual(_state_dir(PieceState.LONG_REST), "long_rest")
        self.assertEqual(_state_dir(PieceState.SHORT_REST), "short_rest")

    def test_state_dir_unknown_falls_back_to_idle(self):
        self.assertEqual(_state_dir(PieceState.CAPTURED), "idle")

    def test_get_piece_root_contains_kind_and_color(self):
        root = get_piece_root(PieceKind.ROOK, PieceColor.WHITE)
        self.assertTrue(str(root).endswith("wR"))

    def test_get_config_path_structure(self):
        path = get_config_path(PieceKind.KING, PieceColor.BLACK, PieceState.IDLE)
        self.assertTrue(str(path).endswith("config.json"))
        self.assertIn("bK", str(path))
        self.assertIn("idle", str(path))

    def test_get_sprite_frame_path_structure(self):
        path = get_sprite_frame_path(PieceKind.PAWN, PieceColor.WHITE, PieceState.MOVING, frame=3)
        self.assertTrue(str(path).endswith("3.png"))
        self.assertIn("wP", str(path))
        self.assertIn("move", str(path))

    def test_frame_count_fallback(self):
        self.assertEqual(frame_count(), 5)

    def test_col_letters_starts_with_a(self):
        self.assertEqual(COL_LETTERS[0], "a")
        self.assertEqual(COL_LETTERS[7], "h")

    def test_rest_states_contains_both_rests(self):
        self.assertIn(PieceState.LONG_REST, REST_STATES)
        self.assertIn(PieceState.SHORT_REST, REST_STATES)
        self.assertNotIn(PieceState.IDLE, REST_STATES)


# ---------------------------------------------------------------------------
# animator
# ---------------------------------------------------------------------------

class TestAnimatorLoadConfig(unittest.TestCase):

    def test_load_config_returns_default_for_missing_path(self):
        config = _load_config(
            PieceKind.PAWN, PieceColor.WHITE, PieceState.IDLE,
            resolve_path=lambda *_: pathlib.Path("/nonexistent"),
        )
        self.assertEqual(config, _DEFAULT_ANIMATION_CONFIG)

    def test_load_config_returns_dict_for_existing_path(self):
        config = _load_config(PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE)
        self.assertIn("graphics", config)


class TestAnimator(unittest.TestCase):

    def setUp(self):
        self.animator = Animator()

    def test_initial_elapsed_is_zero(self):
        self.assertEqual(self.animator._elapsed_ms, 0.0)

    def test_advance_accumulates(self):
        self.animator.advance(100)
        self.animator.advance(200)
        self.assertEqual(self.animator._elapsed_ms, 300.0)

    def test_get_frame_returns_path(self):
        path = self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE)
        self.assertIsInstance(path, pathlib.Path)
        self.assertTrue(str(path).endswith(".png"))

    def test_get_frame_resets_start_on_state_change(self):
        self.animator.advance(500)
        self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE)
        self.animator.advance(100)
        self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.MOVING)
        # start should have been reset to 600
        self.assertEqual(self.animator._start["p1"], 600.0)

    def test_get_frame_loops_animation(self):
        # Read actual fps from config so the test stays correct regardless of asset fps value
        config = _load_config(PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE)
        fps = config["graphics"]["frames_per_sec"]
        loop_ms = int(1000.0 / fps * 5) + 1  # just past one full 5-frame cycle
        self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE)
        self.animator.advance(loop_ms)
        path = self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE)
        self.assertTrue(str(path).endswith("1.png"))

    def test_get_rest_progress_zero_for_non_rest_state(self):
        progress = self.animator.get_rest_progress("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.IDLE, 1000)
        self.assertEqual(progress, 0.0)

    def test_get_rest_progress_increases_over_time(self):
        self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.LONG_REST)
        self.animator.advance(500)
        progress = self.animator.get_rest_progress("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.LONG_REST, 1000)
        self.assertAlmostEqual(progress, 0.5, places=1)

    def test_get_rest_progress_capped_at_1(self):
        self.animator.get_frame("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.LONG_REST)
        self.animator.advance(9999)
        progress = self.animator.get_rest_progress("p1", PieceKind.ROOK, PieceColor.WHITE, PieceState.LONG_REST, 1000)
        self.assertEqual(progress, 1.0)

    def test_get_rest_progress_zero_when_piece_never_seen(self):
        # piece_id not in _start → uses _elapsed_ms as start → elapsed=0 → progress=0
        progress = self.animator.get_rest_progress("unknown", PieceKind.ROOK, PieceColor.WHITE, PieceState.LONG_REST, 1000)
        self.assertEqual(progress, 0.0)


# ---------------------------------------------------------------------------
# renderer — pure logic (no OpenCV window)
# ---------------------------------------------------------------------------

class TestFormatElapsedMs(unittest.TestCase):

    def test_zero(self):
        self.assertEqual(_format_elapsed_ms(0), "00:00.000")

    def test_one_second(self):
        self.assertEqual(_format_elapsed_ms(1000), "00:01.000")

    def test_one_minute(self):
        self.assertEqual(_format_elapsed_ms(60_000), "01:00.000")

    def test_mixed(self):
        self.assertEqual(_format_elapsed_ms(75_123), "01:15.123")

    def test_millis_only(self):
        self.assertEqual(_format_elapsed_ms(42), "00:00.042")


class TestBlendOverlay(unittest.TestCase):

    def test_full_alpha_replaces_color(self):
        roi = np.zeros((10, 10, 4), dtype=np.uint8)
        _blend_overlay(roi, (255, 0, 0, 255), 1.0)
        self.assertTrue(np.all(roi[..., 0] == 255))
        self.assertTrue(np.all(roi[..., 1] == 0))

    def test_zero_alpha_leaves_unchanged(self):
        roi = np.full((10, 10, 4), 128, dtype=np.uint8)
        _blend_overlay(roi, (0, 0, 0, 0), 0.0)
        self.assertTrue(np.all(roi[..., :3] == 128))

    def test_half_alpha_blends(self):
        roi = np.zeros((1, 1, 4), dtype=np.uint8)
        _blend_overlay(roi, (200, 0, 0, 128), 0.5)
        self.assertEqual(roi[0, 0, 0], 100)


class TestRendererSizingHelpers(unittest.TestCase):

    def setUp(self):
        self.r = Renderer(cell_size=100)

    def test_coord_font_size(self):
        self.assertAlmostEqual(self.r._coord_font_size(), 100 / 180.0)

    def test_table_font_size(self):
        self.assertAlmostEqual(self.r._table_font_size(), 100 / 160.0)

    def test_table_header_font_size(self):
        self.assertAlmostEqual(self.r._table_header_font_size(), 100 / 140.0)

    def test_score_font_size(self):
        self.assertAlmostEqual(self.r._score_font_size(), 100 / 120.0)

    def test_row_height_normal(self):
        self.assertEqual(self.r._row_height(), 33)

    def test_row_height_minimum(self):
        r = Renderer(cell_size=10)
        self.assertEqual(r._row_height(), 24)

    def test_header_height_normal(self):
        self.assertEqual(self.r._header_height(), 50)

    def test_header_height_minimum(self):
        r = Renderer(cell_size=10)
        self.assertEqual(r._header_height(), 36)

    def test_coord_pad(self):
        self.assertEqual(self.r._coord_pad(), 33)

    def test_score_x_offset(self):
        self.assertEqual(self.r._score_x_offset(), 60)


# ---------------------------------------------------------------------------
# snapshot_builder
# ---------------------------------------------------------------------------

class TestSnapshotBuilder(unittest.TestCase):

    def _make_snapshot(self, **kwargs):
        defaults = dict(
            board_width=8, board_height=8, pieces=[],
            selected_cell=None, game_over=False,
            airborne_pos=None, scores={}, move_history=[],
        )
        defaults.update(kwargs)
        return GameSnapshot(**defaults)

    def test_winner_color_defaults_to_none(self):
        s = self._make_snapshot()
        self.assertIsNone(s.winner_color)

    def test_winner_color_round_trips(self):
        s = self._make_snapshot(game_over=True, winner_color=PieceColor.BLACK)
        self.assertEqual(s.winner_color, PieceColor.BLACK)

    def test_snapshot_game_over_false(self):
        s = self._make_snapshot(game_over=False)
        self.assertFalse(s.game_over)

    def test_snapshot_game_over_true(self):
        s = self._make_snapshot(game_over=True)
        self.assertTrue(s.game_over)

    def test_snapshot_selected_cell(self):
        pos = Position(3, 4)
        s = self._make_snapshot(selected_cell=pos)
        self.assertEqual(s.selected_cell, pos)

    def test_snapshot_scores_default_empty(self):
        s = self._make_snapshot()
        self.assertEqual(s.scores, {})

    def test_snapshot_move_history_default_empty(self):
        s = self._make_snapshot()
        self.assertEqual(s.move_history, [])

    def test_piece_snapshot_fields(self):
        ps = PieceSnapshot(
            id="p1", kind=PieceKind.ROOK, color=PieceColor.WHITE,
            cell=Position(0, 0), state=PieceState.IDLE,
            target_cell=None,
        )
        self.assertEqual(ps.kind, PieceKind.ROOK)
        self.assertEqual(ps.color, PieceColor.WHITE)


# ---------------------------------------------------------------------------
# game_stats_tracker — EliminationEvent branch (previously uncovered)
# ---------------------------------------------------------------------------

class TestGameStatsTrackerElimination(unittest.TestCase):

    def test_elimination_event_scores_attacker(self):
        """Air-capture: EliminationEvent gives score to the opposite color."""
        from kungfu_chess.ui.game_stats_tracker import GameStatsTracker
        from kungfu_chess.realtime.motion import EliminationEvent
        from kungfu_chess.model.piece import Piece

        tracker = GameStatsTracker(board_height=8, piece_scores={"Q": 9, "P": 1, "N": 3, "B": 3, "R": 5, "K": 0})
        black_queen = Piece("bq1", PieceColor.BLACK, PieceKind.QUEEN, Position(0, 0))
        event = EliminationEvent(piece=black_queen, current_pos=Position(0, 0))
        tracker.process([event], delta_ms=0)
        # Black piece eliminated → White gets the score
        self.assertEqual(tracker.scores[PieceColor.WHITE], 9)
        self.assertEqual(tracker.scores[PieceColor.BLACK], 0)

    def test_elimination_of_white_piece_scores_black(self):
        from kungfu_chess.ui.game_stats_tracker import GameStatsTracker
        from kungfu_chess.realtime.motion import EliminationEvent
        from kungfu_chess.model.piece import Piece

        tracker = GameStatsTracker(board_height=8, piece_scores={"Q": 9, "P": 1, "N": 3, "B": 3, "R": 5, "K": 0})
        white_rook = Piece("wr1", PieceColor.WHITE, PieceKind.ROOK, Position(0, 0))
        event = EliminationEvent(piece=white_rook, current_pos=Position(0, 0))
        tracker.process([event], delta_ms=0)
        self.assertEqual(tracker.scores[PieceColor.BLACK], 5)
        self.assertEqual(tracker.scores[PieceColor.WHITE], 0)


# ---------------------------------------------------------------------------
# hud_layer — game-over outcome text
# ---------------------------------------------------------------------------

class _FakeCanvas:
    """Records put_text calls; matches img.Img's put_text signature."""
    def __init__(self):
        self.texts: list[str] = []

    def put_text(self, txt, x, y, font_size, color=(255, 255, 255, 255), thickness=1):
        self.texts.append(txt)


class TestHudLayerGameOverOutcome(unittest.TestCase):
    """
    Regression coverage: after an opponent auto-resigns, the surviving
    player used to see a bare "GAME OVER" with no indication of who won.
    HudLayer must say "YOU WIN"/"YOU LOSE" whenever winner_color and the
    viewer's own color are both known, and fall back to "GAME OVER" only
    when the outcome isn't attributable (e.g. a natural king-capture end).
    """

    def _make_snapshot(self, **kwargs):
        defaults = dict(
            board_width=8, board_height=8, pieces=[],
            selected_cell=None, game_over=True,
            airborne_pos=None, scores={}, move_history=[],
        )
        defaults.update(kwargs)
        return GameSnapshot(**defaults)

    def _hud(self):
        from kungfu_chess.ui.draw.hud_layer import HudLayer
        return HudLayer(cell_size=100, offset_y=0, canvas_w=800, ui=None)

    def test_you_win_when_winner_matches_my_color(self):
        canvas = _FakeCanvas()
        snap = self._make_snapshot(winner_color=PieceColor.WHITE)
        self._hud().draw(canvas, snap, canvas_h=800, my_color=PieceColor.WHITE)
        self.assertIn("YOU WIN", canvas.texts)

    def test_you_lose_when_winner_is_the_opponent(self):
        canvas = _FakeCanvas()
        snap = self._make_snapshot(winner_color=PieceColor.BLACK)
        self._hud().draw(canvas, snap, canvas_h=800, my_color=PieceColor.WHITE)
        self.assertIn("YOU LOSE", canvas.texts)

    def test_generic_game_over_when_winner_unknown(self):
        """Natural king-capture ending: winner_color is None — no attribution to make up."""
        canvas = _FakeCanvas()
        snap = self._make_snapshot(winner_color=None)
        self._hud().draw(canvas, snap, canvas_h=800, my_color=PieceColor.WHITE)
        self.assertIn("GAME OVER", canvas.texts)
        self.assertNotIn("YOU WIN", canvas.texts)
        self.assertNotIn("YOU LOSE", canvas.texts)

    def test_generic_game_over_when_my_color_unknown(self):
        """Spectator (or color not yet known): can't say YOU WIN/LOSE either."""
        canvas = _FakeCanvas()
        snap = self._make_snapshot(winner_color=PieceColor.WHITE)
        self._hud().draw(canvas, snap, canvas_h=800, my_color=None)
        self.assertIn("GAME OVER", canvas.texts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
