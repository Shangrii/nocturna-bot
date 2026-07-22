# Phase 5: sqlite Hardening + Action Queue Infrastructure - Research

**Researched:** 2026-07-22
**Domain:** Cross-process (bot ↔ FastAPI app) generic action queue over shared sqlite; sqlite writer/writer contention hardening
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01: Inline status on the clicked item.** Each module renders the action's
  status from its queue row **on the item itself** — the row/button flips
  `Working…` -> `OK <done>` / `FAILED`. Not a remote feed. (The Phase-3
  `activity_log` Overview feed is separate and MAY still receive a durable log line
  per action, but the primary, load-bearing feedback is inline — see D-11.)
- **D-02: Failed actions surface a short reason + a Retry button.** A failed row
  shows a concise reason (e.g. "Discord: missing permissions") and a **Retry**
  control that **re-enqueues** the action, so a Manager self-recovers without shell
  access. Re-enqueue interacts with idempotency — see D-08.
- **D-03: Completed/failed rows bounded by keep-last-N, purge-on-write.** Exact
  `activity_log` idiom (`INSERT` then `DELETE ... WHERE id NOT IN (SELECT id ...
  ORDER BY id DESC LIMIT N)`). Rolling recent history, self-limiting, no cron/sweep.
- **D-04: Near-instant dispatch (~1-2s).** The bot claims/dispatches on a tight
  `tasks.loop` (~1-2s), NOT the ~45s heartbeat cadence.
- **D-05: The pending item auto-refreshes (no reload).** While an action is
  pending, the panel short-polls its status (Alpine, already shipped) and flips
  the item to done/failed on its own. Implies an app-side per-action status-read
  endpoint. Websockets remain out of scope.
- **D-06: Auto-retry with backoff, then fail.** On a transient dispatch error the
  bot retries with backoff (small bounded attempt count) before marking the
  action failed; the manual Retry (D-02) remains for genuine failures.
- **D-07: Bot-offline is a distinct state, detected via `bot_heartbeat`.** When
  the bot is down (heartbeat stale), a queued action shows "bot offline — will
  run on reconnect" instead of an endless spinner. The queue is durable: the
  action stays pending and dispatches when the bot returns. No lost clicks.
- **D-08: At-least-once delivery + per-module idempotency.** The bot
  claims -> dispatches -> marks complete; a crash mid-flight may re-run the
  action on recovery (a stale `claimed` row is retried, aligning with D-07's
  durable queue). Every module that rides the queue (Phases 6-9) MUST make its
  own dispatch idempotent. **INVARIANT (binding on Phases 6-9): the queue must
  never cause a double-publish — idempotency is the module's responsibility.**
  The queue never silently drops an action.
- **D-09: One shared, generic `action_queue` table.** `kind` (e.g.
  `gallery_publish`, `meeting_republish`) + `payload_json` + status / error /
  requested_by / timestamps. All modules enqueue into the same table; the bot
  dispatches by kind. Per-module queue tables explicitly rejected.
- **D-10: Serialized dispatch (one at a time).** The bot processes the queue
  oldest-first (`ORDER BY id`), one action per tick. Concurrent/parallel
  dispatch rejected.
- **D-12: Go/no-go gate = an automated concurrent-load test.** A test spins up a
  simulated bot write-loop + panel write burst against the shared DB and asserts
  zero unhandled "database is locked" escapes, committed to the suite as the
  gate before any module builds on the infra.

### Claude's Discretion

- **D-11: Retry/backoff wrapper scope (delegated to research/planning).**
  `busy_timeout` goes into `core/db.py::_get_conn()` **globally** (locked — one
  line, protects every write path). Whether the explicit retry/backoff wrapper
  wraps **all** existing write paths or **only** the new high-contention
  `action_queue` paths is left to research — PITFALLS.md guidance (retry needed
  for high-frequency paths; `busy_timeout` alone may suffice for rare ones) is
  the deciding input. **Floor:** at minimum `busy_timeout` global + retry on the
  two-way `action_queue` paths.
- Exact `action_queue` schema / column names; the `claimed`/`complete` state
  names and the stale-`claimed` recovery mechanism (implementing D-08); the
  precise poll interval within the ~1-2s envelope; backoff attempt count and
  delays; the keep-last-N value (D-03); and the concurrent-load-test harness
  design (D-12) — all deferred to researcher/planner.
- Whether a durable `activity_log` line is also written per action (in addition
  to inline status) — optional per module (D-01).

### Deferred Ideas (OUT OF SCOPE)

- **Real per-module action logic** (gallery approve/remove, reviews
  approve/remove, Jinxxy manual sync, meeting re-publish) — Phases 6-9 build ON
  this queue; Phase 5 only proves the infra. Reminders (Phase 6) deliberately
  bypass the queue (pure DB CRUD) per ARCHITECTURE.md.
- **Concurrent (parallel) queue dispatch** — rejected in favor of serialized
  (D-10); revisit only if volume ever demands it (it won't at one-guild scale).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-------------------|
| INFRA-01 | Panel->bot actions (approve, sync, re-publish) travel through a queue table in the shared sqlite that the bot dispatches, with action status visible in the panel. | Pattern 1 (`action_queue` schema + claim/complete/fail state machine), Pattern 2 (`ActionQueueCog` dispatch loop), Pattern 3 (enqueue/status/retry FastAPI routes) — full working code for enqueue, claim_next, complete, fail, retry, recover_stale_claims, and the dispatch loop; Pitfalls 1-3 cover the state-machine correctness risks specific to this requirement; Validation Architecture maps each lifecycle behavior to a concrete test. |
| INFRA-02 | The shared sqlite is hardened for concurrent writers (busy_timeout + retry) before the first write-heavy module ships. | `_get_conn()` PRAGMA change (Code Examples), `_retry_on_locked` decorator (Pattern 1), D-11 scope recommendation (retry wrapper on action_queue paths only, busy_timeout global) in Summary/Standard Stack, and the committed D-12 concurrent-load test (Code Examples, Validation Architecture) as the go/no-go gate. |
</phase_requirements>

## Summary

This phase has almost no ecosystem-research surface — zero new pip dependencies, no new
framework, no external API. The real work is **precise protocol design** on top of
patterns this codebase already ships four times over (`gallery_state`, `bot_heartbeat`,
`jinxxy_sync_status`, `discord_names`): fresh-connection-per-call, `CREATE TABLE IF NOT
EXISTS` in a cog's `__init__`, `INSERT OR REPLACE`/`ON CONFLICT` upserts, `tasks.loop`
polling cogs, and (as of Phase 3/4) `require_manager`, `_bot_online()`/
`_HEARTBEAT_STALE_SECONDS`, and Alpine short-polling of a JSON status endpoint already
exist and are directly reusable.

The two genuinely new design problems this research resolves are: (1) the exact
`action_queue` claim/complete/fail state machine that gives at-least-once delivery with
stale-claim recovery *without* accidentally purging a still-pending row (a naive copy of
the `activity_log` keep-last-N idiom would do exactly that — see Pitfall 1 below), and
(2) a concurrent-load test harness that reliably produces genuine multi-connection sqlite
writer/writer contention on Windows/WAL so the busy_timeout+retry fix has something real
to prove itself against.

**Primary recommendation:** Add one explicit `PRAGMA busy_timeout` line to
`core/db.py::_get_conn()` (global, one choke point); build `core/action_queue.py` as a
pure module with `enqueue`/`claim_next`/`complete`/`fail`/`recover_stale_claims`/`retry`
functions wrapped in a small in-house retry-on-`database is locked` decorator (no new
dependency); dispatch via a new `cogs/action_queue_worker.py` `ActionQueueCog` on a
1.5s `tasks.loop`; expose two generic FastAPI endpoints (`POST /api/actions`,
`GET /api/actions/{id}`) gated by the already-existing `require_manager`; and commit a
multi-threaded pytest concurrency test as the D-12 go/no-go gate.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `action_queue` table + claim/complete/fail state machine | Database / Storage | — | Pure sqlite contract; both processes read/write the same table, no in-process state |
| `busy_timeout` + retry/backoff wrapper | Database / Storage | API/Backend (bot), API/Backend (app) | The PRAGMA is connection-scoped (DB tier); the retry decorator wraps call sites in both processes |
| `ActionQueueCog` (claim → dispatch → complete/fail loop) | API/Backend (bot process) | Database / Storage | Bot-owned business logic dispatch; only the bot process ever executes an action's real side effects |
| Manager-gated enqueue route | API/Backend (FastAPI app) | — | `require_manager` already lives here; this phase adds two thin generic routes, no new auth surface |
| Per-action status-read endpoint | API/Backend (FastAPI app) | — | Read-only poll target; no Discord credential involved (Pitfall 4 stays satisfied) |
| Inline status widget + Alpine short-poll | Browser / Client | Frontend rendering (Jinja) | Purely presentational; server does all authorization and state transitions |
| Concurrent-load test | (test infra, not a runtime tier) | — | Exercises DB tier from two simulated "processes" (threads) in one pytest process |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlite3` (stdlib) | Python 3.12.8 bundles SQLite 3.45.3 [VERIFIED: `python -c "import sqlite3; print(sqlite3.sqlite_version)"` on the project's conda interpreter] | `action_queue` table, `PRAGMA busy_timeout`, WAL | Already the project's only persistence layer; SQLite 3.45 fully supports `PRAGMA busy_timeout` and WAL — no version gap |
| `discord.ext.tasks` (via discord.py, already installed) | unchanged | `ActionQueueCog`'s ~1.5s poll loop | Identical idiom to `cogs/heartbeat.py` (45s) and `cogs/discord_names.py` (5min) already in this repo [VERIFIED: read directly] |
| `fastapi` / Starlette `run_in_threadpool` (already installed) | unchanged | Enqueue + status-read routes | Same idiom as `api_overview_status`/`db.get_presence` calls today [VERIFIED: app/main.py] |
| `concurrent.futures.ThreadPoolExecutor` (stdlib) | Python 3.12 | Concurrent-load test's simulated panel-write burst | Real OS-thread contention against the same sqlite file, no new dependency |

### Supporting

None. No new pip package is needed anywhere in this phase — the SUMMARY.md milestone
research already established "zero new pip dependencies" for the whole v2.0 milestone,
and this phase does not change that.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-house retry-on-`database is locked` decorator (~15 lines) | `tenacity` (pip) | Tenacity is more general (jitter, multiple exception types, async support) but is a new dependency for a 3-attempt/fixed-delay need — rejected, matches the project's own documented "reject new deps when the existing idiom suffices" discipline (SUMMARY.md, PITFALLS.md rejected `slowapi` for the same reason) |
| Threaded pytest concurrency test | `pytest-xdist` / a separate multiprocessing harness | True separate OS processes would be a slightly more faithful simulation of "bot process + app process," but Python threads already release the GIL around every `sqlite3` C-level I/O call, so genuine file-level writer/writer contention occurs between threads without the complexity of spawning subprocesses in a test; multiprocessing also complicates monkeypatching `config.DB_PATH` per-test. Threads are the pragmatic, deterministic choice here. |
| Fixed-delay backoff (50ms/150ms/400ms) for the DB-lock retry wrapper | Exponential-with-jitter | Simpler to reason about and test deterministically at this volume (a handful of staff, rare true collisions); revisit only if the D-12 load test shows repeated exhaustion of 3 attempts |

**Installation:** None required — everything is stdlib or already in `requirements.txt`.

**Version verification:** Confirmed directly against the project's test-run interpreter
(per user memory: use the conda Python, not PowerShell's):
```
C:\Users\Shangri\miniconda3\python.exe -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"
# 3.12.8 | Anaconda ... ; sqlite3 lib version 3.45.3
```
[VERIFIED: ran directly in this session] — both `PRAGMA busy_timeout` and WAL are supported without qualification at this version.

## Package Legitimacy Audit

Not applicable — this phase installs no new packages. Skipping the legitimacy gate per
its own scope condition ("required whenever this phase installs external packages").

## Architecture Patterns

### System Architecture Diagram

```
 Manager clicks "Approve" (or, for this infra phase, a proof/self-test trigger)
        │
        ▼
 POST /api/actions  {kind, payload}                    [FastAPI app process]
   Depends(require_manager)  ──► action_queue.enqueue(kind, payload, requested_by)
        │                              │
        │                              ▼
        │                    action_queue row inserted, status='pending'
        │                              │
        ▼                              │
 Response {id}                         │            shared sqlite file (WAL, busy_timeout)
        │                              │                         │
        ▼                              │                         │
 Alpine short-poll (~1-2s)             │                         │
 GET /api/actions/{id}  ───────────────┼─────────────────────────┤
   Depends(require_manager)            │                         │
   reads row + _bot_online()           │                         │
        │                              │                         │
        │                              │                         ▼
        │                    ┌─────────┴──────────────────────────────────┐
        │                    │   ActionQueueCog  (tasks.loop, ~1.5s tick)  │  [bot process]
        │                    │   1. recover_stale_claims()                │
        │                    │   2. row = claim_next()  (status→'claimed')│
        │                    │   3. handler = dispatch[row.kind]          │
        │                    │   4. result = await handler(payload)       │
        │                    │   5a. complete(id, result) → status='done' │
        │                    │   5b. fail(id, error) → retry w/ backoff   │
        │                    │       or status='failed' after N attempts │
        │                    └─────────────────────────────────────────────┘
        ▼
 Panel poll sees status='done'/'failed' → flips inline widget
 (✓/✗ + reason + Retry button on failed)
```

### Recommended Project Structure

```
core/
├── db.py                    # + init_action_queue(), + PRAGMA busy_timeout in _get_conn()
└── action_queue.py          # NEW — pure module: enqueue/claim_next/complete/fail/
                              #   recover_stale_claims/retry/get_status + _retry_on_locked
                              #   decorator + _purge_terminal helper

cogs/
└── action_queue_worker.py   # NEW — ActionQueueCog: tasks.loop(seconds=1.5), a
                              #   {kind: handler} dispatch registry, "noop" proof kind

app/
└── main.py                  # + POST /api/actions (require_manager, allowlisted kinds)
                              # + GET  /api/actions/{id} (require_manager)
                              # + POST /api/actions/{id}/retry (require_manager)
                              # + db.init_action_queue() added to the lifespan init block
```

Keeping the two/three new routes directly in `app/main.py` (rather than starting the
`app/routers/` package ARCHITECTURE.md sketches for the milestone) matches the CURRENT
codebase reality — every route lives in `app/main.py` today, including the Phase 3/4
dashboard-shell and settings routes. Starting an empty `routers/` package for two generic
endpoints is premature; Phases 6-9 (which each need several module-specific routes) are
the natural point to introduce it, and can migrate these two generic routes in at that
time without churn to this phase's deliverable.

### Pattern 1: `action_queue` schema + claim/complete/fail state machine

**What:** One table, four states (`pending` / `claimed` / `done` / `failed`), a
`next_attempt_at` column for auto-retry backoff (D-06), and an `attempts` counter.

```sql
CREATE TABLE IF NOT EXISTS action_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending|claimed|done|failed
    result_json     TEXT,
    error           TEXT,
    requested_by    TEXT    NOT NULL,
    requested_at    TEXT    NOT NULL,
    claimed_at      TEXT,
    completed_at    TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT
)
CREATE INDEX IF NOT EXISTS idx_action_queue_status ON action_queue(status)
```

**When to use:** Every panel-initiated action from Phase 6 onward enqueues into this
SAME table by `kind` — no per-module tables (D-09 locked).

**Example (core/action_queue.py, pure — no discord/fastapi import):**
```python
# Source: this repo's core/db.py idiom (gallery_state / bot_heartbeat / discord_names),
# generalized per CONTEXT.md D-08/D-10 and PITFALLS.md Pitfall 3 retry guidance.
import json, sqlite3, time, functools
from datetime import datetime, timezone, timedelta
from core import db

_LOCK_RETRY_DELAYS = (0.05, 0.15, 0.4)   # 3 extra attempts beyond the first try
_MAX_DISPATCH_ATTEMPTS = 3               # D-06 "small bounded attempt count"
_BACKOFF_SECONDS = (2, 5, 15)            # attempt 1/2/3 requeue delay
_STALE_CLAIM_SECONDS = 60                # >> the ~1.5s tick; distinguishes crash from in-flight

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _retry_on_locked(fn):
    """Retries a write on 'database is locked' after busy_timeout itself is exhausted.
    Floor of D-11: applied ONLY to the new high-frequency action_queue write paths."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        last_exc = None
        for delay in (0.0,) + _LOCK_RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                last_exc = exc
        raise last_exc
    return wrapper

@_retry_on_locked
def enqueue(kind: str, payload: dict, requested_by: str) -> int:
    with db._get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso()),
        )
        return cur.lastrowid

@_retry_on_locked
def recover_stale_claims() -> int:
    """D-08: a 'claimed' row older than _STALE_CLAIM_SECONDS survived a bot crash
    mid-dispatch — requeue it so claim_next() retries it (at-least-once delivery)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_STALE_CLAIM_SECONDS)).isoformat()
    with db._get_conn() as conn:
        cur = conn.execute(
            "UPDATE action_queue SET status='pending' WHERE status='claimed' AND claimed_at < ?",
            (cutoff,),
        )
        return cur.rowcount

@_retry_on_locked
def claim_next() -> sqlite3.Row | None:
    """D-10: serialized, oldest-first. Skips rows still in backoff (next_attempt_at future)."""
    now = _now_iso()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM action_queue WHERE status='pending' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY id LIMIT 1", (now,),
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "UPDATE action_queue SET status='claimed', claimed_at=? WHERE id=? AND status='pending'",
            (now, row["id"]),
        )
        if cur.rowcount == 0:
            return None   # defensive; single bot process makes this unreachable today
    return row

def _purge_terminal(conn, keep_last: int = 50):
    """D-03 keep-last-N, purge-on-write — but scoped to done|failed ONLY (Pitfall 1)."""
    conn.execute("""
        DELETE FROM action_queue
        WHERE status IN ('done', 'failed')
        AND id NOT IN (
            SELECT id FROM action_queue WHERE status IN ('done', 'failed')
            ORDER BY id DESC LIMIT ?
        )
    """, (keep_last,))

@_retry_on_locked
def complete(action_id: int, result: dict):
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET status='done', result_json=?, completed_at=? WHERE id=?",
            (json.dumps(result), _now_iso(), action_id),
        )
        _purge_terminal(conn)

@_retry_on_locked
def fail(action_id: int, error: str):
    """D-06 auto-retry with backoff, then D-02's terminal 'failed' + manual Retry."""
    with db._get_conn() as conn:
        row = conn.execute("SELECT attempts FROM action_queue WHERE id=?", (action_id,)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        if attempts < _MAX_DISPATCH_ATTEMPTS:
            delay = _BACKOFF_SECONDS[min(attempts - 1, len(_BACKOFF_SECONDS) - 1)]
            next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            conn.execute(
                "UPDATE action_queue SET status='pending', attempts=?, next_attempt_at=?, error=? "
                "WHERE id=?", (attempts, next_attempt, error, action_id),
            )
        else:
            conn.execute(
                "UPDATE action_queue SET status='failed', attempts=?, error=?, completed_at=? "
                "WHERE id=?", (attempts, error, _now_iso(), action_id),
            )
            _purge_terminal(conn)

@_retry_on_locked
def retry(action_id: int, requested_by: str) -> int | None:
    """D-02 manual Retry — re-enqueues a FRESH row from a terminal 'failed' row's kind+payload.
    Never mutates the old row in place (it stays as bounded history until purge)."""
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT kind, payload_json FROM action_queue WHERE id=? AND status='failed'",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (row["kind"], row["payload_json"], requested_by, _now_iso()),
        )
        return cur.lastrowid

def get_status(action_id: int) -> sqlite3.Row | None:
    with db._get_conn() as conn:
        return conn.execute("SELECT * FROM action_queue WHERE id=?", (action_id,)).fetchone()
```

### Pattern 2: `ActionQueueCog` dispatch loop (bot side)

**What:** A `tasks.loop(seconds=1.5)` cog with a `{kind: handler}` dispatch registry,
mirroring `cogs/heartbeat.py`/`cogs/discord_names.py`'s `asyncio.to_thread` +
`before_loop: wait_until_ready` + `cog_unload: cancel` idiom exactly.

```python
# Source: this repo's cogs/heartbeat.py and cogs/discord_names.py (read directly)
import asyncio, json, logging
from discord.ext import commands, tasks
from core import action_queue, db

log = logging.getLogger(__name__)

class ActionQueueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        db.init_action_queue()
        self._dispatch = {"noop": self._handle_noop}   # Phases 6-9 register more kinds here
        self._tick.start()

    async def cog_unload(self):
        self._tick.cancel()

    @tasks.loop(seconds=1.5)   # D-04: near-instant, NOT the 45s heartbeat cadence
    async def _tick(self):
        try:
            await asyncio.to_thread(action_queue.recover_stale_claims)
            row = await asyncio.to_thread(action_queue.claim_next)
        except Exception:
            log.exception("action_queue: no pude reclamar/recuperar filas")
            return
        if row is None:
            return
        handler = self._dispatch.get(row["kind"])
        payload = json.loads(row["payload_json"])
        try:
            if handler is None:
                raise ValueError(f"unknown action kind: {row['kind']!r}")
            result = await handler(payload)
            await asyncio.to_thread(action_queue.complete, row["id"], result)
        except Exception as exc:
            log.exception("action_queue: acción %s falló", row["id"])
            await asyncio.to_thread(action_queue.fail, row["id"], str(exc))

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()

    async def _handle_noop(self, payload: dict) -> dict:
        """The Phase-5 proof action (see 'A proof action' below) — exercises the full
        enqueue→claim→dispatch→complete/fail→status path with zero real business logic."""
        if payload.get("force_fail"):
            raise RuntimeError("noop: forced failure (test payload)")
        return {"echo": payload.get("echo")}

async def setup(bot):
    await bot.add_cog(ActionQueueCog(bot))
```

Register in `bot.py` alongside the other always-loaded cogs:
`await self.load_extension("cogs.action_queue_worker")`.

### Pattern 3: App-side enqueue + status + retry routes

```python
# Source: this repo's app/main.py idiom (api_overview_status, require_manager usage)
from starlette.concurrency import run_in_threadpool
from core import action_queue

_ALLOWED_KINDS = {"noop"}   # Phases 6-9 extend this allowlist per module

@app.post("/api/actions")
async def api_enqueue_action(request: Request, roles: dict = Depends(require_manager)):
    body = await request.json()
    kind = body.get("kind")
    if kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=422, detail="unknown action kind")
    action_id = await run_in_threadpool(
        action_queue.enqueue, kind, body.get("payload", {}), str(roles["discord_id"]),
    )
    return JSONResponse({"id": action_id})

@app.get("/api/actions/{action_id}")
async def api_action_status(action_id: int, roles: dict = Depends(require_manager)):
    row = await run_in_threadpool(action_queue.get_status, action_id)
    if row is None:
        raise HTTPException(status_code=404)
    return JSONResponse({
        "id": row["id"], "status": row["status"], "error": row["error"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "bot_online": await _bot_online(),   # D-07: reuse the EXISTING Phase-3 helper
    })

@app.post("/api/actions/{action_id}/retry")
async def api_retry_action(action_id: int, roles: dict = Depends(require_manager)):
    new_id = await run_in_threadpool(action_queue.retry, action_id, str(roles["discord_id"]))
    if new_id is None:
        raise HTTPException(status_code=409, detail="action is not in a failed state")
    return JSONResponse({"id": new_id})
```

Add `db.init_action_queue()` to the existing dual-process init block in `app/main.py`'s
`lifespan` (next to `db.init_activity_log()`, `db.init_discord_names()` — same
try/except-wrapped block at ~line 285-290).

### Anti-Patterns to Avoid

- **Purging `action_queue` with the unmodified `activity_log` keep-last-N idiom.**
  `activity_log` has no non-terminal state — every row is immediately "final." Copying its
  `DELETE ... WHERE id NOT IN (SELECT id ... ORDER BY id DESC LIMIT N)` verbatim onto
  `action_queue` (with no `WHERE status IN ('done','failed')` filter) will delete a
  long-pending row (e.g. one waiting for the bot to reconnect, D-07) the moment enough
  *other* actions complete — this directly breaks the "queue never silently drops an
  action" invariant (D-08). See Pitfall 1 below.
- **Manual Retry (D-02) mutating the same row instead of minting a fresh one.** Reusing
  the same `id` for a retried action blurs "the click that just failed" with "the new
  attempt" in a way that complicates the panel's poll target and any future idempotency
  key derived from the row id. Mint a new row; let the old failed row age out via the
  keep-last-N purge.
- **Skipping `asyncio.to_thread` around the cog's DB calls "since it's fast."** At a 1.5s
  tick (vs. heartbeat's 45s), a blocking sqlite call directly on the event loop is
  proportionally far more disruptive to Discord gateway responsiveness — always wrap, no
  exceptions, matching the existing `cogs/heartbeat.py`/`cogs/discord_names.py` idiom.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry-on-lock backoff | A general-purpose retry library (`tenacity`, `backoff`) | A ~15-line in-house decorator (`_retry_on_locked`) | New dependency for a fixed 3-attempt/fixed-delay need contradicts this project's own "reject new deps when the existing idiom suffices" discipline (already validated for `slowapi` in PITFALLS.md) |
| Cross-process task queue | Celery / RQ / Redis-backed queue | The existing shared-sqlite `action_queue` table + `tasks.loop` poller | A message broker/Redis dependency reverses the locked "sqlite is the only channel" project decision and is unjustifiable at one-guild, single-digit-staff volume |
| Distributed locking for claim safety | A lease/fencing-token library | A conditional `UPDATE ... WHERE status='pending'` (single-writer-per-tick, single bot process) | D-10 already locks serialized, single-bot dispatch — there is no second bot process to race against; the conditional UPDATE is a defensive no-op today, not a real distributed-lock need |
| Stale-claim detection | A heartbeat/lease-renewal protocol per in-flight action | A simple `claimed_at` timestamp + threshold requeue | One bot process, one action in flight at a time (D-10) — a fixed staleness window is sufficient and matches the existing `bot_heartbeat` staleness idiom already in this codebase |

**Key insight:** Every "don't hand-roll" temptation in this phase is really "don't import
a new general-purpose library for a problem this codebase's own existing single-process,
single-writer, low-volume constraints have already simplified away."

## Common Pitfalls

### Pitfall 1: Copying the `activity_log` purge idiom verbatim corrupts the durable queue

**What goes wrong:** `activity_log`'s `log_activity()` purges with
`DELETE FROM activity_log WHERE id NOT IN (SELECT id ... ORDER BY id DESC LIMIT N)` — every
row is disposable history. If `action_queue`'s purge copies this pattern without adding
`WHERE status IN ('done','failed')` to BOTH the outer `DELETE` and the inner `SELECT`, a
row that has been sitting `pending` for a while (e.g., because the bot was offline per
D-07) can be deleted the instant `keep_last` OTHER actions reach a terminal state around
it — the queue silently drops a still-pending action, which directly violates D-08's "the
queue never silently drops an action" invariant.

**Why it happens:** `action_queue` is the first table in this codebase with a
non-terminal state that must survive a keep-last-N purge; every prior "purge-on-write"
precedent (`activity_log`, `view_dedup`'s cutoff-based purge) had no such requirement.

**How to avoid:** Always scope both the inner and outer clause of the purge query to
`status IN ('done', 'failed')` (see `_purge_terminal` above). Add a unit test that inserts
a `pending` row, then completes `keep_last + 5` other actions, and asserts the original
`pending` row still exists.

**Warning signs:** A purge query on `action_queue` that doesn't mention `status` at all.

---

### Pitfall 2: Stale-claim threshold too close to the tick interval causes a live double-dispatch

**What goes wrong:** If `_STALE_CLAIM_SECONDS` is set too low relative to how long a
REAL dispatch handler takes (this phase's `noop` handler is instant, but Phase 6-9's real
handlers will call Discord/GitHub APIs that can legitimately take several seconds), a
still-in-flight, perfectly healthy dispatch gets requeued by `recover_stale_claims()` and
claimed a second time on the very next tick — producing a genuine double-dispatch that
D-08's "queue must never cause a double-publish" invariant explicitly worries about,
except now self-inflicted by the recovery mechanism itself rather than a crash.

**Why it happens:** The proof action in this phase is instantaneous, so a low threshold
"looks fine" in Phase 5 testing but is a landmine for Phase 6-9's real, slower handlers.

**How to avoid:** Set `_STALE_CLAIM_SECONDS` generously (this research recommends 60s —
40x the 1.5s tick) and document loudly in `core/action_queue.py` that Phases 6-9 MUST
confirm their real dispatch handlers complete well within this window (or the threshold
must be revisited then, not assumed frozen). Add a test that starts a handler that sleeps
past the tick interval but well under the stale threshold, and asserts it is NOT reclaimed
mid-flight.

**Warning signs:** A future phase's dispatch handler that can legitimately run longer than
a fraction of `_STALE_CLAIM_SECONDS` (e.g., a slow GitHub commit retry-with-backoff loop).

---

### Pitfall 3: Conflating the D-06 auto-retry and the D-02 manual Retry mechanisms

**What goes wrong:** D-06 (auto-retry with backoff) operates on a row that never leaves
`pending`/`claimed` — it's an internal bounded-attempt loop before the row is ever marked
terminal. D-02 (the panel's manual Retry button) only ever applies to a row ALREADY in the
terminal `failed` state, and (per this research's recommendation) mints a brand-new row.
If a future code change lets the manual Retry endpoint act on a `pending` row (e.g., by
loosening the `WHERE status='failed'` guard in `retry()` "to be more flexible"), a Manager
could double-enqueue an action that's still auto-retrying internally.

**How to avoid:** Keep `retry()`'s guard (`AND status='failed'`) exactly as designed;
never widen it. The panel's Retry button should be hidden/disabled for any status other
than `failed` (D-02's own language: "a failed row shows ... a Retry control").

---

### Pitfall 4 (inherited from milestone PITFALLS.md Pitfall 3): sqlite writer/writer contention

**What goes wrong / why it happens / recovery:** See `.planning/research/PITFALLS.md`
Pitfall 3 in full — WAL solves reader/writer blocking only, not writer/writer contention;
no connection here sets `busy_timeout` explicitly today; the implicit Python
`sqlite3.connect()` default busy-timeout is 5s [CITED: docs.python.org sqlite3 module,
`connect(..., timeout=5.0)` default] but was never a documented, intentional choice.

**How this phase avoids it:** Explicit `PRAGMA busy_timeout=8000` in `_get_conn()`
(global — D-11 locked) + the `_retry_on_locked` decorator on all five `action_queue`
write functions (D-11 floor) + the D-12 concurrent-load test proving zero unhandled
`database is locked` under a real multi-threaded burst.

---

### Pitfall 5: `tasks.loop`-based cogs are hard to unit-test directly — test the extracted logic, not the loop

**What goes wrong:** discord.py's `tasks.loop` decorator wraps a coroutine in scheduling
machinery that is awkward to invoke exactly once in a synchronous pytest run.

**How to avoid:** Follow this repo's own precedent in `tests/test_discord_names_cog.py` —
that file tests `_map_channel_kind`/`_role_hex`/`_snapshot_rows` (the PURE helper
functions the cog's loop body calls), never the `tasks.loop`-decorated method itself. For
`ActionQueueCog`, extract the per-tick body logic so it's callable directly in a test
(e.g., by calling `await cog._tick.coro(cog)` — discord.py's documented way to invoke a
loop's body once without starting the scheduler — or by structuring `_tick` to delegate
immediately to a plain `async def _run_once(self)` that tests call directly).

## Code Examples

See Pattern 1/2/3 above for the full `core/action_queue.py`, `cogs/action_queue_worker.py`,
and `app/main.py` route additions — all are complete, directly usable code, not
pseudocode, and follow this repo's existing idioms line-for-line where a precedent exists.

### `core/db.py::_get_conn()` change (the one-line INFRA-02 floor)

```python
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # INFRA-02: explicit, documented busy_timeout (was an undocumented ~5s connect() default).
    # 8000ms sits inside PITFALLS.md's cited 5000-10000ms range; the D-12 load test is the
    # empirical check on whether this value is adequate under real concurrent write bursts.
    conn.execute("PRAGMA busy_timeout=8000")
    return conn
```

### D-12 concurrent-load test (the go/no-go gate)

```python
# tests/test_action_queue_concurrency.py
"""INFRA-02 go/no-go gate (D-12): simulated bot write-loop + panel write burst against
the SAME sqlite file must never raise an unhandled 'database is locked'.

Run with the project's conda interpreter (per project test-run convention):
  C:\\Users\\Shangri\\miniconda3\\python.exe -m pytest tests/test_action_queue_concurrency.py -v
"""
import concurrent.futures
import sqlite3
import threading

import pytest

import config
from core import action_queue, db


def _use_tmp_db(monkeypatch, tmp_path):
    # tmp_path is always a LOCAL filesystem path under pytest — required for WAL (core/db.py
    # docstring notes WAL does not work over a network share).
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "concurrency.db"), raising=False)


def test_concurrent_bot_and_panel_writes_never_raise_database_locked(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_action_queue()

    stop = threading.Event()
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def _record(exc):
        with errors_lock:
            errors.append(exc)

    def bot_loop():
        # Tight loop (no sleep) — simulates the ActionQueueCog's ~1.5s tick but maximizes
        # contention density for the test's duration instead of waiting real wall-clock time.
        while not stop.is_set():
            try:
                action_queue.recover_stale_claims()
                row = action_queue.claim_next()
                if row is not None:
                    action_queue.complete(row["id"], {"ok": True})
            except sqlite3.OperationalError as exc:
                _record(exc)

    def panel_burst(n: int):
        for i in range(n):
            try:
                action_queue.enqueue("noop", {"i": i}, requested_by="test-manager")
            except sqlite3.OperationalError as exc:
                _record(exc)

    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    # 16 concurrent "panel clicks", 25 writes each = 400 rapid inserts racing the bot
    # thread's claim/complete writes on the same file.
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(panel_burst, 25) for _ in range(16)]
        concurrent.futures.wait(futures, timeout=30)

    stop.set()
    bot_thread.join(timeout=5)

    assert errors == [], f"'database is locked' escaped unhandled: {errors!r}"

    # Sanity: every enqueued row was eventually claimed+completed (nothing silently lost).
    with db._get_conn() as conn:
        remaining_pending = conn.execute(
            "SELECT COUNT(*) AS n FROM action_queue WHERE status='pending'"
        ).fetchone()["n"]
    assert remaining_pending == 0
```

**Development-time verification (not committed as a flaky CI test):** before trusting
this test as the D-12 gate, temporarily comment out the `PRAGMA busy_timeout` line and the
`_retry_on_locked` decorator and re-run it once locally — it should then intermittently
raise `sqlite3.OperationalError: database is locked`, proving the harness is actually
capable of reproducing the failure this phase fixes. Do not commit a test designed to
flake; this is a one-time manual sanity check during implementation, documented as a code
comment above the test.

### A proof action for this infra phase

Recommend a single built-in `"noop"` action kind (shown fully in Pattern 2 above) as the
"proof": it exercises enqueue → claim → dispatch → complete/fail → status-poll end to end
with zero real module logic, and its `payload.force_fail` flag lets tests deterministically
exercise the D-06 auto-retry-then-fail path and the D-02 manual-Retry path without needing
any Discord/GitHub side effect. It ships as real (tiny, generic) infra code registered in
`ActionQueueCog._dispatch`, not a throwaway test-only branch — Phases 6-9 add
`gallery_publish`, `reviews_publish`, `jinxxy_sync`, `meeting_republish`, etc. to the SAME
registry dict, `noop` stays registered as a permanent diagnostic kind (harmless, useful for
future ops smoke-testing) rather than being ripped out afterward.

## State of the Art

Nothing in this phase depends on a fast-moving external ecosystem. `PRAGMA busy_timeout`
and WAL mode are stable SQLite features (WAL since 3.7.0, 2010; `busy_timeout` far older) —
no deprecation or version-gap risk at SQLite 3.45.3 / Python 3.12.8.

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Implicit ~5s `sqlite3.connect()` busy timeout | Explicit `PRAGMA busy_timeout=8000` | This phase | Documented, intentional, and independently tunable from the connect-level default; matches PITFALLS.md's explicit recommendation |
| Fresh-connection-per-call with no retry on transient lock | Same fresh-connection idiom + a thin retry decorator on the new high-frequency `action_queue` paths only | This phase | Existing low-frequency writers (reminders, heartbeat, jinxxy sync) are left unchanged per D-11's floor — `busy_timeout` alone is judged sufficient for them (PITFALLS.md's own carve-out for "rare" write paths) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `busy_timeout=8000` (ms) is an adequate value | Code Examples / Standard Stack | Too low: locked errors could still surface under a heavier future write burst than this phase's test simulates. Too high: a genuinely stuck writer could hold up a read/write for up to 8s. The D-12 load test is the mechanism to empirically validate/adjust this before sign-off. |
| A2 | Retry-decorator attempt count (3 extra) and delays (50/150/400ms) | Pattern 1 code | Reasoned estimate, not benchmarked against production write volume; revisit if the D-12 test or real usage shows repeated exhaustion of all attempts |
| A3 | Stale-claim threshold = 60s | Pattern 1 code / Pitfall 2 | Too low: a real (slower) Phase 6-9 dispatch handler could be double-claimed mid-flight (see Pitfall 2). Too high: a genuinely crashed action waits longer before self-healing. Flagged explicitly for Phase 6-9 planners to re-examine against their actual handler durations. |
| A4 | `keep_last=50` for the `action_queue` terminal-row purge | Pattern 1 code | No user-specified volume target exists for this table; if Phase 6-9 approval-queue traffic is much higher than assumed, 50 may be too small a rolling history for the panel's "recent activity" feel. Easy one-line tune, low risk either way. |
| A5 | D-06 backoff schedule (2s/5s/15s, max 3 attempts) | Pattern 1 code | Reasoned estimate matching CONTEXT.md's "small bounded attempt count" language, not empirically tuned against real Discord/GitHub transient-failure timing (which Phases 6-9 will actually exercise) |
| A6 | `"noop"` proof-action name/shape, and keeping it permanently registered rather than removing it after Phase 5 | Code Examples | Low risk — purely a naming/scope choice; a future contributor could rename or remove it without breaking anything downstream, since Phases 6-9 register their own kinds independently |
| A7 | Two new routes belong directly in `app/main.py` rather than starting `app/routers/` now | Recommended Project Structure | If Phase 6 planners strongly prefer starting the routers package immediately, this is a small, mechanical relocation — no logic changes, just an import/mount-point move |

## Open Questions

1. **Should the manual Retry (D-02) mint a fresh row or mutate the failed row in place?**
   - What we know: CONTEXT.md D-02 says Retry "re-enqueues" the action; D-03's keep-last-N
     purge implies terminal rows are expected to roll off naturally.
   - What's unclear: whether the panel's inline widget needs to keep polling the SAME id
     across a retry, or can switch to a new id returned by the retry endpoint.
   - Recommendation: mint a fresh row (implemented above) — the panel's JS receives the new
     `id` in the retry response and simply redirects its poll target, which is a small,
     already-necessary bit of client logic (Alpine already needs to hold the id in state).

2. **Exact `busy_timeout`/retry/backoff numeric values.**
   - What we know: PITFALLS.md cites a 5000-10000ms range for `busy_timeout` and "2-3
     retries" generally, sourced from a SQLite forum thread and Bert Hubert's article
     [CITED, MEDIUM confidence per PITFALLS.md's own sourcing].
   - What's unclear: the actual value that proves sufficient under THIS project's real
     future write volume (Phase 6-9 approval-queue bursts), which doesn't exist yet.
   - Recommendation: ship the values in this research (8000ms / 3 attempts / 60s stale
     threshold), treat the D-12 test as the mechanism to catch inadequacy empirically, and
     explicitly note in code comments that Phase 6-9 planners should re-run/extend this test
     against their own real write patterns before considering the values permanently settled.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python (conda interpreter, project test-run convention) | Test suite | ✓ | 3.12.8 | — |
| sqlite3 (stdlib, bundled SQLite) | `action_queue`, `busy_timeout`, WAL | ✓ | SQLite 3.45.3 | — |
| pytest | Concurrent-load test | ✓ | 9.1.1 (per existing `.pyc` cache tags) | — |
| discord.py `tasks.loop` | `ActionQueueCog` | ✓ | already installed, used by 6+ existing cogs | — |
| Local (non-network) filesystem for `DB_PATH` | WAL correctness | ✓ | `bot.db` is a local file on host "cinema"; pytest `tmp_path` is always local | — |

No missing dependencies. Nothing in this phase requires anything beyond what the project
already has installed and running.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1, Python 3.12.8 |
| Config file | none detected (`pytest.ini`/`pyproject.toml` has no `[tool.pytest]` section) — invoked directly against the `tests/` package |
| Quick run command | `"C:\Users\Shangri\miniconda3\python.exe" -m pytest tests/test_action_queue.py tests/test_action_queue_cog.py tests/test_app_actions.py -x` |
| Full suite command | `"C:\Users\Shangri\miniconda3\python.exe" -m pytest` |

**Note (project memory):** always use the conda Python
(`C:\Users\Shangri\miniconda3\python.exe -m pytest`) — PowerShell's `Python314` has no
pytest installed.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|--------------------|-------------|
| INFRA-01 | `enqueue`/`claim_next`/`complete`/`fail`/`retry`/`recover_stale_claims` DB contract | unit | `pytest tests/test_action_queue.py -x` | ❌ Wave 0 |
| INFRA-01 | Purge-on-write never deletes a `pending`/`claimed` row (Pitfall 1) | unit | `pytest tests/test_action_queue.py::test_purge_never_deletes_pending -x` | ❌ Wave 0 |
| INFRA-01 | Stale-claim recovery requeues an orphaned `claimed` row (D-08) | unit | `pytest tests/test_action_queue.py::test_recover_stale_claims_requeues_orphan -x` | ❌ Wave 0 |
| INFRA-01 | `ActionQueueCog` tick: claim → dispatch → complete, and claim → dispatch → fail → auto-retry → eventual `failed` | unit | `pytest tests/test_action_queue_cog.py -x` | ❌ Wave 0 |
| INFRA-01 | Enqueue/status/retry FastAPI routes require Manager tier; unknown `kind` rejected 422; retry only from `failed` | integration | `pytest tests/test_app_actions.py -x` | ❌ Wave 0 |
| INFRA-01 | Bot-offline state surfaces correctly (pending + `bot_online=False` reuses `_bot_online()`) | integration | `pytest tests/test_app_actions.py::test_status_reports_bot_offline -x` | ❌ Wave 0 |
| INFRA-02 | `busy_timeout` PRAGMA present on every connection | unit | `pytest tests/test_db_pragmas.py -x` (or fold into existing `test_settings.py` CONC-01 area) | ❌ Wave 0 |
| INFRA-02 | Concurrent-load test: simulated bot loop + panel burst, zero unhandled `database is locked` | integration/load | `pytest tests/test_action_queue_concurrency.py -v` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_action_queue.py tests/test_action_queue_cog.py -x` (fast, sub-second per test)
- **Per wave merge:** `pytest tests/test_action_queue_concurrency.py tests/test_app_actions.py -x` (the concurrency test runs several seconds by design — it needs real contention time)
- **Phase gate:** Full suite green (`pytest`, no `-k`/`-m` filter) before `/gsd:verify-work`, with `test_action_queue_concurrency.py` treated as the literal go/no-go gate for INFRA-02 (D-12)

### Wave 0 Gaps

- [ ] `tests/test_action_queue.py` — covers INFRA-01's DB-layer contract, including the Pitfall-1 purge-scoping test and the Pitfall-2 stale-claim-threshold test
- [ ] `tests/test_action_queue_cog.py` — covers the `ActionQueueCog` dispatch loop, tested via the extracted-logic pattern (Pitfall 5), not the raw `tasks.loop` wrapper
- [ ] `tests/test_app_actions.py` — covers the two/three new FastAPI routes: manager-gating, kind allowlisting, retry-only-from-failed
- [ ] `tests/test_action_queue_concurrency.py` — the D-12 go/no-go gate itself
- [ ] Optional: a shared `_use_tmp_db(monkeypatch, tmp_path)` fixture in `conftest.py` — currently duplicated per-test-file (`test_discord_names.py`, `test_settings.py`); not required for this phase but a low-cost cleanup opportunity since three more test files are about to duplicate it a fourth/fifth/sixth time
- [ ] Framework install: none — pytest and all dependencies are already present

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | no | Unchanged — existing Discord OAuth session, no new auth surface |
| V3 Session Management | no | Unchanged — identity resolved via `request.session` only, same as every existing route |
| V4 Access Control | yes | `Depends(require_manager)` on all three new routes (enqueue/status/retry) — owner OR Manager only, reusing the Phase-3 `require_manager` choke point verbatim |
| V5 Input Validation | yes | `kind` MUST be checked against an explicit allowlist (`_ALLOWED_KINDS`) at the API boundary before `enqueue()` — never accept an arbitrary string as `kind` from the request body, even though the dispatch registry would safely no-op an unknown kind (fail-fast with a clean 422 instead of a fail-then-purge round trip) |
| V6 Cryptography | no | No new crypto; the queue carries no secrets (payloads are action parameters like message/thread ids, never tokens) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Arbitrary `kind` string injection | Tampering | Explicit allowlist check at the route boundary (V5 above); parameterized SQL means `kind` can never affect the query shape regardless |
| A Manager reading/retrying another Manager's action by guessing its numeric id | Information Disclosure (mild) | **Intentionally not scoped per-user** — D-09 designs `action_queue` as ONE SHARED table all Managers act on together (same trust tier); this is a deliberate design choice, not a gap, consistent with "Manager" being a single flat trust tier in this project (no per-Manager data partitioning exists anywhere else in the app either) |
| Queue-flooding via rapid repeated enqueue calls (self-inflicted DoS) | Denial of Service | No rate limiting exists anywhere in this app today (consistent scope — internal single-guild staff tool, small trusted user set); accepted risk, matches the project's existing security posture rather than introducing a new gap specific to this phase |
| Reintroducing a Discord write-credential into the FastAPI app to "shortcut" the queue | Elevation of Privilege | Explicitly NOT done — the app only ever writes/reads `action_queue` rows; all Discord/GitHub side effects stay bot-process-only (PITFALLS.md Pitfall 4/Anti-Pattern 1, unchanged by this phase) |

## Sources

### Primary (HIGH confidence)

- This repository, read directly this session: `core/db.py` (full file — `_get_conn`,
  every existing `init_*`/upsert idiom), `app/deps.py` (`require_manager`,
  `_resolve_roles`, `TierForbidden` — already built in Phase 3), `app/main.py` (dashboard
  routes, `_bot_online`/`_HEARTBEAT_STALE_SECONDS`, `api_overview_status`, lifespan init
  block), `cogs/heartbeat.py`, `cogs/discord_names.py` (the two closest `tasks.loop`
  precedents), `tests/test_discord_names.py`, `tests/test_discord_names_cog.py`,
  `tests/test_settings.py` (the existing CONC-01 WAL concurrency test — direct precedent
  for the D-12 test's shape), `tests/conftest.py`, `bot.py` (extension-loading list),
  `config.py` (`DB_PATH`).
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-CONTEXT.md` —
  authoritative locked decisions (D-01 through D-12).
- `.planning/research/ARCHITECTURE.md` — the milestone-level `action_queue` blueprint
  this research extends into concrete SQL/code.
- `.planning/research/PITFALLS.md` — Pitfall 3 (sqlite writer/writer contention, the
  direct basis for INFRA-02's design) and its own cited sources (SQLite forum, Bert
  Hubert article) for the busy_timeout/retry guidance.
- Verified directly in this session: `C:\Users\Shangri\miniconda3\python.exe -c
  "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version)"` →
  Python 3.12.8 / SQLite 3.45.3.

### Secondary (MEDIUM confidence)

- Python stdlib docs behavior (`sqlite3.connect(..., timeout=5.0)` default) — corroborated
  by PITFALLS.md's own claim, not independently re-fetched from docs.python.org in this
  session (training-data-level confidence on a very stable, unchanged stdlib default).

### Tertiary (LOW confidence)

None — every recommendation in this document is either read directly from this
repository's own code/tests or grounded in the milestone research's already-cited external
sources. No new unverified external claims were introduced.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, every tool already installed and version-verified in this session
- Architecture: HIGH — every pattern extends a precedent read directly from this repository's own shipped code (heartbeat, discord_names, settings, activity_log)
- Pitfalls: HIGH — Pitfalls 1/2/3 are novel-to-this-phase design risks reasoned directly from the concrete schema/protocol this research proposes (not speculative); Pitfall 4 is directly inherited from the milestone's own HIGH-confidence PITFALLS.md Pitfall 3

**Research date:** 2026-07-22
**Valid until:** No external-ecosystem expiry risk (stdlib-only); re-validate the numeric assumptions (A1-A5) once the D-12 load test runs and once Phase 6-9 real dispatch handlers exist, not on a calendar basis
