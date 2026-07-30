Phase 7 — prove the future architecture direction runs, without building it
all yet. Do NOT implement the six-tier split, gRPC, NATS, Kubernetes, or
sharding from Server_Design_Updated.md — that document is a roadmap for
100M-user scale, not a spec for this step. This phase is deliberately small.

TASK 1 — PostgresUserRepository
Add a new class implementing the existing UserRepository interface
(server/auth/db.py), backed by PostgreSQL instead of SQLite — same public
methods (get_user_by_username, create_user, update_elo), same parameterized-
query discipline, same "no raw SQL/cursor exposed to callers" rule. Do NOT
change AuthService at all — if this requires changing AuthService, stop and
report why, since the whole point is proving the UserRepository abstraction
already supports this swap. Add a config value for the Postgres connection
string following the existing _AUTH_DEFAULTS pattern in server/config.py.
Keep SqliteUserRepository as-is — this is an addition, not a replacement.

TASK 2 — docker-compose.yml
A minimal compose file with: the existing server (server/main.py), a
Postgres container, and a Redis container (Redis isn't used by any code yet
— it's fine for it to just run alongside; the goal here is proving the
pieces start up together, not wiring Redis into anything). Server should be
configurable via environment variables to point at the Postgres container
instead of the local SQLite file.

TASK 3 — tests
Unit tests for PostgresUserRepository following the existing no-monkeypatch
style (real Postgres if available in a test container, or a clearly-marked
integration test that's skipped if no DB is reachable — don't fake Postgres
behavior with an in-memory stand-in and call it a Postgres test).

STANDING RULES — unchanged from every prior phase:
- No hardcoded constants — connection strings, ports, etc. all via config.
- No unittest.mock.patch / monkeypatching anywhere.
- SRP preserved: AuthService still knows nothing about which repository
  implementation it's using.
- Don't touch model/, engine/, rules/, realtime/, rendering/, input/.

Report back: files changed, and confirm AuthService required zero changes.
