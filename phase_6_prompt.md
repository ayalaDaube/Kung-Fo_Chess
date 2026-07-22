This is the final phase. Two parts: (A) verify the room/spectator system
already built during the pre-Phase-5 refactor fully satisfies the spec below,
and (B) build the one piece of Phase 6 that doesn't exist yet — structured
logging, on both server and client.

Do not touch model/, engine/, rules/, realtime/, rendering/, input/ — except
if part A's verification finds a genuine gap there, in which case stop and
report it rather than fixing it silently.

═══════════════════════════════════════════════════════════════════
PART A — Verify the existing room/spectator system against the spec
═══════════════════════════════════════════════════════════════════

ConnectionRouter + GameSession already implement room creation, join-by-id,
color assignment, and spectators from the pre-Phase-5 work. Before writing
anything new, confirm — with tests, not just reading the code — that all of
this actually holds:

1. create_room generates a room ID and the room is joinable by it.
2. First joiner (with a resolved username) = White, second joiner = Black.
3. Every joiner after the first two becomes a spectator: read-only, receives
   GameSnapshot broadcasts, but the server rejects any move/jump command from
   that connection. (owns_piece_at() already causes this rejection since a
   spectator owns no color — confirm this with an explicit test if one
   doesn't already exist, don't assume.)
4. A reconnecting player (existing PlayerRecord for that username) is
   correctly restored to their original color and is NOT misclassified as a
   spectator — this was fixed during the Phase 5 work; add a regression test
   for it here too if the existing one lives only in test_connection_router.py
   and isn't also exercised via the room-join path specifically.
5. Cancelling a room (CancelRoomCommand, or the auto-resign teardown path)
   correctly stops that room's TickLoop and removes it from room_ids() —
   already covered by Phase 5 tests; just confirm no regression.

If any of items 1-5 don't actually hold, fix them as a normal bug fix (same
rules as every prior phase: no hardcoding, no monkeypatching, SRP preserved,
don't touch the pure core). If they all hold, say so explicitly in your
summary and move to Part B — don't rebuild what already works.

═══════════════════════════════════════════════════════════════════
PART B — Structured logging (server + client), the actual new work
═══════════════════════════════════════════════════════════════════

Requirement: JSON-lines logging, on both server and client, covering:
  - every command received (by the server, from any client)
  - every event broadcast (to any client, from the server)
  - every auth attempt, success or failure — NEVER log a plaintext password,
    not even in a failure message

SERVER SIDE:

1. Add a new server/logging_/ package with an ActivityLogger class.
   - Constructor takes a log path (from config, see below) and writes one
     JSON object per line — no other format.
   - Each line should have at minimum: a timestamp, an event/command type,
     the game_id/room_id if applicable, and a payload — but NEVER a raw
     password field. If a payload dict might contain one (e.g. an auth
     command), the logger must strip/redact it before writing, not rely on
     callers to remember not to pass it.
   - This class only knows how to serialize and append a line to a file —
     it does not know about WebSockets, GameSession, or AuthService. Keep it
     a pure sink, consistent with the SRP pattern used everywhere else in
     this codebase (compare to how AuthService/db.py/GameStatsTracker are
     each scoped to exactly one job).

2. Wire ActivityLogger into ConnectionRouter as a subscriber to EventBus —
   this is what "every event broadcast" means: MOVE_ACCEPTED, MOVE_REJECTED,
   JUMP_ACCEPTED, JUMP_REJECTED, SNAPSHOT, PLAYER_JOINED, PLAYER_DISCONNECTED,
   PLAYER_RECONNECTED, GAME_ENDED — all of these already carry game_id in
   their payload from the Phase 5 work, so the logger can attribute every
   line to the correct room without new plumbing there.

3. "Every command received" is NOT currently published to the bus anywhere
   — parse_incoming_message and _dispatch handle commands directly, they
   don't publish a "command received" event. Add this: either (a) publish a
   new COMMAND_RECEIVED bus event from _dispatch right after a command is
   successfully parsed (before ownership/room checks), tagged with
   connection_id and command type, or (b) call the logger directly from
   _dispatch for this one case if introducing a new bus topic feels like
   overkill for a single call site — your call, but be consistent and
   explain which you chose and why in your summary.

4. "Every auth attempt, success or failure" — AuthService currently returns
   a result to ConnectionRouter._handle_auth with no bus event and no
   logging at all. Add logging for both login and register attempts, success
   and failure, from _handle_auth (or have AuthService itself accept an
   optional logger-shaped callback — your call on which class owns this,
   but justify it against SRP: does logging login attempts belong to
   ConnectionRouter's job of routing, or AuthService's job of authenticating?
   Pick one and don't split the same responsibility across both).
   CRITICAL: the log line must contain the username and the outcome
   (success/failure/reason like "duplicate username" or "invalid
   credentials") but never the password, under any circumstance — write a
   test that specifically asserts a failed login attempt's log line does not
   contain the submitted password string anywhere.

5. Config: add a LoggingConfig (log path, following the exact _AUTH_DEFAULTS
   / _REALTIME_DEFAULTS / _MATCHMAKING_DEFAULTS / _STATS_DEFAULTS pattern
   already established in server/config.py) — do not hardcode a log file
   path inline anywhere.

CLIENT SIDE:

6. Check kungfu_chess/config_loader.py — it already has a `client_log_path`
   field on GameConfig that may or may not be wired up yet. Verify: is
   anything actually writing to it today? If not, add a client-side logger
   (same JSON-lines format, same "no plaintext password" rule if the client
   ever handles a password — check ws_client.py / shell_login.py for this)
   that logs at minimum: every command the client sends, every message the
   client receives from the server. Reuse client_log_path from the existing
   config rather than adding a new config field, unless it's already
   unrelated to this purpose — check before assuming.

═══════════════════════════════════════════════════════════════════
CROSS-CUTTING SAFETY — final verification pass, not new work
═══════════════════════════════════════════════════════════════════

These should already all hold from earlier phases. Confirm each with a test
if one doesn't already clearly exist; report anything that doesn't hold as a
bug rather than assuming it's fine:

- Server is authoritative: every move/jump command is validated for shape
  (protocol.py) and ownership (owns_piece_at) before ever reaching
  GameEngine. No client-supplied data reaches the engine unvalidated.
- No blocking calls in the asyncio event loop: confirm every SQLite call in
  auth_service.py is still wrapped in asyncio.to_thread, including any new
  logging code you add — a synchronous file-write logger called from inside
  an async handler on every single move/broadcast could itself become a new
  blocking-call problem if the log file grows large or disk I/O is slow;
  wrap ActivityLogger's file writes in asyncio.to_thread too, consistent
  with the same reasoning already applied to SQLite.
- One GameSession = one isolated GameEngine/Board/RealTimeArbiter, no shared
  mutable state across rooms: should already hold from the original
  architecture; just don't introduce a shared mutable log buffer or shared
  state in ActivityLogger that couples rooms together — a single append-only
  file/handle shared across rooms is fine (it's genuinely stateless from the
  logger's own perspective), a shared in-memory dict keyed loosely by
  session would not be.

═══════════════════════════════════════════════════════════════════
STANDING RULES — same as every prior phase, still non-negotiable
═══════════════════════════════════════════════════════════════════

- No hardcoded constants anywhere — log paths, any tunable, all through
  config.py following its existing dict-of-defaults + dataclass pattern.
- No unittest.mock.patch, no monkeypatching, anywhere in tests. Use real
  objects, fake factories/timestamps, or real sockets for e2e tests, exactly
  like every existing test file in this codebase does.
- SRP preserved: ActivityLogger only serializes and writes; it does not
  decide what's loggable or reach into GameSession/AuthService internals.
  ConnectionRouter still only routes. GameSession still only orchestrates one
  game. Don't let logging concerns leak into classes that don't already have
  them.
- Encapsulation: no new code reaches into another class's private
  (_prefixed) attributes. If ActivityLogger needs something from GameSession
  or AuthService, add a public method or pass it in explicitly — don't peek.
- Target full test coverage on every new file and every changed method,
  including the "no plaintext password in logs" test called out above.
- Add/update the git-repo-URL comment at the top of server/main.py if it's
  still a placeholder — this has been flagged before and should be resolved
  before this is considered the final delivery.

DELIVERABLE:
- Part A's verification results, stated explicitly (what already held, what
  needed fixing).
- Part B's ActivityLogger (server + client), full wiring, full tests.
- A final summary listing every file changed/added, and confirmation that
  the full test suite passes with no monkeypatching anywhere in the project.
