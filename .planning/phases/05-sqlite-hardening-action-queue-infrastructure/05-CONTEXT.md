# Phase 5: sqlite Hardening + Action Queue Infrastructure - Context

**Gathered:** 2026-07-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Two pieces of **proven cross-process infrastructure** that every write-heavy
dashboard module (Phases 6–9) will ride on:

1. **A generic `action_queue`** — the first **app→bot (forward)** channel. A
   Manager's panel click enqueues a typed action (`kind` + JSON payload) that the
   bot dispatches, with each action's status (pending / complete / failed) visible
   **inline in the panel** (INFRA-01). It is the write-side mirror of Phase 4's
   bot→app `discord_names` cache.
2. **Hardening the shared sqlite for concurrent writers** — `busy_timeout` +
   retry/backoff so concurrent panel-writes and bot-writes never raise
   "database is locked", **proven under an automated concurrent-load test** before
   any module ships on top (INFRA-02).

**Scope anchor:** This phase BUILDS and PROVES the infrastructure only. It ships
**no real module action** — no gallery-approve / reviews / meeting-republish
business logic (those are Phases 6–9). The queue's genericity and the DB hardening
are the deliverable; a minimal/test action kind and the load test are what "prove"
it. Reminders (Phase 6) deliberately **bypass** the queue (pure DB CRUD) per
ARCHITECTURE.md — this phase does not change that.

</domain>

<decisions>
## Implementation Decisions

### Action lifecycle & panel feedback (INFRA-01)
- **D-01: Inline status on the clicked item.** Each module renders the action's
  status from its queue row **on the item itself** — the row/button flips
  `Working…` → `✓ <done>` / `✗ Failed`. Not a remote feed. (The Phase-3
  `activity_log` Overview feed is separate and MAY still receive a durable log line
  per action, but the primary, load-bearing feedback is inline — see D-11.)
- **D-02: Failed actions surface a short reason + a Retry button.** A failed row
  shows a concise reason (e.g. "Discord: missing permissions") and a **Retry**
  control that **re-enqueues** the action, so a Manager self-recovers without shell
  access (fits the "no shell workarounds" goal). Re-enqueue interacts with
  idempotency — see D-08.
- **D-03: Completed/failed rows bounded by keep-last-N, purge-on-write.** Exact
  `activity_log` idiom (`INSERT` then `DELETE … WHERE id NOT IN (SELECT id … ORDER
  BY id DESC LIMIT N)`). Rolling recent history, self-limiting, no cron/sweep.

### Dispatch latency & refresh (INFRA-01 responsiveness)
- **D-04: Near-instant dispatch (~1–2s).** The bot claims/dispatches on a **tight
  `tasks.loop`** (~1–2s), NOT the ~45s heartbeat cadence — a click must feel like a
  real button. Trivial cost at one-guild volume.
- **D-05: The pending item auto-refreshes (no reload).** While an action is
  pending, the panel **short-polls its status** (Alpine — already shipped) and flips
  the item to `✓`/`✗` on its own. Implies an **app-side per-action status-read
  endpoint**. Websockets remain out of scope (polling is sufficient).

### Failure & stuck-action handling (robustness)
- **D-06: Auto-retry with backoff, then fail.** On a transient dispatch error
  (network blip, Discord 5xx) the bot retries with backoff (small bounded attempt
  count) before marking the action failed; the manual Retry (D-02) remains for
  genuine failures.
- **D-07: Bot-offline is a distinct state, detected via `bot_heartbeat`.** When the
  bot is down (heartbeat stale), a queued action shows **"bot offline — will run on
  reconnect"** instead of an endless spinner. The queue is **durable**: the action
  stays pending and dispatches when the bot returns. No lost clicks.
- **D-08: At-least-once delivery + per-module idempotency.** The bot
  claims → dispatches → marks complete; a crash mid-flight may re-run the action on
  recovery (a stale `claimed` row is retried, aligning with D-07's durable queue).
  **Therefore every module that rides the queue (Phases 6–9) MUST make its own
  dispatch idempotent.**
  **INVARIANT (binding on Phases 6–9): the queue must never cause a double-publish —
  idempotency is the module's responsibility** (the Phase-7 publish-race / 🟢-marker
  guard already owns this for gallery/reviews). The queue never silently drops an
  action.

### Queue shape, concurrency & the "proven" bar (INFRA-01 / INFRA-02)
- **D-09: One shared, generic `action_queue` table.** `kind` (e.g.
  `gallery_publish`, `meeting_republish`) + `payload_json` + status / error /
  requested_by / timestamps. All modules enqueue into the same table; the bot
  dispatches **by kind**. Matches the milestone-research blueprint
  (`core/action_queue.py`: `enqueue(kind, payload)→id` / `claim_next()` /
  `complete(id, result)`). One table to harden and prove. Per-module queue tables
  explicitly rejected (duplicates the dispatch/retry/status machinery).
- **D-10: Serialized dispatch (one at a time).** The bot processes the queue
  **oldest-first** (`ORDER BY id`), one action per tick — predictable ordering, no
  intra-bot write contention, trivially correct at this volume. Concurrent/parallel
  dispatch rejected.
- **D-12: Go/no-go gate = an automated concurrent-load test.** A test spins up a
  simulated **bot write-loop + panel write burst** against the shared DB and asserts
  **zero unhandled "database is locked"** escapes, committed to the suite as the
  gate before any module builds on the infra. This IS the load test PITFALLS.md
  Pitfall 3 recommends.

### Claude's Discretion
- **D-11: Retry/backoff wrapper scope (delegated to research/planning).**
  `busy_timeout` goes into `core/db.py::_get_conn()` **globally** (locked — one
  line, protects every write path; it's the single choke point). Whether the
  explicit retry/backoff wrapper wraps **all** existing write paths (`save_post`,
  reminders, store, heartbeat…) or **only** the new high-contention `action_queue`
  paths is left to research — PITFALLS.md guidance (retry needed for high-frequency
  paths; `busy_timeout` alone may suffice for rare ones) is the deciding input.
  **Floor:** the phase goal ("hardened before any write-heavy module ships") means
  at minimum `busy_timeout` global + retry on the two-way `action_queue` paths.
- Exact `action_queue` schema / column names; the `claimed`/`complete` state names
  and the stale-`claimed` recovery mechanism (implementing D-08); the precise poll
  interval within the "~1–2s / feels immediate" envelope; backoff attempt count and
  delays; the keep-last-N value (D-03); and the concurrent-load-test harness design
  (D-12) — all deferred to researcher/planner, constrained by the decisions above.
- Whether a durable `activity_log` line is also written per action (in addition to
  inline status) — optional per module (D-01).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **INFRA-01** (panel→bot actions travel through a
  queue table the bot dispatches, action status visible in the panel) and
  **INFRA-02** (`busy_timeout` + retry hardening before the first write-heavy
  module). Out-of-Scope table: no real-time websockets (polling is sufficient); no
  new IPC.
- `.planning/ROADMAP.md` — Phase 5 goal + the two success criteria (queued actions
  with visible pending/complete/failed status; concurrent panel/bot writes without
  "database is locked", proven under test). Phases 6–9 are the consumers.

### Milestone research (directly blueprints this phase — MUST read)
- `.planning/research/ARCHITECTURE.md` — the `action_queue` design:
  `core/action_queue.py` **pure** module (`enqueue(kind, payload)→id` /
  `claim_next()` / `complete(id, result)`), the `action_queue` table columns
  (`id, kind, payload_json, status, requested_by, requested_at, claimed_at…`), the
  bot-side `ActionQueueCog` / `action_queue_worker.py` fast `tasks.loop`, and the
  statement that `action_queue` is "the one genuinely new cross-process contract
  this milestone adds." Note: reminders (Phase 6) deliberately bypass the queue.
- `.planning/research/PITFALLS.md` — **Pitfall 3** (sqlite writer/writer
  contention): WAL alone does NOT fix it; explicit `busy_timeout` (5000–10000ms) +
  retry/backoff wrapper + short transactions. Its recommended load test (burst of
  panel writes concurrent with the bot's periodic writes, zero unhandled
  "database is locked") **is the D-12 proven bar**; the retry-scope guidance
  (retry required for high-frequency paths, `busy_timeout` may suffice for rare
  ones) informs **D-11**.
- `.planning/research/SUMMARY.md` — milestone technique summary: `action_queue`
  sqlite table + short-poll cog; `require_tier(...)` generalization of the existing
  dependency chain (enqueue routes must be manager-gated).

### Prior phase context (patterns this rides on)
- `.planning/phases/04-settings-migration-name-resolution/04-CONTEXT.md` — the
  reverse-direction (bot→app) `discord_names` cache; establishes the
  shared-sqlite-only channel discipline that `action_queue`'s forward direction
  mirrors.
- `.planning/phases/03-dashboard-shell-tiered-access/03-CONTEXT.md` —
  `bot_heartbeat` (reused by D-07 offline detection), `activity_log` (D-03
  keep-last-N idiom + optional per-action log line), `jinxxy_sync_status`
  single-row upsert pattern, and the `require_manager`/tier system (enqueue routes
  must be manager-gated).

### Prior design / spec
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — v1
  settings-panel invariants (validate-then-write, no-secrets, fail-closed gate) the
  dashboard preserves; context for the shared-sqlite DB idiom.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`core/db.py::_get_conn()`** ([core/db.py:8-17](core/db.py#L8-L17)) — the single
  connection factory every write flows through. WAL is already on (line 16); there
  is **no `busy_timeout` and no retry** today. INFRA-02's `busy_timeout` PRAGMA
  lands here (D-11).
- **`core/db.py` activity_log helpers** (`init_activity_log` / `log_activity` /
  `get_recent_activity`) — `log_activity`'s purge-on-write (`keep_last=500`) is the
  EXACT template for D-03's action-row pruning; the Overview feed is the optional
  durable log surface (D-01/D-11).
- **`core/db.py` `bot_heartbeat`** (`init_heartbeat` / `set_heartbeat` /
  `get_heartbeat`) — the `last_beat_utc` freshness timestamp is reused **app-side**
  by D-07 to detect bot-offline.
- **`core/db.py` single-row + upsert idioms** (`gallery_state` INSERT OR REPLACE,
  `presence`/`view_counts` ON CONFLICT, `jinxxy_sync_status`) — templates for the
  new `init_action_queue` + enqueue/claim/complete helpers.
- **`core/db.py::init_discord_names` / `replace_discord_names`** (Phase 4) — the
  most recent example of a bot↔app table added via the same idiom; `action_queue`
  is its forward-direction sibling.
- **App side:** Alpine (`app/static/alpine.min.js`, already shipped) powers the D-05
  auto-refresh polling; the `require_manager`/tier dependency gates enqueue routes.

### Established Patterns
- **Shared sqlite (`DB_PATH`, WAL) is the ONLY bot↔app channel — no IPC/HTTP.**
  `action_queue` MUST use it (locked project decision). It is the **forward
  (app→bot)** direction; `discord_names` was the reverse.
- **DB idiom:** fresh-connection-per-call; `init_*()` called from the owning cog's
  `__init__` (dual-process defensive init so the app never 500s on a missing
  table); parameterized SQL only; explicit column allowlists. New `action_queue`
  code follows this.
- **Every panel-initiated Discord write routes through the bot via the queue — no
  bot credentials in the FastAPI app** (locked). The app only enqueues + reads
  status; the bot holds the Discord side.
- POST-only mutations, manager-gated, bilingual (ES/EN) user-facing copy.

### Integration Points
- **New:** `core/action_queue.py` (pure `enqueue` / `claim_next` / `complete`) +
  `core/db.py::init_action_queue` + a bot-side `ActionQueueCog` fast `tasks.loop`
  (~1–2s) that claims → dispatches → completes.
- **New:** `busy_timeout` PRAGMA in `_get_conn()`; a retry/backoff helper wrapping
  (at least) the queue write paths (D-11).
- **App side:** manager-gated enqueue route(s) + a per-action status-read endpoint
  the pending item short-polls (D-05).
- This phase ships the infra **plus a proof** (a test/minimal action kind and/or the
  concurrent-load test); real module actions arrive in Phases 6–9.

</code_context>

<specifics>
## Specific Ideas

- **"bot offline — will run on reconnect"** — the D-07 pending-while-offline state
  (bilingual, house ES/EN style), visually distinct from a genuine failure.
- **Inline item states:** `Working…` → `✓ <done>` / `✗ Failed · <reason>` + Retry
  (D-01/D-02).

</specifics>

<deferred>
## Deferred Ideas

- **Real per-module action logic** (gallery approve/remove, reviews approve/remove,
  Jinxxy manual sync, meeting re-publish) — Phases 6–9 build ON this queue; Phase 5
  only proves the infra. Reminders (Phase 6) deliberately bypass the queue (pure DB
  CRUD) per ARCHITECTURE.md.
- **Concurrent (parallel) queue dispatch** — rejected in favor of serialized (D-10);
  revisit only if volume ever demands it (it won't at one-guild scale).

</deferred>

---

*Phase: 5-sqlite Hardening + Action Queue Infrastructure*
*Context gathered: 2026-07-22*
