# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read this first

**Before doing anything else in this repo — before exploring files, before answering
architecture questions, before fixing a bug — read `ARCHITECTURE.md` at the repo root.**
It's a full deep-dive on how this codebase is built: every module's responsibility, the
wire protocol, the real-time engine mechanics, the multiplayer session lifecycle, testing
conventions, and known gaps. This file is just a short index and the commands you'll
actually run day to day.

## Commands

```
# Full test suite (no mocks anywhere — real sockets/objects + injected fakes)
pytest kungfu_chess/tests

# A single test file
pytest kungfu_chess/tests/unit/test_game_engine.py -q

# A single test method
pytest kungfu_chess/tests/unit/test_game_engine.py::TestClassName::test_method_name -q

# Start the server
python -m kungfu_chess.server.main

# Start the GUI client (server must already be running)
python -m kungfu_chess.app

# Install (editable)
pip install -e .
# cv2/screeninfo/numpy are used by the client but are NOT declared in pyproject.toml —
# install them manually if missing: pip install opencv-python screeninfo numpy
```

No linter or type-checker is configured anywhere in this repo.

## Directory tree

```
Kung-Fo_Chess/
├── ARCHITECTURE.md          # full architecture deep-dive — read it before this file's summary
├── config.json               # client tuning -> config_loader.py (GameConfig)
├── server.json                # server tuning -> server/config.py (ServerConfig)
├── kungfu_chess.db             # sqlite users db (created at runtime)
├── img.py                      # tiny Img/canvas wrapper used by ui/
└── kungfu_chess/                # the installable package — all real code lives here
    ├── app.py                      # GUI client entry point: python -m kungfu_chess.app
    ├── config_loader.py             # client-side GameConfig
    │
    ├── model/                       # pure data: Position, Piece, Board, GameSnapshot (the DTO)
    ├── rules/                       # move legality only (RuleEngine + per-piece PieceMovement)
    ├── realtime/                    # RealTimeArbiter — concurrent Motions, jump/air-capture, rests
    ├── engine/                      # GameEngine — the sole orchestrator; snapshot() is the read model
    ├── io/                          # ASCII board DSL parser/printer, standard starting position
    ├── input/                       # BoardMapper + Controller (local UI selection, client-only)
    ├── ui/                          # cv2 rendering: renderer.py + draw/ layers + GameStatsTracker
    │
    ├── client/                      # networked GUI client
    │   ├── pregame.py                   # login -> menu -> room/matchmaking (run_pregame entry point)
    │   ├── render_loop.py                # async frame loop + outgoing command queue
    │   ├── snapshot_receiver.py          # parses incoming snapshot/error/disconnect messages
    │   └── activity_logger.py             # ClientActivityLogger (JSON-lines)
    │
    ├── server/                      # authoritative multiplayer backend
    │   ├── main.py                      # process entry point
    │   ├── config.py                     # ServerConfig — the config-pattern source of truth
    │   ├── network/                       # protocol.py (wire format), connection_router.py (THE hub)
    │   ├── session/                       # game_session.py, tick_loop.py, disconnect_monitor.py
    │   ├── matchmaking/                   # matchmaker.py, matchmaking_loop.py
    │   ├── auth/                           # auth_service.py, db.py (bcrypt + sqlite)
    │   ├── bus/                            # event_bus.py — in-process pub/sub
    │   └── logging_/                       # activity_logger.py (JSON-lines, redacts passwords)
    │
    ├── texttests/                    # scripted DSL local rule tests, no networking
    └── tests/
        ├── unit/                         # ~50 files, mostly real-socket e2e tests, zero mocks
        └── integration/                    # runs the texttests/ DSL scripts
```

## Architecture — condensed (see `ARCHITECTURE.md` §5 for full detail)

- **Client (cv2 GUI) ↔ Server (asyncio `websockets`)** over a JSON wire protocol defined
  in exactly one place: `server/network/protocol.py`.
- **Server is fully authoritative.** Every move/jump is validated for shape, then
  ownership, before it ever reaches `GameEngine`. The client's `Controller` never checks
  piece color itself.
- **Real-time, not turn-based.** `RealTimeArbiter` tracks a *list* of concurrent `Motion`s
  (MOVE/JUMP) with rest-state cooldowns after each. `GameEngine` is the sole read/write
  orchestrator — `GameEngine.snapshot()` is the only sanctioned read model, consumed by
  both the renderer and the wire serializer.
- **One `GameSession` per room** = one isolated `GameEngine` + `GameStatsTracker`, no
  shared mutable state across rooms. `ConnectionRouter` owns all rooms, routing, auth,
  matchmaking, and disconnect/reconnect/auto-resign.
- **Config pattern** (copy exactly for new tunables): `_XXX_DEFAULTS` dict + frozen
  dataclass + `{**_XXX_DEFAULTS, **data.get("xxx", {})}` inside `load_*_config()`.
  Mirrored in `config_loader.py` (client) and `server/config.py` (server). Never hardcode
  a tunable inline.
- **Two independent logging systems** — don't conflate them: plain Python `logging`
  (human-readable debug) vs. `ActivityLogger`/`ClientActivityLogger` (JSON-lines,
  password-redacted, structured activity history).
- **No `unittest.mock`/`MagicMock`/monkeypatching anywhere in this codebase — this is a
  hard rule, not a style preference.** Every test uses real objects/sockets plus injected
  fakes (fake WebSocket classes, fake factories, explicit timestamps). New tests must
  follow the same pattern.
- **No reaching into another class's `_private` attributes.** Add a public method/property
  instead (e.g. `GameSession.subscribe()` instead of touching `session._bus` directly).

Full module-by-module breakdown, the multiplayer session lifecycle, testing conventions,
and known open gaps: **`ARCHITECTURE.md`**.
