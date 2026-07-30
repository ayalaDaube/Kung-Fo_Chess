Phase 9 — Split ApiGateway and WsGateway into separate processes, sharing
state through Redis instead of shared Python objects in one process. This is
the point where Redis stops "just running alongside" and becomes load-bearing
for something real: cross-process connection/session lookup.

Still NOT in scope: Matchmaker-as-a-service, Game Allocator, gRPC, NATS,
Kubernetes, sharding. Those come later, per Server_Design_Updated.md's own
"small and working beats large and unfinished" ordering. This phase is the
two-gateway split becoming physically real, nothing more.

BEFORE STARTING: report every existing file you intend to touch and why, and
do not touch any file outside that list without calling it out explicitly in
your final report — including test files. This is a hard requirement this
round specifically, since the last two phases each shipped at least one
undisclosed file/behavior change.

TASK 1 — Redis-backed ConnectionRegistry
ConnectionRegistry currently lives as one shared in-memory object passed into
both gateways' constructors. Give it the same treatment AuthService already
has for storage: define/confirm a ConnectionRegistry protocol (same public
methods it has today), keep the existing in-memory implementation for tests
and single-process use, and add a RedisConnectionRegistry implementing the
same interface, backed by real Redis (connection_id -> room_id, room_id ->
shard/process identity for later, username -> connection_id for reconnect
lookups). No changes to RoomManager, GameSession, or either gateway's own
logic — they should keep calling the same registry methods they call today,
now potentially satisfied by Redis instead of a dict.

TASK 2 — Two real entry points
Add server_api_main.py and server_ws_main.py (or equivalent — your call on
naming, but they must be genuinely separate runnable entry points, not two
functions in one file). Each constructs only what it needs:
  - server_api_main.py: ApiGateway + AuthService + RedisConnectionRegistry.
    No GameSession/RoomManager/TickLoop/Matchmaker — ApiGateway has never
    needed these.
  - server_ws_main.py: WsGateway + RoomManager + Matchmaker +
    RedisConnectionRegistry + an auth_dispatch callable that reaches
    AuthService the same way it does today (still direct, in-process, since
    auth dispatch already flows through a callable — don't turn this into a
    network call yet unless it already effectively is one via shared state).
  Keep server/main.py only if it's still useful as a "run both in one
  process" option for local dev/tests — don't delete the single-process path,
  just add the two-process path alongside it.

TASK 3 — docker-compose.yml
Split the single "server" service into two: api-gateway and ws-gateway, both
pointed at the same Postgres and Redis containers already defined. Confirm
both can start and connect to Redis/Postgres independently.

TASK 4 — Tests
- RedisConnectionRegistry unit tests, same style as test_postgres_repository.py:
  real Redis if reachable, cleanly skipped with a clear message if not — no
  fake-Redis stand-in presented as a Redis test.
- One integration test proving the actual point of this phase: a connection
  registered via one ConnectionRegistry instance (simulating ApiGateway's
  process) is visible to a second, separate ConnectionRegistry instance
  (simulating WsGateway's process) — both backed by the same real Redis.
  This is the test that proves cross-process sharing actually works, not
  just that each class works in isolation.

STANDING RULES — unchanged from every prior phase:
- No hardcoded constants (Redis host/port/etc. via config, matching the
  existing _AUTH_DEFAULTS-style pattern).
- No unittest.mock.patch / monkeypatching anywhere.
- SRP: RedisConnectionRegistry only implements the registry interface — it
  doesn't know about gateways, rooms, or auth. Neither gateway's own logic
  changes because of where the registry data lives.
- Don't touch model/, engine/, rules/, realtime/, rendering/, input/.
- Do not build Matchmaker-as-a-service, Game Allocator, gRPC, or NATS this
  phase.

DELIVERABLE: report every file changed (full list, no omissions), confirm
the full existing test suite still passes unchanged, and confirm the new
cross-process integration test actually fails if run against two separate
in-memory registries (proving it's really testing Redis sharing, not
something trivially true regardless of backend).
