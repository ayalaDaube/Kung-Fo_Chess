# Kung-Fo Chess

A real-time multiplayer chess variant — **there are no turns**. Every piece on the board
can move independently and simultaneously. Moves take real wall-clock time proportional
to distance, pieces enter a cooldown ("rest") after acting, and pieces can **jump**
(go briefly airborne and uncapturable, with an air-capture mechanic for anyone who tries
to land on them mid-jump).

The server is fully authoritative: the client never decides whether a move is legal, it
only proposes one and renders whatever the server confirms.

## Features

- Real-time concurrent movement — no "whose turn is it"
- Jump mechanic with air-capture
- ELO-based matchmaking, manual room creation/join-by-id, spectators
- Disconnect/reconnect handling with auto-resign
- SQLite-backed auth (bcrypt) and ELO tracking (PostgreSQL when running via Docker Compose)
- Structured JSON-lines activity logging on both client and server

## Tech stack

- Python 3.10+, stdlib `asyncio` for all concurrency
- `websockets` for networking, `bcrypt` for password hashing, stdlib `sqlite3` for
  persistence (no ORM, no external message queue); `psycopg2-binary` + `redis` when
  running via Docker Compose (PostgreSQL for users, Redis ELO cache)
- Client rendering via OpenCV (`cv2`), plus `screeninfo` and `numpy`
- `pytest` for tests — no mocks anywhere, real sockets/objects + injected fakes

## Installation

```bash
pip install -e .
```

`cv2`, `screeninfo`, and `numpy` are used by the client but aren't declared in
`pyproject.toml` — install them manually if missing:

```bash
pip install opencv-python screeninfo numpy
```

## Running

### Native (no Docker)

Start the server first, then one client per player:

```bash
python -m kungfu_chess.server.main
python -m kungfu_chess.app
```

Client and server tuning live in [config.json](config.json) and
[server.json](server.json), loaded via `config_loader.py` and `server/config.py`
respectively — never hardcode a tunable inline.

### Docker Compose (server + PostgreSQL + Redis)

The graphical client always runs natively on the host — only the server is
containerized.

1. Copy the environment template and fill in credentials:

   ```bash
   cp .env.example .env
   # edit .env — change POSTGRES_PASSWORD at minimum
   ```

2. Start the stack:

   ```bash
   docker compose up --build
   ```

   Docker Compose waits for Postgres and Redis to pass their healthchecks
   before starting the server.  The server's WebSocket port is published on
   the host at `localhost:8765` (or whatever `SERVER_PORT` is set to).

3. Point the native client at the containerized server.  In `config.json`
   set:

   ```json
   { "host": "localhost", "port": 8765 }
   ```

   Then run the client as usual:

   ```bash
   python -m kungfu_chess.app
   ```

4. To stop and remove containers (data volumes are preserved):

   ```bash
   docker compose down
   ```

   To also wipe the Postgres data volume:

   ```bash
   docker compose down -v
   ```

**Environment variables** (`DB_BACKEND`, `POSTGRES_*`, `REDIS_*`) are read
from `.env` by Docker Compose and injected into the server container.
`.env` is gitignored; `.env.example` is the checked-in template showing
every required variable name.  No credentials are hardcoded anywhere in
code or in `docker-compose.yml` itself.

## Testing

```bash
# Full suite
pytest kungfu_chess/tests

# A single test file
pytest kungfu_chess/tests/unit/test_game_engine.py -q

# A single test method
pytest kungfu_chess/tests/unit/test_game_engine.py::TestClassName::test_method_name -q
```

`kungfu_chess/tests/integration` runs the scripted board DSL scenarios under
`kungfu_chess/texttests/`, which test move/jump/rest legality without any networking.

## Project layout

```
Kung-Fo_Chess/
├── kungfu_chess/          # the installable package — all real code lives here
│   ├── model/                 # pure data: Position, Piece, Board, GameSnapshot
│   ├── rules/                 # move legality (RuleEngine + per-piece rules)
│   ├── realtime/               # RealTimeArbiter — concurrent motions, jump/air-capture, rests
│   ├── engine/                 # GameEngine — the sole read/write orchestrator
│   ├── ui/                     # cv2 rendering
│   ├── client/                 # networked GUI client (pregame, render loop, snapshot receiver)
│   ├── server/                 # authoritative backend (network, session, matchmaking, auth)
│   ├── texttests/               # scripted DSL local rule tests
│   └── tests/                   # unit (real-socket e2e) + integration (texttests runner)
├── assets/                # sprites, board image
├── config.json             # client tuning
├── server.json              # server tuning
└── kungfu_chess.db           # sqlite users db (created at runtime)
```

## Documentation

- **[CLAUDE.md](CLAUDE.md)** — quick index and day-to-day commands
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — full deep-dive: wire protocol, real-time engine
  mechanics, multiplayer session lifecycle, testing conventions, and known gaps. Read this
  before making non-trivial changes.
