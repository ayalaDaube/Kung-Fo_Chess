Phase 8 — split ConnectionRouter into two gateways: API Gateway (stateless
request/response) and WebSocket Gateway (live connections). Still one
process, one machine — no Redis Room Directory, no Game Allocator, no gRPC/
NATS yet. Those come later, once there's more than one instance of either
gateway to coordinate between. This phase is just the logical split.

FIRST — before any new work, explain the EloCache/Redis addition from Task 2.
That wasn't requested; Redis was only supposed to run alongside, unused. Report:
what EloCache does, whether AuthService now depends on Redis being reachable
to function (it shouldn't — Postgres/SQLite must remain fully sufficient on
their own), and whether this can be made an optional cache-aside layer that
degrades to hitting the repository directly if Redis is down. Don't remove
it without asking, but explain it and fix the dependency if it's not optional.

THEN — the split:

TASK 1 — ApiGateway: everything stateless request/response.
Pull login, register, and room-history-style requests (anything that
doesn't hold a live connection open) out of ConnectionRouter into a new
ApiGateway class. It talks to AuthService the same way ConnectionRouter does
today — no new logic, just relocated wiring.

TASK 2 — WsGateway: everything that's a live connection.
Rename/refactor what's left of ConnectionRouter (room create/join, moves,
matchmaking, disconnect/reconnect, all the per-room state) into WsGateway.
This is the class that owns GameSession/EventBus/TickLoop wiring — unchanged
in behavior, just no longer doing auth/login directly itself.

TASK 3 — shared wiring.
Both gateways need to reach the same AuthService/session state — for now
that's plain shared objects passed into both constructors (still one
process), not a network call between them. Structure the handoff so a future
phase (multiple gateway instances, needing the Redis Room Directory from
Server_Design_Updated.md) is a swap of that one wiring point, not another
rewrite of either gateway's internals.

TASK 4 — main.py
Update wiring to construct both gateways. Confirm nothing in the pure core
or in GameSession/TickLoop/Matchmaker needed to change — this should be a
routing-layer split only.

TASK 5 — tests
Split/update tests to match: ApiGateway tests for auth flows, WsGateway
tests for everything currently in test_connection_router.py. No behavior
change, so existing test assertions should mostly just move files.

STANDING RULES — unchanged from every prior phase:
- No hardcoded constants, no unittest.mock.patch/monkeypatching anywhere.
- SRP: ApiGateway only does stateless request/response; WsGateway only does
  live-connection/room/game routing. Neither reaches into the other's
  private state.
- Don't touch model/, engine/, rules/, realtime/, rendering/, input/.
- Do NOT build the Matchmaker-as-a-service, Game Allocator, Redis Room
  Directory, gRPC, or NATS pieces from Server_Design_Updated.md — this
  phase is the gateway split only.

Report back: the EloCache explanation/fix, files changed, and confirm the
full test suite still passes with the same behavior as before the split.
