Please review and fix the following issues in the kungfu_chess project.

Apply these constraints to every change:
- Clean code: clear naming, no dead code, minimal diffs scoped to the bug.
- Single Responsibility Principle: don't let GameSession absorb stats-tracking
  logic itself — it should own/delegate to GameStatsTracker, not reimplement it.
- No hardcoded values: piece scores, config, etc. must come from config/
  constructor parameters with sensible defaults, not literals buried in logic.
- No monkeypatching: fix the real call sites and class wiring directly,
  don't patch behavior in from the outside at runtime or in tests.

For all issues, report back specifically what changed and why per file — do
not silently fix nearby unrelated code.

---

## ISSUE 1 — Score table and move history never update (server-side wiring gap)

GameStatsTracker (kungfu_chess/ui/game_stats_tracker.py) is fully implemented
and covered by unit tests, but is never actually constructed or used by the
running server. As a result every GameSnapshot ever broadcast has empty
scores and move_history, regardless of player count — this is why it "looks
fine" with 1 player (no captures happening) and visibly broken with 2 (real
captures happening, table never reflects them).

Fix:

1. kungfu_chess/engine/game_engine.py: add a public read-only `board`
   property returning self._board.

2. Add piece-score defaults the right way — do NOT invent a new
   DEFAULT_PIECE_SCORES constant inline in game_session.py, and do NOT import
   from config_loader.py (that's client-side rendering config — UiConfig,
   pygame color tuples, window settings — and must stay decoupled from
   server/). Instead:
   - Add a new `_STATS_DEFAULTS` dict and `StatsConfig` dataclass in
     server/config.py, following the exact same pattern already used for
     `_AUTH_DEFAULTS`/`AuthConfig`, `_REALTIME_DEFAULTS`/`RealtimeConfig`,
     `_MATCHMAKING_DEFAULTS`/`MatchmakingConfig` — merged from server.json
     with sensible defaults (standard chess values), loaded via
     `load_server_config()` like everything else.
   - GameSession's constructor should accept a `piece_scores: dict`
     parameter with no inline default — sourced from
     `ServerConfig.stats.piece_scores` by whatever constructs GameSession,
     mirroring how AuthConfig/RealtimeConfig are already threaded through.

3. kungfu_chess/server/session/game_session.py:
   - Import GameStatsTracker.
   - Construct
     `self._stats = GameStatsTracker(board_height=self._engine.board.height, piece_scores=piece_scores)`
     in `__init__`.
   - In `tick(self, ms)`: capture the events from `self._engine.wait(ms)`
     into a variable, call `self._stats.process(events, ms)`, then return
     the events (currently discarded).
   - In `build_snapshot()` and `handle_command()`: pass `stats=self._stats`
     into every `self._engine.snapshot(...)` call.

4. Add a test that runs a real capture through GameSession.tick() and asserts
   build_snapshot().scores reflects it, and move_history is non-empty — to
   catch regressions of this exact wiring gap.

Do not touch the client — it already displays whatever scores/move_history
arrive in the snapshot correctly.

---

## ISSUE 2 — Airborne highlight bugs in RealTimeArbiter (two bugs, not one)

In kungfu_chess/realtime/real_time_arbiter.py, `_airborne_pos` is a single
`Optional[Position]` field meant to track "the piece currently airborne from
a jump." There are two separate, confirmed bugs here — fix both:

**Bug 2a — an unrelated move wrongly clears the airborne marker.**
`_resolve_move()` unconditionally sets `self._airborne_pos = None` whenever
ANY regular MOVE motion resolves, even if a completely different piece is
currently airborne from an unrelated jump. This line is redundant: the two
legitimate places that should clear `_airborne_pos` already exist and are
already correct — when the airborne piece itself lands (the JUMP branch in
`_resolve_arrival`) and when it's captured mid-air (`_resolve_air_capture`).
Fix: remove the unconditional clear from `_resolve_move` — it should not
touch `_airborne_pos` at all.

**Bug 2b — nothing stops a second piece from jumping while another is still
airborne (reachable today, not a hypothetical).**
`GameEngine.request_jump` only checks `has_active_motion(piece)` — whether
THIS piece is busy — never whether some OTHER piece is currently airborne.
Since `_airborne_pos` is a single field, if piece A jumps and then piece B
(a different piece) jumps while A is still in the air, `start_jump` silently
overwrites `_airborne_pos` with B's position. From that moment, piece A —
still genuinely airborne — loses both its air-capture protection
(`_resolve_air_capture` only ever checks the current single value) and its
UI highlight, while still logically airborne.

Before fixing 2b, add a test that starts two different pieces jumping with
overlapping timing and observe the current (broken) behavior. Then decide,
based on the game's actual rules:
  (a) if only one piece should ever be airborne system-wide at a time, add a
      guard in `request_jump` that rejects a second jump attempt while
      `_airborne_pos` is already set (return an appropriate MoveResult
      reason), in addition to the 2a fix above, or
  (b) if simultaneous jumps by different pieces should be legal,
      `_airborne_pos` needs to become a per-piece or per-position
      collection, and `_resolve_air_capture` / `_get_airborne_piece_color`
      must check against all airborne positions, not just one.

Add tests for both bugs:
  - 2a: two pieces where one jumps and a different piece's ordinary move
    resolves in the same tick — assert the jumping piece's airborne state
    survives until its own jump duration ends.
  - 2b: two pieces jump with overlapping timing — assert both pieces'
    airborne state and air-capture eligibility are tracked correctly
    (per whichever design decision (a) or (b) above is chosen).

---

## ISSUE 3 — No per-player board orientation (design gap, not a regression)

The rendered board uses one fixed orientation for both White and Black
players — there is no flip based on the client's assigned color. This is
consistent between 1-player and 2-player use (so it isn't a new regression),
but flag it for a product decision: should the Black player's client mirror
the board the way standard chess UIs do? If so, this needs to be threaded
through kungfu_chess/ui/renderer.py and the board/piece draw layers using
the `my_color` value already available in the render loop (added recently
for the win/lose message) — no new plumbing required to access it.

No code change requested for this issue yet — just confirm the plumbing
point above and await a product decision before implementing.
