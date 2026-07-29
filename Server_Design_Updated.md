# Kung-Fo Chess — Server Design & Future-Proofing

## Executive Summary

- **Scale**: 100M registered users -> 10M concurrent players -> **~5M concurrent
  rooms**. Average game length ~60s means the system does **~83,000 room
  create/destroy operations per second, forever** — this throughput number,
  not raw concurrency, is what actually drives the design.
- **Database**:  Replace with **PostgreSQL** for permanent data (users,
  games, results, move history); horizontally sharded once volume actually
  requires it (see §1) — plain Postgres is the right starting point, sharding
  is the scale-up step, not day one.
- **Scaling model**: not "one giant server," not "one container per game" —
  six focused tiers, each scaled for its own bottleneck: **API Gateway**
  (login/rooms/history), **WebSocket Gateway** (live connections),
  **Matchmaker** (pairs players), **Game Allocator** (picks which shard
  hosts a room), **Game Server Shards** (run the authoritative GameEngine),
  and **Observability** (logs/metrics/health checks) — coordinated by a
  Redis **Room Directory** so any shard can be found by any gateway.
- **Network traffic**: player input is trivial (~0.5 kbps/user). The
  server's *broadcast* is the real cost — today's fixed-20Hz full-snapshot
  model is ~3.2 Tbps in aggregate at this scale (not viable); switching to
  broadcast-on-state-change brings that to ~80 Gbps (**~40x smaller**, i.e.
  a ~97.5% cut — not "40% less," a common misreading worth avoiding).
- **Game duration -> shard roles**: 60s average games mean rooms must stay
  cheap in-memory tasks, never containers — Game Server Shard *containers*
  are long-lived and host thousands of those tasks each.
- **The rule that never changes**: the client decides nothing about game
  legality, and neither does any Gateway. The GameEngine inside a Game
  Server Shard is the single source of truth — already true of this
  codebase today, and every tier added below is designed to keep it true at
  scale.
- **Implementation path**: build small and working before building
  complete. First priority is a working basic server (already true of this
  project); next is a small, real Docker Compose version proving the tier
  split actually works end-to-end — not a from-scratch build of all six
  tiers before anything runs.

---

# Cloud/Server Design for Scale

### The core numbers

| Quantity | Value |
|---|---|
| Registered users | 100,000,000 |
| Concurrent players | 10,000,000 |
| Concurrent rooms (2 players/room) | ~5,000,000 |
| Avg. game length | ~60s |
| **Room churn** (rooms/sec created+destroyed) | **~83,000/sec** |
| Matchmaking throughput needed | ~166,000 users/sec |

`5,000,000 rooms / 60s ≈ 83,000` — the number most people miss. It's not "10M
concurrent," it's "83,000 rooms opening and closing every second, forever."
That's what stresses matchmaking, the room directory, and the DB — not
concurrency by itself.

### 1. Database

- **PostgreSQL** for permanent data: users, games, results, move history.
  Relational, because an ELO update is an atomic read-modify-write across
  two users' ratings — exactly what SQL transactions are for. A single
  Postgres instance (in a container) is the right starting point for a
  working version — don't shard on day one.
- **Sharded** Postgres (or NewSQL like CockroachDB/Spanner) is the scale-up
  step, once write volume actually approaches the ~166,000 ELO-writes/sec
  this scale implies — a single instance, however well-tuned, cannot serve
  that alone.
- **Redis** for everything temporary and fast-changing: sessions, active
  rooms, reconnect state, the matchmaking queue. Also sits in front of
  Postgres as a cache for hot reads (login/session checks, ELO lookups) so
  the 100M-row table isn't hit on every request.
- **Read replicas** off Postgres for anything off the write path
  (leaderboards, stats).

### 2. Horizontal scaling — "everyone can play with everyone"

One server isn't enough, and one "Gateway" isn't the right shape either —
login/room-history and live gameplay connections have genuinely different
scaling needs (one is quick request/response, the other holds an open
connection and memory for the length of a match), so they're split into two
tiers from the start. Six tiers total, each scaled for its own bottleneck:

```
Client --> API Gateway (login, rooms, history — stateless, per-region, many)
Client --> WebSocket Gateway (live connections, state updates — per-region, many)
              |
     +--------+--------+------------------+------------------+
     v                 v                  v                  v
  Auth/Account    Matchmaker        Game Allocator      Room Directory (Redis)
  (Postgres      (pairs players,    (picks WHICH shard   room_id -> shard
   + Redis)       Redis queues       hosts a room —       user_id -> shard/room
                  by ELO+region)     for matched AND
                       |             direct room-code
                       |             joins alike)
                       +-------------------+
                                           v
                                 Game Server Shard fleet
                              (many containers, each
                               hosting 1000s of live
                               rooms as cheap tasks;
                               the authoritative
                               GameEngine lives here)
                                           |
                                           v
                                   Observability
                              (logs, metrics, health
                               checks feed autoscaling
                               + failure detection)
```

- **API Gateway** handles everything that isn't real-time: login, register,
  room history, account lookups. Stateless request/response — scale it by
  running more identical copies behind a load balancer, no special handling
  needed.
- **WebSocket Gateway** holds the live, long-lived connection to each
  playing client. Scales with connection count, not request rate — a
  fundamentally different load shape from the API Gateway, which is exactly
  why they're separate tiers rather than one.
- **Matchmaker** pairs players (Redis sorted sets, bucketed by ELO and
  region) — has to see the *whole global queue*, so it can't live inside a
  Game Server Shard the way it does in today's single-process design. Widen
  the ELO window over time (already how it works today) and widen the
  geographic radius over time too, so players match locally first and only
  go cross-region if the local queue is thin.
- **Game Allocator** is the piece that decides *which physical shard*
  actually hosts a room — split out from the Matchmaker on purpose, because
  "who should play whom" (skill/region) and "which machine has capacity
  right now" are different questions with different logic. Both paths go
  through it: a `Matchmaker` result asking for a new room, *and* a player
  typing in a room code directly — the Allocator (or the Room Directory it
  writes to) is what a WebSocket Gateway consults either way to find the
  right shard.
- **Room Directory** (Redis key-value map, written by the Allocator):
  `room_id -> shard address` and `user_id -> (shard, room_id)`. This is how
  any WebSocket Gateway, anywhere, finds which shard owns a given room —
  needed for joins and for reconnects.
- Once allocated, both clients connect **directly to the assigned shard's
  address** (via the WebSocket Gateway) — reusing the exact connect-by-room-id
  model already in the client, just pointed at a specific shard. (A
  transparent proxy hiding shard addresses would be "cleaner," but adds a
  latency hop to every move in a real-time game — direct connection is the
  right trade-off here.)
- **Observability** is its own tier, not an afterthought bolted onto the
  others: logs, metrics, health checks, and load testing. It's not
  optional plumbing — the failure-handling table in §5 depends entirely on
  health checks existing somewhere, so it earns a real place in the
  architecture rather than being mentioned only in passing.

### 3. Network traffic

- **Input** (client → server, one move ~every 2s): ~125 bytes / 2s ≈
  0.5 kbps/user. Aggregate across 10M users ≈ 5 Gbps globally — sounds big as
  one number, but spread across every regional Gateway it's a few Mbps per
  node. Trivial.
- **Broadcast** (server → client) is the real cost. Today's design sends a
  full snapshot every 50ms (20Hz) *regardless of whether anything changed*.
  At ~2KB/snapshot (estimate — measure the real value before quoting it),
  that's 40 KB/s per client, **~3.2 Tbps in aggregate at 10M clients — not
  viable.**
  **Fix: broadcast only when state actually changes**, not on a fixed clock.
  Re-estimated at ~1 update/sec/room, ~1KB delta: **~80 Gbps aggregate — a
  ~40x reduction (~97.5% less traffic), not "40% less."** A further 3-5x is
  available later by swapping JSON for a binary wire format — not worth
  doing yet, JSON's readability is still valuable at current scale.

### 4. Game duration (30-90s) → shard roles

- **Rooms are never containers** — 83,000 creates/sec is incompatible with
  container cold-start times. They stay cheap async tasks, as they are
  today.
- **Game Server Shard containers are long-lived, multi-tenant** — each
  hosts thousands of concurrent room-tasks; scaling out means more *copies
  of the whole process*, not one container per room.
- **Matchmaking must be fast**, since a 60s game means players cycle back
  into the queue roughly every minute — near-constant rematching.
- **Capacity planning is a throughput question** ("rooms created/sec per
  shard"), not just a concurrency one ("rooms held at once") — a shard can
  be fine on one measure and still fall over on the other.

### 5. Inter-server communication and failure handling

**Two different shapes of "talking between services," using different tools
for each on purpose:**
- **Ask-and-wait** — a service needs a direct answer right now ("Matchmaker
  asks the Game Allocator: give me a shard for this room"). Best served by a
  fast request/response protocol between services, e.g. **gRPC**.
- **Publish-and-forget** — a service just needs to announce a fact, and
  whoever cares can react ("a match was found," "a room ended"), with no
  reply expected. Best served by **NATS or Redis Pub/Sub**. This isn't a new
  idea for this project — it's the exact same pattern the in-process
  `EventBus` already uses today (`MOVE_ACCEPTED`, `GAME_ENDED`, and friends,
  published once and consumed by whichever subscribers care) — NATS/Redis
  Pub/Sub is that same pattern stretched across separate machines instead of
  staying inside one process.
- The Redis **Room Directory** itself is a third, simpler pattern again —
  not a conversation at all, just a shared fact ("room #4471 → shard #17")
  written once and read by whoever needs it, no request/response or
  publish/subscribe machinery required.

**What happens when each tier fails, and whether there's a backup:**

| Tier | If it dies | Backup / recovery |
|---|---|---|
| API Gateway | No consequence — stateless, holds no game data | Client retries through any other API Gateway; several always exist |
| WebSocket Gateway | No consequence — routes connections, holds no game state itself | Client reconnects through any other WebSocket Gateway |
| Matchmaker | No consequence — the queue lives in Redis, not in the worker's own memory | Any other matchmaker worker picks up the same queue instantly |
| Game Allocator | No consequence — decisions are based on shard health data in Redis/Observability, not private memory | Any other allocator instance can make the same decision |
| Redis (Room Directory / queues) | Real risk — many tiers depend on it | Run as a small replicated cluster (e.g. Sentinel/Cluster) — a standby takes over automatically, never run as a single instance |
| PostgreSQL (account DB) | Real risk — this holds permanent, must-not-lose data | Replicated (primary + standby, sharded once at scale); standby is promoted automatically on failure |
| **Game Server Shard** | **The one real, honest exception** — see below | **None**, by deliberate design |

**Why a shard crash is different, and why that's an acceptable design, not
a shortcut:** a Game Server Shard holds every in-progress game's live state
(exact piece positions, mid-motion) only in its own memory, for speed. If it
crashes, that in-memory state is genuinely gone — there is no live copy of
it anywhere else. Both players' connections drop at once. The standard,
honest answer for a real-time game like this: **that specific match is
voided** — both clients are told the match was interrupted and return to
matchmaking, and since neither player actually quit, it should not count as
a loss or affect ELO. Making every mid-move game state survive a crash would
mean constantly replicating it elsewhere, which slows down every single
move — not worth paying for a ~60-second casual match. This system stays
resilient by making failures *cheap to recover from* (start a new match)
rather than *impossible to have* — that's the honest trade-off, and it's
worth saying out loud rather than claiming full redundancy everywhere.

**What actually notices a failure and reacts:** every container is
continuously health-checked (a quick "are you still alive?" every few
seconds) by the **Observability** tier; anything that stops responding is
automatically replaced and routed around. This is a standard feature of
whatever tool manages the container fleet (Kubernetes/K3s for a managed,
scalable deployment; Docker Compose for the small local version described
below) — not something built by hand for this project.

---

# Implementation Path

**Small and working beats large and unfinished.** In order:

1. **A working basic server** — this project already has one (single
   process, in-memory rooms, real WebSocket handling, real auth). If that
   weren't true yet, it would come before any of the above.
2. **A small, real Docker Compose version** proving the tier split actually
   runs, not just describes something on paper — the existing server/client
   containerized alongside real Postgres and Redis containers is the
   concrete next step, with further tier-splitting (a separate WebSocket
   Gateway container, a separate Game Allocator) as a stretch goal once that
   baseline runs end-to-end.
3. **Kubernetes/K3s** is the managed, autoscaling version of step 2's same
   containers, for when "run this on many machines automatically" actually
   matters — not a prerequisite for demonstrating the design.
