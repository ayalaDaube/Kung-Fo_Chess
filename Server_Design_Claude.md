# Kung-Fo Chess — Server Design & Future-Proofing

This document has two parts, because your boss asked two genuinely different
kinds of questions:

- **Part A** answers the *cloud/infrastructure* questions — how the servers
  handle 100M registered users and 10M concurrent players.
- **Part B** answers the *code-quality and future-proofing* follow-up — will
  the game code survive binary board encoding and user-defined custom pieces
  without a rewrite, and is it clean by the usual "big stones" of clean code.

They're kept in one file per your request, but deliberately kept as separate,
clearly-labeled parts — they're answering different questions, about
different layers of the system, and reviewers will want to jump straight to
the one they're asking about.

Every claim below traces back to something already true of this codebase
(documented in `ARCHITECTURE.md`) — the point throughout is "here's what
already supports this, here's the one thing that doesn't, here's the plan for
that one thing" — not a generic textbook answer.

---
---

# PART A — Cloud/Server Design for Scale

## A.0 The numbers that drive every decision below

Work these out *first* — they're what separates a good answer from a guess,
and they're the numbers to lead with tomorrow.

| Quantity | Value | How it's derived |
|---|---|---|
| Registered users | 100,000,000 | given |
| Concurrent playing users | 10,000,000 | given |
| Concurrent **rooms** | ~5,000,000 | 2 players/room (spectators add a small multiplier on top) |
| Average game length | ~60s | midpoint of the given 30-90s range |
| **Room churn rate** | **~83,000 rooms/sec** | `5,000,000 rooms / 60s` -- rooms ending *and* being created, steady-state |
| Matchmaking throughput needed | ~166,000 users/sec | `2 x room churn rate` -- every finished game returns ~2 users to the matchmaking pool |
| Per-user input traffic | ~0.5 kbps | trivial (see A.3) |
| Naive per-user broadcast traffic (today's 20Hz full snapshot) | ~320 kbps/user | **not** trivial -- see A.3, the single biggest thing that must change |

The room-churn number is the one most people miss. It's tempting to design
only around "10M concurrent" as a static number, but a system where the
average session is 60 seconds is really a system doing **~83,000 room
create/destroy operations every second, forever** -- that throughput number,
not the concurrency number, is what stresses the matchmaking layer, the room
directory, and the database far more than raw concurrency does.

## A.1 Database -- 100M registered users

**SQLite is not suitable at this scale, but it's the *correct* choice at the
scale this project runs at today** (a handful of local dev connections). It's
worth saying explicitly in an interview: SQLite isn't "bad," it's scoped
wrong for 100M users. Specifically:

- It's a **single file** with a single-writer lock -- every write serializes,
  and only one process can even open it for writing at a time. This
  project's design of wrapping every `sqlite3` call in `asyncio.to_thread`
  (`AuthService`) is the *right* mitigation for "don't block the event loop,"
  but it does nothing about "only one host in the world can talk to this
  file."
- No built-in replication, sharding, or network access -- a distributed fleet
  of game/auth nodes across regions literally cannot share one SQLite file
  safely.
- At the write-rate this project implies -- ELO updates fire once per
  finished game, i.e. **~166,000 writes/sec at the churn rate above** -- a
  single SQLite file isn't in the same order of magnitude as what's needed
  even before distribution is considered.

**What to use instead:**

- **A horizontally-shardable relational store** for accounts + ELO: e.g.
  managed Postgres, sharded by `hash(user_id)` across many instances (via
  something like Citus/Vitess-style partitioning), or a NewSQL system
  (CockroachDB / Google Spanner / Amazon Aurora) that gives ACID transactions
  *and* horizontal scale + geo-replication out of the box, at the cost of
  more operational complexity and $$. Say "sharded Postgres" as the
  pragmatic answer and "Spanner/CockroachDB" as the "if I had the
  budget/team for it" answer -- naming the trade-off is more impressive than
  picking one dogmatically.
- **Why relational at all, and not just a KV/NoSQL store?** Because an ELO
  update is a paired read-modify-write across *two* users' ratings that must
  be atomic -- exactly the kind of thing SQL transactions are for. Pure
  key-value stores (DynamoDB, Cassandra) are a fine choice for the parts of
  this system that really are just key lookups (see the room/presence
  directory in A.2), but ELO integrity is worth keeping transactional.
- **A cache in front of it for the hot path**: Redis (clustered) for
  session/login lookups and hot ELO reads, so the 100M-row account table
  isn't hit on every single auth check. This mirrors the two-tier idea
  already in the codebase (`AuthService` + a repository abstraction) -- the
  repository's *implementation* changes (sharded Postgres client instead of
  a SQLite-backed one), but `AuthService`'s contract doesn't have to.
- **Read replicas** for anything off the write-critical path -- a
  leaderboard/rank query doesn't need to read the primary; it can read a
  replica without any risk to gameplay correctness.

## A.2 Horizontal scaling -- 10M concurrent users, "everyone can play with everyone"

**One server is nowhere close to enough**, but the *unit of scaling* matters:
it's not "one giant server," and it's also not "one container per game" --
it's **many multi-tenant "Game Node" processes, each hosting thousands of
concurrent rooms**, which is exactly what this codebase's current
architecture already does inside a single process (one `GameSession` +
`TickLoop` per room, as a cheap asyncio task). Scaling out means running
*many copies* of that process and adding a coordination layer on top -- not
redesigning the room/tick model itself.

### Proposed tiers ("the different Dockers")

```
                         +---------------------+
 Client (anywhere) --->  |   Edge / Gateway     |  (many, per-region)
                         |  - TLS + WS handshake|
                         |  - auth pass-through |
                         +----------+-----------+
                                    |
                    +---------------+-------------------+
                    v               v                   v
           +----------------+ +-----------+   +--------------------+
           |  Auth/Account   | | Matchmaking|   |  Room Directory     |
           |  service        | |  service   |   |  (Redis)            |
           |  -> sharded DB  | |  (stateless,|  |  room_id -> node    |
           |  + Redis cache  | |  ELO-bucket |  |  user_id -> node/room|
           +----------------+ |  queues in  |   +----------+----------+
                               |  Redis)     |              |
                               +------+------+              |
                                      | "create room on Node X"
                                      v
                            +-----------------------+
                            |   Game Node fleet       |<-- looked up by
                            |  (many containers, each |    Room Directory
                            |  hosting many concurrent|    for joins/reconnects
                            |  GameSession+TickLoop    |
                            |  tasks -- TODAY's        |
                            |  design, just replicated |
                            |  N times)                |
                            +-----------+-------------+
                                        | async, off the hot path
                                        v
                            +-----------------------+
                            | Activity log pipeline   |
                            | (Kafka-style broker ->  |
                            |  data lake), not local   |
                            |  JSON-lines files        |
                            +-----------------------+
```

### How do you know which players are on which server?

A **Room Directory** -- a Redis (clustered) key-value map, not a relational
table, because this is purely a lookup problem with extremely high write
churn (~83k creates/sec *and* ~83k deletes/sec, matching A.0):

- `room_id -> game_node_address` -- written once when a room is created,
  deleted when it ends. Any Gateway, on any "join room" request, looks up
  this map to find which node actually owns that room.
- `user_id -> (game_node_address, room_id)` -- this is what makes
  **reconnect** work across a distributed fleet: today's manual
  "relaunch, log in, choose Room, type the room id" flow still works
  unchanged -- the only new step is that the Gateway has to resolve *which
  node* owns that room_id before routing the join, instead of assuming
  "the one process I'm already running."

### How do you make "everyone can play with everyone"?

The **Matchmaking service is a separate, stateless tier from Game Nodes**,
because it has completely different scaling characteristics (CPU-light,
state-light, needs a shared queue) versus Game Nodes (CPU/memory-heavy,
hosts the actual real-time engines). It should not live inside a Game Node
process the way it does today -- at 10M concurrent users, matchmaking has to
see the *entire global queue*, not just the players who happen to have
connected to one node.

- Represent the queue as Redis **sorted sets bucketed by ELO range** (and by
  region -- see below), so a match-finding worker only has to scan a narrow
  slice, not the whole 10M-user queue.
- Widen the search over time exactly like this project's existing
  ELO-widening matchmaking config already does -- the same "widen the window
  if you can't find a match" idea just needs a second dimension added:
  **widen the geographic radius over time too**, so a player is first
  matched within-region (low latency) and only falls back to cross-region if
  the local queue is thin. This is a direct, natural extension of a
  mechanism that already exists in the code, not a new concept.
- Once two users are matched, the matchmaking worker picks a Game Node (e.g.
  least-loaded, or consistent hashing to spread load evenly) and asks it to
  create the room -- identical to what happens today, just crossing a network
  hop instead of an in-process function call.
- Both clients are told the winning Game Node's address directly and connect
  to it -- this reuses the *exact* connect-by-room-id model the client
  already has, just pointed at a specific node instead of "the only server."
  (The alternative -- a transparent proxy/sidecar that hides node addresses
  from clients entirely -- is more "correct" from a pure encapsulation
  standpoint, but adds a permanent proxy hop of latency to every single move
  in a *real-time* game where latency is the whole point. Direct-connect-to-
  node is the right trade-off here specifically because this game is
  latency-sensitive -- say so explicitly if asked.)

### How do you divide roles between servers?

Five distinct tiers, each scaled independently because each has a different
bottleneck:
1. **Edge/Gateway** -- I/O-bound, TLS termination, scales with connection count.
2. **Matchmaking** -- CPU-light/state-heavy, scales with match-throughput
   (~166k/sec), not with total concurrency.
3. **Game Nodes** -- CPU/memory-heavy, scales with concurrent-room count; the
   only tier that is a direct scale-out of code that already exists.
4. **Auth/Account** -- I/O-bound against the sharded DB, deliberately isolated
   from Game Nodes so a slow DB query never stalls a game tick.
5. **Room Directory + activity log pipeline** -- pure infrastructure (Redis,
   Kafka-equivalent), not application code.

## A.3 Network traffic -- "a step every two seconds"

This has two very different answers depending on whether you mean the
player's **input** to the server or the server's **broadcast** back out --
and the gap between them is the single most important thing to flag at this
scale.

### Client -> server (input): trivial, even in aggregate

A move/jump command on the wire today is a small JSON object -- call it
~125 bytes generously. At one every 2 seconds:

- **Per user**: 125 bytes / 2s = 62.5 B/s = ~0.5 kbps -- less than a single
  text message per second. Genuinely negligible for one connection.
- **Aggregate across 10M concurrent users**: 10,000,000 x 62.5 B/s =
  625 MB/s = **~5 Gbps** system-wide. That sounds big in one number, but it's
  spread across every Gateway node in every region -- a single Gateway
  handling, say, 50,000 connections only sees ~3 Mbps of this. **Per-node,
  it's still trivial; it only looks large when you add up the whole
  planet.** That distinction (per-user vs. per-node vs. global aggregate) is
  the actual point worth making here.

### Server -> client (broadcast): this is where the real cost is

Today's design broadcasts a **full snapshot 20 times/sec** (every 50ms)
**regardless of whether anything changed**. That model is fine at "a couple
of concurrent local games" -- it is **not viable** at 10M concurrent users:

- Estimate a game-state snapshot's wire size at ~2 KB (32 pieces x ~50-60
  bytes of JSON each, plus overhead) -- **this is an estimate; the real
  number should be measured** from the actual serializer before quoting this
  in the interview as fact.
- **Naive current model**: 2 KB x 20/s = 40 KB/s = ~320 kbps **per connected
  client**. Aggregate across 10M clients: **~400 GB/s (~3.2 Tbps)** -- larger
  than most CDNs' total capacity for a single application. Not a "maybe
  optimize later" problem, a hard blocker.
- **Fix -- broadcast on state change, not on a fixed clock.** Since pieces
  only actually move roughly every 2 seconds per the given assumption, an
  event-driven broadcast (only send when the state actually changed) drops
  this by roughly the same order of magnitude as the polling-vs-event-driven
  gap always does. Rough re-estimate at ~1 broadcast/sec per room, ~1 KB
  delta (send what changed, not the full board): 5,000,000 rooms x ~2 KB/s
  (both players) = **10 GB/s (~80 Gbps)** aggregate -- still a lot in
  absolute terms, but roughly **40x smaller** than the naive model, and
  squarely in the range of what large-scale multiplayer/streaming
  infrastructure already handles today.
- **Further lever, once the above is done**: swap JSON for a compact binary
  encoding (MessagePack/Protobuf/a hand-rolled bit-packed format) for another
  3-5x reduction. Worth explicitly noting this is **not worth doing today**
  -- JSON's human-readability is a genuine asset at current scale for
  debugging -- but it's exactly the kind of thing that stops being a
  premature optimization once every byte is real infrastructure cost. (This
  connects directly to Part B.1 below -- the same binary-encoding question
  shows up from a totally different angle there.)

## A.4 Game duration (30-90s) -> what it says about Docker roles

A ~60-second average session means the system is really doing **~83,000
room-lifecycle operations per second** (A.0) -- and that number, more than
raw concurrency, dictates how the "Docker" tier should be shaped:

- **Rooms must NOT be containers.** Spinning up a container per room
  (typical cold-start: hundreds of ms to seconds) is utterly incompatible
  with 83k creates/sec. Rooms have to stay what they already are in this
  codebase: a **cheap in-process asyncio task**, created and torn down in
  microseconds. This is the single strongest argument for *not* rewriting
  the room/session model -- it already has the right granularity for this
  churn rate; it just needs to run on more machines.
- **Game Node containers must be long-lived and multi-tenant** -- each one
  hosts many thousands of concurrent room-tasks internally, and horizontal
  scaling means running more *copies of that whole process*, not one
  process per room.
- **Matchmaking has to be fast, not just correct**, because a 60-second
  session means every matched pair of players comes back to the queue in
  about a minute -- the system is in a near-constant state of rematching.
  The existing widen-over-time config needs its timings tuned around "the
  queue refills this fast," not around "queues are mostly stable."
- **Room-Directory writes are on the hot path of every single game**, not an
  occasional operation -- another reason it has to be an in-memory store
  (Redis) rather than a relational table: 83k writes/sec plus 83k
  deletes/sec, sustained, forever.
- **Capacity planning is a throughput number, not a concurrency number.**
  "How many Game Nodes do I need" is answered by "rooms created per second
  per node," not "10M / rooms per node" -- a node that can comfortably hold
  5,000 *concurrent* rooms might still fall over if it can't *create/destroy*
  rooms fast enough to keep up with a 60-second average lifetime; both
  numbers need checking, and they're not the same number.

## A.5 What changes in this codebase vs. what stays the same

**Stays conceptually identical:** one `GameSession`/`TickLoop` per room as a
cheap async task; the config pattern (`_XXX_DEFAULTS` + frozen dataclass);
the event-bus/subscriber pattern for logging.

**Has to change:** the SQLite repository -> a sharded-Postgres-backed
implementation behind the same interface; matchmaking moves out of the game
process into its own stateless service backed by Redis; a new Room Directory
concept (doesn't exist at all today, because today there's only ever one
process); the broadcast trigger moves from fixed-interval to
state-change-driven (A.3) -- this is a real behavior change worth doing even
before any distributed-systems work, since it's valuable at current scale
too.

## A.6 Interview cheat-sheet -- the numbers to have ready

- 100M registered / 10M concurrent -> **~5M concurrent rooms**.
- 60s avg game -> **~83,000 room create/destroy operations per second**,
  system-wide. This is the number that surprises people -- lead with it.
- -> **~166,000 users/sec** flowing back through matchmaking.
- SQLite: wrong not because it's "bad," but because a single-writer file
  can't serve ~166k writes/sec from a distributed fleet.
- Input traffic: ~0.5 kbps/user, trivial even at ~5 Gbps aggregate globally.
- Naive 20Hz full-snapshot broadcast: **~3.2 Tbps aggregate -- not viable.**
  Event-driven broadcast: **~80 Gbps -- viable.** ~40x, from one change
  (broadcast on state change, not on a clock).
- Rooms stay cheap async tasks, never containers; Game Node containers are
  long-lived multi-tenant hosts of thousands of those tasks.

---
---

# PART B -- Code Quality & Future-Proofing

This part answers your boss's follow-up message directly -- is the *game
code itself* (not the servers) ready for binary board encoding and
user-defined custom pieces without a rewrite, and is it clean.

## B.1 "Board and pieces may become binary instead of textual" -- already supported

**Status: yes, with one small thing worth naming.**

The reason this is already safe: the code that reads the board's text format
is completely isolated from the code that plays the game. Its whole job is
turning text into `Board`/`Piece` objects -- and the rules engine, the game
engine, and the real-time motion system all work **only** with those
finished objects, never with raw text. This mirrors the same "snapshot is
the only read model" idea this project already uses on the *output* side --
it just needed to be pointed out that the same instinct already covers the
*input* side too.

**What this means in practice, if binary encoding actually happens:**
- Add a binary parser next to the text one, producing the exact same
  `Board`/`Piece` objects.
- Add a matching binary serializer if the *outgoing* wire format needs to
  change too (today's JSON serializer would get a binary sibling, living in
  the same networking layer, not in the engine).
- **Zero changes needed in the rules engine, the game engine, or the
  real-time motion system.** That's the whole point of the boundary already
  existing.

**The one thing worth naming, not fixing:** each piece kind's enum value
(`KING = "K"`, etc.) doubles today as "the text format." If binary encoding
wants a different code per piece (say, a 3-bit integer instead of a letter),
that mapping should be its own table inside the binary serializer/parser --
not a change to what the enum's value means, since other code likely depends
on it staying a readable letter for debugging/logging. Small, but worth
saying out loud so nobody "fixes" the enum itself later by mistake.

## B.2 "Users define their own pieces and movement rules" -- mostly already supported, one real gap

**Status: two of the three things needed already exist. One doesn't.**

### Already there, and worth being proud of

**a) The rule engine already accepts custom movement rules via injection** --
its constructor takes an optional mapping of piece-kind -> movement-rule
object, explicitly documented in its own docstring as "option to
replace/extend movement rules for a specific piece kind." This wasn't an
accident.

**b) The game engine already accepts a custom promotion policy via
injection** -- a swappable callback that runs whenever a piece arrives at the
board's far edge. Your boss's exact example -- *"a pawn that reaches the last
row reverses direction instead of turning into another piece"* -- is
**already fully possible today**, with no engine changes: pass a custom
policy that, instead of turning the piece into a queen, flips some direction
state on it (or swaps it to a differently-configured movement rule) instead.
This is a genuinely strong existing design -- say this to your boss directly,
it's a real point in your favor.

### The one real gap: piece kinds are a closed set

Piece kinds today are a fixed enum with exactly 6 members (King, Queen,
Rook, Bishop, Knight, Pawn). The movement-rule mapping above is keyed by
this same fixed set -- the *values* are already swappable, but the *keys* are
locked to these 6. A user could never register a genuinely new piece kind
("a Shlomi") by injecting a new movement rule, because there's no slot to
key it with, and creating one today means editing this enum directly in the
source -- exactly the kind of change the "don't rush to implement, but make
sure you can" request is trying to avoid needing later.

**How I'd explain handling this when it comes**, without building it now:
- Loosen the piece-kind type from a closed enum to an open identifier -- a
  plain validated string, or a small registry built from a per-game
  "ruleset" that lists which piece kinds exist and which movement rule each
  one uses. This is a config/data change, not a rewrite: the movement-rule
  mapping barely changes shape (only its key type loosens), and the board
  parser's kind-lookup table would be built from that same ruleset instead
  of the fixed enum's values.
- One existing field is a small preview of the same problem at a smaller
  scale -- a piece's starting row is tracked on the general piece object
  purely so one specific piece kind's rule (the pawn's double-step) can read
  it. When custom pieces arrive, piece-kind-specific state like this should
  live with the movement rule that needs it (or in a generic per-piece
  "custom state" bag), not as a named field on the shared piece model --
  worth keeping in mind as the pattern to follow for any new piece-specific
  state.

## B.3 Code smells -- self-audit against the "big stones"

**DRY (don't repeat yourself):** mostly good -- the diagonal-moving and
straight-line-moving piece rules share one common "sliding" helper rather
than duplicating it, and the queen's rule is built by combining the rook's
and bishop's rather than reimplementing either. **One known exception:** the
server-side and client-side activity loggers duplicate the same
redaction/JSON-line-writing logic in two places. Not urgent, but real
duplication -- worth a shared helper someday so a future fix to the
redaction logic doesn't have to be made twice and risk being forgotten in
one of them.

**SRP (single responsibility):** solid, and one of the stronger parts of
this codebase. The board parser only parses; the rule engine only decides
legality and never mutates anything; the game engine is the one place that
actually orchestrates a mutation. This separation is exactly why B.1 and B.2
above are as safe as they are -- SRP and "easy to extend later" are the same
thing in practice.

**No hardcoded constants in business logic:** consistently good via a
`defaults dict + frozen config dataclass` pattern used for every tunable
added throughout this project. One real violation was caught and fixed
earlier (an auto-resign timeout briefly defaulted to the wrong *value*
while still being config-driven, not hardcoded inline -- the *pattern* was
followed correctly, the *value* was just wrong).

**Encapsulation:** mostly good, with one honest flag. This project's own
architecture notes explicitly document the rule -- "no reaching into another
class's private data, add a public method instead" -- and name a specific
real example of it. That's not hypothetical: code *did* reach directly into
another class's private internals at one point during this project and had
to be fixed by adding a proper public method instead. It's fixed now, and
it's the kind of thing worth double-checking any time a new class needs
something from another one -- the instinct to reach for "the other object's
internal thing" is the exact smell your boss is describing.

## B.4 Testing

**No monkey-patching: genuinely clean, full stop.** Checked repeatedly
across the whole codebase -- there is no mocking/monkeypatching anywhere.
Every test uses real objects, real sockets, or injected fakes (fake network
classes, fake clocks via explicit time parameters, in-memory repositories)
-- exactly the dependency-injection approach your boss is asking for instead.
State this to your boss with full confidence; it's true and it's been
checked more than once.

**Git URL comment on the main file: not done yet -- needs a real fix.** The
server's entry-point file currently has a placeholder repository URL instead
of the real one. This has been flagged before and is still unresolved.
**Fix this before anyone reviews the code.**

**100% test coverage: genuinely can't be confirmed yet -- needs to be run.**
There are real, substantial unit tests in this project, but "there are real
tests" and "the coverage is 100%" are two different claims, and only the
first has been directly verified so far. Run this and look at the report
yourself before telling your boss "yes, 100%":
```bash
pip install coverage
coverage run -m pytest kungfu_chess/tests
coverage html      # writes htmlcov/index.html -- open it, uncovered lines are highlighted
coverage report -m
```

## B.5 Bottom line

Binary encoding: already handled by the existing boundary between
text-parsing and game logic, one small note to remember. Custom pieces: two
of the three needed hooks already exist and are genuinely well-designed; one
real gap (closed piece-kind set) with a clear, low-risk plan for later. Code
smells: solid overall, two specific known soft spots named honestly rather
than glossed over. Testing: monkey-patching is clean and provable; the git
URL comment and the actual coverage number are the two concrete to-dos left
before this goes to review.
