# Phase 5: sqlite Hardening + Action Queue Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-22
**Phase:** 5-sqlite Hardening + Action Queue Infrastructure
**Areas discussed:** Action lifecycle & feedback, Dispatch latency, Failure & stuck-action handling, Queue shape & proven bar

---

## Action lifecycle & panel feedback

**Q1 — Where does a Manager see status move from pending → done?**

| Option | Description | Selected |
|--------|-------------|----------|
| Inline on the item | Row/button updates in place: Approving… → ✓ Published / ✗ Failed | ✓ |
| Reuse Overview activity feed | Actions surface in the existing activity_log feed on Overview | |
| Both | Inline status AND a durable Overview log line | |

**Q2 — On failure, what does the Manager see / can they act?**

| Option | Description | Selected |
|--------|-------------|----------|
| Error + re-trigger button | Short reason + Retry that re-enqueues | ✓ |
| Generic "failed, retry" | Failed state + retry, no error detail surfaced | |
| You decide | Match house pattern at planning | |

**Q3 — Retention of completed/failed rows?**

| Option | Description | Selected |
|--------|-------------|----------|
| Keep-last-N, purge on write | activity_log idiom (keep_last, purge-on-write) | ✓ |
| Keep until acknowledged | Rows stay until Manager dismisses | |
| Time-window prune | Drop rows older than a fixed window | |

**Notes:** Retry re-enqueue interacts with the delivery guarantee (see Failure area). The optional durable Overview log line remains available but inline is the primary feedback.

---

## Dispatch latency

**Q1 — How fast should the bot pick up a queued action?**

| Option | Description | Selected |
|--------|-------------|----------|
| Near-instant (~1–2s) | Tight poll loop; click feels immediate | ✓ |
| A few seconds (~5s) | Lighter on wake-ups, spinner-backed | |
| You decide the interval | Lock "feels immediate", pick interval at planning | |

**Q2 — How does the panel reflect completion (websockets out of scope)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-refresh the pending item | Alpine short-polls status, flips to ✓/✗, no reload | ✓ |
| Manual reload | Manager reloads to see outcome | |
| You decide | Pick at planning | |

**Notes:** Implies an app-side per-action status-read endpoint the pending item polls.

---

## Failure & stuck-action handling

**Q1 — Auto-retry vs fail-fast on a transient failure?**

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-retry a few times, then fail | Backoff (~3 attempts) before marking failed; manual Retry remains | ✓ |
| Fail fast, manual retry only | One attempt → failed with reason + Retry | |
| You decide | Lock "failures recoverable", choose at planning | |

**Q2 — Bot offline when an action is queued?**

| Option | Description | Selected |
|--------|-------------|----------|
| "Bot offline — will run on reconnect" | Heartbeat staleness → clear queued state, dispatches on return | ✓ |
| Time out pending → failed | Old pending auto-fails; retry when bot returns | |
| Both | Offline state + timeout backstop | |

**Q3 — Delivery guarantee (Phase 7 must never double-publish)?**

| Option | Description | Selected |
|--------|-------------|----------|
| At-least-once + per-module idempotency | May re-run on crash; each module owns its own dedup | ✓ |
| At-most-once (claim-before-dispatch) | Won't auto-re-run; can be silently skipped | |
| You decide | Lock "never double-publish", pick protocol at planning | |

**Notes:** At-least-once + auto-retry makes module idempotency a **binding constraint on Phases 6–9**. The queue never silently drops an action; the double-publish invariant is delegated to module-level idempotency (Phase-7 🟢-marker guard already owns this).

---

## Queue shape & the "proven" bar

**Q1 — How generic is the queue?**

| Option | Description | Selected |
|--------|-------------|----------|
| One shared table, typed + JSON payload | Single action_queue: action_type + payload_json + status | ✓ |
| Per-module queue tables | Typed per module, duplicates dispatch/retry/status machinery | |

**Q2 — Dispatch concurrency?**

| Option | Description | Selected |
|--------|-------------|----------|
| Serialized (one at a time) | Oldest-first, one per tick, predictable | ✓ |
| Concurrent dispatch | Parallel dispatch, adds ordering/contention complexity | |
| You decide | Lock "correct + simple", choose at planning | |

**Q3 — Retry/backoff wrapper scope (busy_timeout is global regardless)?**

| Option | Description | Selected |
|--------|-------------|----------|
| All write paths (centralize) | busy_timeout + route existing writes through retry helper | |
| Queue writes only, busy_timeout global | Retry wrapper only on new queue paths | |
| You decide | Let research judge existing-surface retry need | ✓ |

**Q4 — "Proven under load" go/no-go bar?**

| Option | Description | Selected |
|--------|-------------|----------|
| Automated concurrent-load test | Concurrent writers assert zero "database is locked", committed to suite | ✓ |
| Retry-wrapper unit test | Simulate locked DB, assert retry-then-succeed | |
| You decide | Lock "no lock under concurrent writers, proven by test" | |

**Notes:** busy_timeout in _get_conn() is locked (one line, global). Retry-wrapper scope delegated to research; PITFALLS.md Pitfall 3 guidance is the deciding input. The chosen load test matches PITFALLS.md's recommended load test.

---

## Claude's Discretion

- Retry/backoff wrapper scope — all write paths vs queue-only (busy_timeout global regardless); floor = busy_timeout global + retry on action_queue paths.
- Exact action_queue schema/column names, claim/complete state names + stale-claim recovery, precise poll interval within the ~1–2s envelope, backoff attempt count/delays, keep-last-N value, concurrent-load-test harness design.
- Whether a durable activity_log line is also written per action alongside inline status.

## Deferred Ideas

- Real per-module action logic (gallery/reviews/jinxxy/meetings) — Phases 6–9 build on the queue; Reminders (Phase 6) deliberately bypass it (pure DB CRUD).
- Concurrent/parallel queue dispatch — rejected for serialized; revisit only if volume ever demands it.
