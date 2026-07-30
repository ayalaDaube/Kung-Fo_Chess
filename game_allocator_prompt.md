Phase 10 — Game Allocator + Redis Room Directory (single-shard, but real).

Per Server_Design_Updated.md's own ordering, this is the next named stretch
goal after the two-gateway split (Phase 9) — not the full multi-shard fleet,
not gRPC/NATS, not Kubernetes. Today there is still exactly ONE Game Server
Shard (the ws-gateway process). This phase introduces the Allocator + Room
Directory seam correctly now, even with only one shard to choose from, so
adding real shards later is a data change, not a rewrite.

BEFORE STARTING: report every file you intend to touch and why. Do not touch
any file outside that list without disclosing it in your final report.

TASK 1 — RoomDirectory (Redis)
A small class, same pattern as RedisConnectionRegistry: writes/reads
room_id -> shard_address in Redis. SRP: it only stores and looks up this
mapping — it doesn't decide anything.

TASK 2 — GameAllocator
A class with one real decision method (e.g. allocate_shard(room_id) ->
shard_address). For now it always returns the single configured shard
address (from config, not hardcoded) — but write it as a genuine decision
point (a method call, injectable/overridable), not a bypassed no-op, so a
future multi-shard version is a swap of this method's internals only.

TASK 3 — Wire it in
Room creation calls GameAllocator, writes the result to RoomDirectory. Room
join looks the shard address up via RoomDirectory before connecting (today
this resolves to the same single ws-gateway address every time — that's
expected and fine, the point is the lookup path is real, not skipped).
No changes to RoomManager/GameSession/Matchmaker's own logic.

TASK 4 — Tests
Unit tests for RoomDirectory and GameAllocator (real Redis, skip cleanly if
unreachable, same style as test_redis_connection_registry.py). One test
explicitly asserting today's allocator always returns the single configured
shard — documenting that this is intentional, not a bug, until more shards
exist.

STANDING RULES — unchanged from every prior phase:
- No hardcoded constants; no unittest.mock.patch/monkeypatching anywhere.
- SRP: RoomDirectory only stores; GameAllocator only decides; neither
  touches game logic or connection handling.
- Don't touch model/, engine/, rules/, realtime/, rendering/, input/.
- Do NOT build a second real Game Server Shard, gRPC, NATS, or the
  Observability tier this phase — allocator + directory only.

DELIVERABLE: full file list (no omissions), confirm existing test suite
still passes unchanged, confirm the new tests actually fail if RoomDirectory
isn't consulted (i.e. prove the lookup path is real, not bypassed).
