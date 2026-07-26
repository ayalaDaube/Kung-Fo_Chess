Kung-Fo Chess — Server Design & Future-Proofing (Executive Summary)
PART A — Cloud/Server Design for Scale
A.0 Core Metrics & Scale
Scale: 100M registered users, 10M concurrent players, resulting in ~5M concurrent rooms.

Churn Rate: With an average game length of 60s, the system handles ~83,000 room create/destroy operations per second.

Matchmaking Throughput: ~166,000 users/sec returning to the matchmaking pool.

A.1 Database Layer (100M Users)
SQLite limitation: Unsuitable for distributed scaling or high write concurrency (~166k writes/sec).

Target Architecture:

A horizontally-sharded relational store (e.g., sharded Postgres or NewSQL like CockroachDB) for accounts and atomic ELO transactions.

Redis cluster in front for session lookups, hot ELO reads, and matchmaking queues.

Read replicas for non-critical reads like leaderboards.

A.2 Horizontal Scaling & Architecture Tiers
Five Independent Tiers:

Edge/Gateway: TLS termination, connection handling.

Matchmaking Service: Stateless, ELO-bucketed Redis queues.

Game Nodes: Multi-tenant containers hosting thousands of concurrent room tasks.

Auth/Account Service: Isolated from game nodes via the sharded DB.

Room Directory & Activity Pipeline: Redis map (room_id -> node_address, user_id -> node/room) and Kafka-style logging.

Global Play: Direct connection from clients to resolved Game Node addresses to maintain real-time latency performance.

A.3 Network Traffic Optimization
Input Traffic: ~0.5 kbps per user (~5 Gbps global aggregate), distributed across regional gateways.

Broadcast Traffic: Replacing the naive 20Hz full-snapshot model (~3.2 Tbps aggregate) with an event-driven state-change broadcast reduces network overhead by ~40% (~80 Gbps aggregate).

A.4 Infrastructure Decisions
Rooms as Async Tasks: Rooms run as cheap in-process asyncio tasks rather than heavyweight containers to support 83k creations/sec.

Throughput Planning: Capacity depends on room lifecycle creation speed per node rather than static concurrency alone.

PART B — Code Quality & Future-Proofing
B.1 Binary Board Encoding
Status: Fully supported. Text parsing is completely decoupled from core game logic, which interacts solely with instantiated Board and Piece objects. Adding a binary parser requires zero changes to the rules or game engines.

B.2 Custom Pieces & Movement Rules
Status: Mostly supported via existing design patterns.

Rules engine and promotion policies accept custom injections (e.g., movement modifications or directional reversals instead of standard queen promotion).

The Gap: Piece kinds are currently a closed Enum. Future scaling requires opening piece kinds to validated strings or dynamic ruleset registries.

B.3 Code Smells & Principles
DRY & SRP: Strong separation of concerns (parsers parse, rules evaluate without mutating, engines orchestrate). Minor duplication exists in logging handlers.

Encapsulation & Constants: Enforced strict boundaries preventing direct access to private class attributes, paired with frozen config dataclasses.

B.4 Testing & Verification
No Monkey-Patching: Tests rely strictly on real objects, actual sockets, or injected fakes/clocks.

Action Items: Resolve the placeholder Git repository URL in the main entry file and verify test coverage reports via standard coverage execution tools before review.