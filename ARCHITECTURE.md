# Kung-Fo Chess — Architecture Guide

This is a deep-dive reference for this codebase, written so a future chat session (or a
human) can understand the whole system without re-reading every file. Start here before
touching code. `CLAUDE.md` at the repo root is the short pointer/index into this file.

## 1. What this project is

A real-time multiplayer chess variant ("Kung Fu Chess"): there are **no turns** — every
piece on the board can move independently and simultaneously. Moves take real wall-clock
time to complete (proportional to distance), pieces enter a "rest" cooldown after acting,
and pieces can **jump** (go briefly airborne/uncapturable, with an "air-capture" mechanic
for anyone who tries to land on them).

- **Client**: Python + OpenCV (`cv2`) GUI, single-threaded asyncio event loop.
- **Server**: Python asyncio WebSocket server. Fully authoritative — the client never
  decides whether a move is legal, only proposes one.
- Real multiplayer features: ELO-based matchmaking, manual room creation/join-by-id,
  spectators, disconnect/reconnect with auto-resign, SQLite-backed auth + ELO, structured
  JSON-lines activity logging on both sides.

## 2. Tech stack

- Python 3.10+, stdlib `asyncio` for all concurrency (no threads, no other async framework).
- `websockets` for networking, `bcrypt` for password hashing, stdlib `sqlite3` for
  persistence (no ORM).
- Client-only: `opencv-python` (`cv2`), `screeninfo`, `numpy` — **not declared in
  `pyproject.toml`** (only `websockets`/`bcrypt` are); install them manually.
- `unittest`/`pytest` for tests. No linter/type-checker is configured anywhere in the repo.
- In-process pub/sub only (`server/bus/event_bus.py`) — no external message queue.

## 3. Repo layout (top level)

```
Kung-Fo_Chess/
├── kungfu_chess/          # the installable package — all real code lives here
├── assets/                # sprites, board image
├── config.json            # client-side tuning -> config_loader.py (GameConfig)
├── server.json             # server-side tuning -> server/config.py (ServerConfig)
├── kungfu_chess.db          # sqlite users db (created at runtime)
├── client.log / server_activity.log   # runtime logs (created at runtime)
├── img.py                  # tiny Img/canvas wrapper (put_text, draw_on, show) used by ui/
├── preview.py              # ad hoc manual preview script
├── ARCHITECTURE.md          # this file
├── CLAUDE.md                # short pointer + index (read this first)
└── pyproject.toml
```

## 4. Package tree (`kungfu_chess/`)

```
kungfu_chess/
├── app.py                  # GUI client entry point: python -m kungfu_chess.app
├── config_loader.py         # client-side GameConfig, loaded from config.json
│
├── model/                  # pure data — no logic, no I/O, no rendering
│   ├── position.py            Position(row, col)
│   ├── piece.py                Piece, PieceColor, PieceKind, PieceState
│   ├── board.py                 Board — grid of pieces; no rule knowledge
│   └── game_state.py            GameSnapshot / PieceSnapshot / MoveRecord (THE read-model DTO)
│
├── rules/                  # move legality only — read-only w.r.t. Board
│   ├── piece_rules.py          PieceMovement subclass per piece kind
│   └── rule_engine.py          RuleEngine.validate_move()
│
├── realtime/                # the "kung fu" real-time motion system
│   ├── motion.py                Motion, ArrivalEvent, EliminationEvent, RestEvent, IdleEvent
│   └── real_time_arbiter.py     RealTimeArbiter — concurrent Motions, jump/air-capture, rests
│
├── engine/                  # the orchestrator — the ONLY sanctioned way to mutate/read game state
│   ├── game_engine.py           GameEngine: Board+RuleEngine+RealTimeArbiter, request_move/jump, snapshot()
│   └── snapshot_builder.py      build_snapshot() — Board+Arbiter (+stats) -> GameSnapshot
│
├── io/                      # board text (de)serialization, used by setup + tests
│   ├── board_parser.py          ASCII board DSL -> Board
│   ├── board_printer.py         Board -> ASCII (test assertions)
│   └── standard_setup.py        STANDARD_STARTING_POSITION text
│
├── input/                   # local UI selection state — client-side only, no rules knowledge
│   ├── board_mapper.py          pixel <-> cell
│   └── controller.py            click()/jump() -> ControllerResult (a *candidate* command only)
│
├── ui/                      # rendering (cv2/numpy) — client only
│   ├── renderer.py              composes the draw/ layers into one frame
│   ├── animator.py               sprite frame selection from motion_progress/state
│   ├── game_stats_tracker.py     scores + move_history derived from RealTimeEvents (used server-side!)
│   ├── draw/                     board_layer, piece_layer, overlay_layer, hud_layer, table_layer
│   └── assets/                    sprite path resolution + animation timing config
│
├── client/                  # networked GUI client
│   ├── pregame.py                login -> menu -> room/matchmaking flow (run_pregame is the entry point)
│   ├── render_loop.py             the async frame loop + outgoing command queue
│   ├── snapshot_receiver.py       parses incoming snapshot/error/disconnect messages
│   ├── activity_logger.py         ClientActivityLogger (JSON-lines, mirrors the server one)
│   ├── logger.py                   plain-text `logging` setup (separate from activity_logger!)
│   ├── shell_login.py              username-prompt validation only
│   ├── ws_client.py                 low-level connect-and-join primitive
│   └── main.py                      alternate CLI entry point, delegates to app.py
│
├── server/                   # authoritative multiplayer backend
│   ├── main.py                     process entry point: python -m kungfu_chess.server.main
│   ├── config.py                    ServerConfig — the config-pattern source of truth
│   ├── network/
│   │   ├── protocol.py               wire format + untrusted-input parsing (all CMD_*/MSG_* live here)
│   │   ├── serialization.py          GameSnapshot -> wire JSON
│   │   └── connection_router.py      THE hub — routes every message, owns all rooms
│   ├── session/
│   │   ├── game_session.py            one GameEngine + one GameStatsTracker per room
│   │   ├── tick_loop.py                per-room tick+broadcast loop
│   │   ├── disconnect_monitor.py       per-player auto-resign timer
│   │   └── player_identity.py          PlayerRecord, IdentityResolver
│   ├── matchmaking/
│   │   ├── matchmaker.py               pure synchronous ELO-window queue
│   │   └── matchmaking_loop.py         asyncio wrapper (widen-window/timeout ticks)
│   ├── auth/
│   │   ├── auth_service.py             register/login/ELO update, bcrypt via asyncio.to_thread
│   │   ├── db.py                        UserRepository protocol; Sqlite / InMemory impls
│   │   └── constants.py
│   ├── bus/
│   │   ├── event_bus.py                 in-process asyncio pub/sub
│   │   └── topics.py                     every topic string constant
│   └── logging_/
│       └── activity_logger.py            ActivityLogger (JSON-lines, redacts passwords)
│
├── texttests/                 # scripted-DSL local rule tests — no networking at all
│   ├── script_parser.py, script_runner.py
│
└── tests/
    ├── unit/                    ~50 files — mostly real-socket end-to-end tests, zero mocks
    └── integration/              runs the texttests/ DSL scripts
```

## 5. The big architectural ideas

### 5.1 Server is authoritative; client is a dumb renderer + input source
Every `MoveCommand`/`JumpCommand` is validated **twice** on the server before it ever
reaches `GameEngine`: shape (`protocol.py::parse_incoming_message`) then ownership
(`GameSession.owns_piece_at` / `ConnectionRouter._dispatch`). The client's `Controller`
never checks piece color — it just proposes a move; the server can reject it with
`MSG_ERROR`, which the client surfaces as a transient "Move rejected: ..." HUD banner
(`render_loop.py`'s `ERROR_DISPLAY_MS` + `SnapshotReceiver.pop_error()`).

### 5.2 Real-time, not turn-based
There is no "whose turn" concept anywhere. `RealTimeArbiter` tracks a **list** of
concurrent `Motion`s — both colors can be mid-move at the same time. Two mechanics layer
on top of "just move":
- **Rest**: after a MOVE resolves the piece enters `LONG_REST`; after a JUMP resolves,
  `SHORT_REST`. Both block further moves/jumps until the rest timer expires (`IdleEvent`).
- **Jump**: a piece can go airborne instead of moving. While airborne it can't be
  captured directly; an enemy MOVE landing on its cell captures the *mover* instead
  ("air-capture"). `RealTimeArbiter._airborne_pos` was flagged during a prior review as
  a single field that may not correctly track *multiple simultaneously-airborne pieces*
  of different colors — check `real_time_arbiter.py` and its tests before assuming this
  is fixed; see §8.

### 5.3 One GameSession = one isolated GameEngine/Board/RealTimeArbiter/GameStatsTracker
No shared mutable state across rooms. `ConnectionRouter` holds `dict[room_id, GameSession]`
plus one `TickLoop` per room. `ActivityLogger` is the one deliberately-shared object across
rooms — safe, because it's a stateless append-only file writer, not a room-keyed cache.

### 5.4 Wire protocol lives in exactly one place
Every message is `{"cmd": ...}` (client→server) or `{"type": ...}` (server→client) JSON.
All `CMD_*`/`MSG_*` string constants and every typed `Command` dataclass are defined in
`server/network/protocol.py`. `parse_incoming_message()` is the **only** place untrusted
JSON is parsed — never hand-roll `json.loads(raw)["cmd"]` elsewhere.

### 5.5 Snapshots are the only read model
`GameEngine.snapshot()` → `GameSnapshot` is the single DTO consumed by both the renderer
(`ui/renderer.py`) and the wire serializer (`server/network/serialization.py`). Never reach
into `GameEngine`/`Board` internals from rendering or networking code — go through
`snapshot()`.

### 5.6 Config pattern — copy this exactly for any new tunable
Both `config_loader.py` (client, reads `config.json`) and `server/config.py` (server,
reads `server.json`) use the identical shape:
```python
_XXX_DEFAULTS = {"some_setting": 42}

@dataclass(frozen=True)
class XxxConfig:
    some_setting: int

# inside load_*_config():
xxx_raw = {**_XXX_DEFAULTS, **data.get("xxx", {})}
```
Never hardcode a tunable inline in logic — add it to the relevant defaults dict +
dataclass. `server/config.py` currently has `AuthConfig`, `RealtimeConfig`,
`MatchmakingConfig`, `StatsConfig`, `LoggingConfig` — all following this pattern.

### 5.7 Dependency injection over mocking
Every I/O boundary is a constructor/function parameter with a real-world default:
`read`/`write`/`getpass_fn` in `pregame.py`, `engine_factory`/`identity_resolver` in
`GameSession`, `session_factory`/`room_id_generator` in `ConnectionRouter`,
`activity_logger` everywhere. Tests inject fakes (fake WebSocket classes, fake clocks via
explicit `now_ms` params, in-memory repos).
**Hard rule, not a style preference: nothing in this codebase uses `unittest.mock` /
`MagicMock` / monkeypatching, anywhere.** New tests must follow the same pattern (real
objects + real sockets + injected fakes), or they're inconsistent with everything else here.

### 5.8 Encapsulation
Classes don't reach into each other's `_private` attributes. Example: `GameSession` keeps
its `EventBus` private and exposes a public `subscribe(topic, handler)` method — that's
how `ConnectionRouter` wires in `ActivityLogger` without touching `session._bus` directly.
If you need something from another class, add a public method/property; don't peek.

### 5.9 Structured logging — two independent systems, don't conflate them
- **Plain Python `logging`** (stdlib): human-readable, level-based, for debugging.
  Server uses the root logger. Client uses the `kungfu_chess.client` logger with
  `propagate=False` (so DEBUG spam never reaches the console — see `client/logger.py`),
  written to `GameConfig.client_log_path`.
- **`ActivityLogger` / `ClientActivityLogger`**: JSON-lines, one object per line, for
  structured/machine-parseable history (every command sent/received, every auth attempt,
  every `EventBus` topic). Password-like keys (`password`/`passwd`/`pwd`) are redacted
  *unconditionally inside the logger* — callers never need to remember to strip them.
  Server writes to `ServerConfig.logging.log_path` (`server_activity.log` by default).
  Client writes to the **same** `client_log_path` as the plain-text logger above — that
  file currently mixes both line formats. This was a deliberate choice (the spec that
  introduced client-side activity logging explicitly said to reuse `client_log_path`
  rather than add a new config field) but flag it if you ever need to machine-parse
  `client.log` as pure JSON-lines.

## 6. Multiplayer session lifecycle

1. Client connects → `CMD_LOGIN`/`CMD_REGISTER` → `AuthService` (bcrypt hashing/checking
   run via `asyncio.to_thread`, never blocking the event loop) → `MSG_LOGGED_IN` with ELO.
2. Either:
   - `CMD_FIND_MATCH` → `Matchmaker` (ELO-windowed queue, widens over time via
     `MatchmakingLoop`, has its own `timeout_ms`) → `MSG_MATCH_FOUND` (room auto-created), or
   - "Room" menu: `CMD_CREATE_ROOM` (blank room id) or `CMD_JOIN_ROOM` (existing id).
3. First joiner (with a resolved username) becomes **WHITE**, second becomes **BLACK**
   (`GameSession.assign_color`). Every joiner after that is a **spectator** — owns no
   `PlayerRecord`/color, so `owns_piece_at()` naturally rejects any move/jump from them.
4. `TickLoop` advances the engine every `tick_interval_ms` and broadcasts `MSG_SNAPSHOT`
   to everyone currently in the room.
5. **Disconnect**: the other player gets `MSG_OPPONENT_DISCONNECTED` (with
   `auto_resign_ms`) and a `DisconnectMonitor` arms. If the *same username* rejoins the
   *same room_id* before it fires — this is manual on the client side, there is no
   automatic reconnect; the player has to relaunch, log in, choose "Room", and type in
   the room id they were shown when the game started — they're rebound to their original
   `PlayerRecord`/color and the monitor is cancelled. Otherwise auto-resign fires:
   `GAME_ENDED` publishes, ELO updates, and the room is torn down (`cancel_room`).
6. **Resignation outcome**: `GameSession.resign()` sets `winner_color` on the engine
   (only known for an explicit resignation, *not* a natural king-capture ending) so the
   client's HUD can say "YOU WIN"/"YOU LOSE" instead of a bare "GAME OVER". This requires
   the client to know its *own* `PieceColor` — for a matchmade game that comes from the
   `MSG_ASSIGNED` message the server sends just before `MSG_MATCH_FOUND`
   (`find_match_flow` in `pregame.py` captures it).

## 7. Testing conventions

- `pytest kungfu_chess/tests` — full suite (~488 tests as of the last review), **zero**
  `unittest.mock`/monkeypatching anywhere. Real `websockets.serve` + real
  `websockets.connect` for almost every server-facing test; a handful of lightweight fake
  `WebSocket`/`Controller`/`Renderer` classes for pure-logic tests (see
  `test_connection_router.py`'s `FakeWebSocket`, `test_render_loop.py`'s `_FakeRenderer`).
- `tests/unit/` — despite the name, most of these are genuine end-to-end tests over real
  sockets (e.g. `test_move_sync_e2e.py`, `test_disconnect_notify_e2e.py`,
  `test_matchmaking_e2e.py`).
- `tests/integration/test_text_scripts.py` — runs `texttests/` DSL scripts through the
  real `Controller`/`GameEngine`/`RealTimeArbiter` stack, no networking.
- New tests should follow the exact same pattern: inject fakes or use real sockets, never
  reach for `mock.patch`.

## 8. Known gaps / things to double-check before trusting this doc

This document is a snapshot from a review session, not a live source of truth. Before
relying on any of the following, check the actual code and recent git history:

- **Airborne tracking for simultaneous jumps** (§5.2): whether two different pieces can
  be airborne at once and both correctly protected/tracked was flagged as an open
  question during a prior review (`phase_fix_prompt.md` at the repo root, if it still
  exists, has the full write-up of "Bug 2a/2b"). Verify current behavior with
  `real_time_arbiter.py` and its tests rather than assuming either outcome.
- **No per-color board orientation**: both players currently see the same absolute board
  orientation (no flip for Black). Confirmed absent as of the last review, not a
  regression — just an unimplemented product decision.
- **Client-side JSON-lines activity log shares a file with the plain-text debug log**
  (§5.9) — by design, per the spec that introduced it, but worth re-confirming if you're
  about to build tooling that parses `client.log`.
- If there are `phase_*.md` / `fix_*.md` files at the repo root, they are point-in-time
  specs/bug reports for units of work that may already be complete — check `git log`
  and `git status` before treating them as outstanding work.
- Always prefer `git log`/`git status`/reading the actual file over trusting a stale
  paraphrase here if the two disagree.
