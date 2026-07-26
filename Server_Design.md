# Kung-Fo Chess — Server Design & Future-Proofing

## Executive Summary

- **Scale**: 100M registered users -> 10M concurrent players -> **~5M concurrent
  rooms**. Average game length ~60s means the system does **~83,000 room
  create/destroy operations per second, forever** — this throughput number,
  not raw concurrency, is what actually drives the design.
- **Database**: SQLite (today's choice) is right for local dev, wrong at this
  scale — one file, one writer, can't serve the ~166,000 ELO writes/sec this
  scale implies. Replace with a horizontally-sharded relational store
  (sharded Postgres, or CockroachDB/Spanner) + a Redis cache in front for hot
  reads.
- **Scaling model**: not "one giant server," not "one container per game" —
  many copies of a multi-tenant **Game Node** (exactly today's
  room/session design, replicated), fronted by a Gateway tier, matched by a
  separate stateless Matchmaking tier, coordinated by a Redis **Room
  Directory** so any node can find any room.
- **Network traffic**: player input is trivial (~0.5 kbps/user). The
  server's *broadcast* is the real cost — today's fixed-20Hz full-snapshot
  model is ~3.2 Tbps in aggregate at this scale (not viable); switching to
  broadcast-on-state-change brings that to ~80 Gbps (**~40x smaller**, i.e.
  a ~97.5% cut — not "40% less," a common misreading worth avoiding).
- **Game duration -> Docker roles**: 60s average games mean rooms must stay
  cheap in-memory tasks, never containers — Game Node *containers* are
  long-lived and host thousands of those tasks each.
- **Future-proofing**: binary board encoding is already safe (text-parsing is
  isolated from game logic). Custom user-defined pieces are *mostly* already
  supported (movement rules and promotion behavior are both swappable via
  injection today) — the one real gap is that piece kinds are a closed enum.
- **Code quality**: DRY/SRP/config-driven-constants are solid. Encapsulation
  is solid *now*, after a real violation was caught and fixed earlier in this
  project — worth knowing it happened, not just claiming it never did.

---

# Part A — Cloud/Server Design for Scale

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

SQLite is a single file with a single-writer lock — no replication, no
sharding, no network access. Fine for local dev; can't come close to serving
~166,000 ELO writes/sec from a distributed fleet. Replace with:
- A **sharded relational store** (sharded Postgres, or NewSQL like
  CockroachDB/Spanner) for accounts + ELO — relational because an ELO update
  is an atomic read-modify-write across two users' ratings, which is exactly
  what SQL transactions are for.
- **Redis** in front for hot reads (login/session checks, ELO lookups) so
  the 100M-row table isn't hit on every request.
- **Read replicas** for anything off the write path (leaderboards, stats).

### 2. Horizontal scaling — "everyone can play with everyone"

One server isn't enough. The scaling *unit* is a multi-tenant **Game Node**
— exactly today's single-process design (one session + one lightweight task
per room), just replicated across many machines. Five tiers, each scaled for
its own bottleneck:

```
Client --> Gateway (per-region, many)
              |
     +--------+--------+-----------------+
     v                 v                 v
  Auth/Account    Matchmaking       Room Directory (Redis)
  (sharded DB    (stateless,        room_id -> node
   + Redis)       Redis queues       user_id -> node/room
                  by ELO+region)
                       |
                       v
                 Game Node fleet
              (many containers, each
               hosting 1000s of live
               rooms as cheap tasks)
                       |
                       v
              Activity log pipeline
              (streamed out, not local files)
```

- **Room Directory** (Redis key-value map): `room_id -> node address` and
  `user_id -> (node, room_id)`. This is how any Gateway, anywhere, finds
  which node owns a given room — needed for joins and for reconnects.
- **Matchmaking** is its own stateless tier (Redis sorted sets, bucketed by
  ELO and region) — it has to see the *whole global queue*, so it can't live
  inside a Game Node the way it does today. Widen the ELO window over time
  (already how it works) and widen the geographic radius over time too, so
  players match locally first and only go cross-region if the local queue is
  thin.
- Once matched, both clients connect **directly to the assigned Game Node's
  address** — reusing the exact connect-by-room-id model already in the
  client, just pointed at a specific node. (A transparent proxy hiding node
  addresses would be "cleaner," but adds a latency hop to every move in a
  real-time game — direct connection is the right trade-off here.)

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

### 4. Game duration (30-90s) → Docker roles

- **Rooms are never containers** — 83,000 creates/sec is incompatible with
  container cold-start times. They stay cheap async tasks, as they are
  today.
- **Game Node containers are long-lived, multi-tenant** — each hosts
  thousands of concurrent room-tasks; scaling out means more *copies of the
  whole process*, not one container per room.
- **Matchmaking must be fast**, since a 60s game means players cycle back
  into the queue roughly every minute — near-constant rematching.
- **Capacity planning is a throughput question** ("rooms created/sec per
  node"), not just a concurrency one ("rooms held at once") — a node can be
  fine on one measure and still fall over on the other.

### 5. Inter-server communication and failure handling

**Two different kinds of "talking," using different tools on purpose.**
Player ↔ game traffic stays exactly what it is today — a WebSocket
connection held open for the length of the match. Server ↔ server traffic is
a different shape: short, one-off questions ("start a room for these two
players," "where does room #4471 live"), best served by a fast
request/response protocol between services (e.g. gRPC) for the "ask and get
an answer now" cases, and by the Redis Room Directory itself for the "just
publish this fact for everyone to see" cases — no back-and-forth needed to
write "room #4471 → node #17" somewhere everyone can read it.

**What happens when each tier fails, and whether there's a backup:**

| Tier | If it dies | Backup / recovery |
|---|---|---|
| Gateway | No consequence — it holds no game data, just routes connections | Client reconnects through any other Gateway; several always exist |
| Matchmaking worker | No consequence — the queue lives in Redis, not in the worker's own memory | Any other matchmaking worker picks up the same queue instantly |
| Redis (Room Directory / queues) | Real risk — many tiers depend on it | Run as a small replicated cluster (e.g. Sentinel/Cluster) — a standby takes over automatically, never run as a single instance |
| Account database | Real risk — this holds permanent, must-not-lose data | Sharded **and** replicated (primary + standby per shard); standby is promoted automatically on failure |
| **Game Node** | **The one real, honest exception** — see below | **None**, by deliberate design |

**Why a Game Node crash is different, and why that's an acceptable design,
not a shortcut:** a Game Node holds every in-progress game's live state
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
seconds); anything that stops responding is automatically replaced and
routed around. This is a standard feature of whatever tool manages the
container fleet (e.g. Kubernetes) — not something built by hand for this
project.

---

