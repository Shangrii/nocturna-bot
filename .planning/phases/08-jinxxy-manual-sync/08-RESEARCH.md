# Phase 8: Jinxxy Manual Sync - Research

**Researched:** 2026-07-24
**Domain:** Cross-process overlap guard (asyncio.Lock + DB mirror) for a Discord bot's existing
sync orchestration, exposed through the already-shipped `action_queue` infrastructure to a FastAPI
dashboard.
**Confidence:** HIGH — every claim below is grounded in a direct read of this repository's own
code (`cogs/jinxxy.py`, `core/action_queue.py`, `cogs/action_queue_worker.py`, `core/db.py`,
`app/main.py`, `app/routers/gallery.py`, `app/deps.py`, `app/auth.py`, `app/templates/overview.html`,
`app/templates/gallery.html`, `tests/test_jinxxy_cog.py`, `tests/test_action_queue_concurrency.py`,
`tests/test_action_queue_cog.py`, `tests/test_app_actions.py`). This is a wrap-existing-code phase,
not a new-library phase, so there is no third-party ecosystem to verify against a registry.

## Summary

Phase 8 adds exactly one new `action_queue` `kind` (`jinxxy_sync`) plus a widened
`jinxxy_sync_status` mirror row on top of code that already exists and already works:
`JinxxyCog._run_sync` (the single sync orchestration), `_record_sync_status` (the status/activity
write point), `ActionQueueCog._dispatch` (the kind→handler table), and the shipped
`POST /api/actions` / `GET /api/actions/{id}` Manager-gated routes. **None of this needs to be
built from scratch — it needs to be extended in four narrow places.**

The one genuinely new piece of engineering is the overlap guard itself. Today `JinxxyCog` has
**no lock of any kind** — `_run_sync` is a bare, unguarded coroutine, and `_poll`/`/tienda sync`
both call it directly with no mutual exclusion (verified by reading the full file: no
`asyncio.Lock`, no busy flag, nothing). This confirms CONTEXT.md's premise exactly: the guard is
the phase's real content, not incidental plumbing. The codebase already contains one directly
reusable precedent for this exact shape: `core/github_publish.py` module-level
`_commit_lock = asyncio.Lock()`, with a docstring note that "uncontended acquires take the fast
path and never bind a loop, so this is also safe across the test suite's `asyncio.run` calls" —
this is the pattern to follow for `JinxxyCog`'s own lock, and directly de-risks the "prove it under
test" success criterion using the repo's existing no-`pytest-asyncio` test idiom.

`jinxxy_sync_status` today stores only `last_run_utc/ok/product_count/error` — it has **no**
`running`, `started_at`, `source`, or added/updated/removed-count columns. Every one of these must
be added via the `ALTER TABLE ... ADD COLUMN` try/except idiom already used twice in this file (for
`forum_posts` and `reminders`) — `CREATE TABLE IF NOT EXISTS` alone is a no-op against an existing
table and will NOT add these columns in a deployed DB.

One real gap surfaced that CONTEXT.md's canonical refs do not resolve: **there is no existing
mechanism to resolve a Manager's Discord display name server-side.** The session (`app/auth.py`)
stores only `discord_id` (+ `slug` for editors) by deliberate design ("never a tier... D-02"); the
`discord_names` cache (Phase 4) only covers channels and roles, never guild members. D-12's
"(Nombre)" attribution and D-07's "desde el panel (Name)" source label both need a name from
somewhere. See Open Questions for the recommended fix (trivial: persist the already-computed
`username` into the session at login — zero new bot-side moving parts).

**Primary recommendation:** Widen `jinxxy_sync_status` via the ADD-COLUMN idiom, add one
`asyncio.Lock` (module- or cog-level, following `github_publish._commit_lock`'s exact shape) inside
`JinxxyCog`, wrap `_run_sync` with lock-acquire + mirror-write, add a `locked()` fast-path check in
both `_poll` and one new `_dispatch["jinxxy_sync"]` handler, and reuse every existing
Alpine/CSS/route convention already shipped for Overview/Gallery — no new frontend pattern is
needed anywhere in this phase.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Sync orchestration (enumerate/merge/commit) | Bot process (Discord cog) | — | `JinxxyCog._run_sync` already owns this; app has no Jinxxy/GitHub credentials (locked) |
| Overlap guard (mutual exclusion) | Bot process (in-memory `asyncio.Lock`) | Database (mirror, read-only for guard purposes) | Both triggers (`_poll`, queue dispatch) run in the SAME process/event loop — an in-process lock is a real mutex here, unlike a cross-process scenario |
| In-flight / last-run status display | Database (`jinxxy_sync_status` mirror) | FastAPI app (read + serve) | App cannot see bot-process memory; the mirror is the only channel |
| Trigger enqueue (Manager click) | FastAPI app (POST route) | Database (`action_queue` insert) | App enqueues; app never executes the sync itself |
| Trigger dispatch (claim + invoke) | Bot process (`ActionQueueCog._dispatch`) | — | Same one-action-per-tick serialization as Phase 7's gallery/reviews kinds |
| Read-only product catalog display | Database (`store_snapshot`) | FastAPI app (read + serve) | Sync-owned fields only; no credentials needed to read a local sqlite table |
| Manager display-name resolution (D-07/D-12) | FastAPI app (session) — **gap, no current owner** | — | Neither app nor bot currently resolves a Discord user id → display name; recommend fixing in the app (session), not the bot (see Open Questions) |

## Standard Stack

This phase adds **zero new third-party packages** to either the bot or the app. It is a
composition of already-installed, already-imported libraries only. No `pip install` step, no
version research, no registry lookup applies.

### Core (already installed, reused verbatim)
| Library | Purpose in this phase | Why no alternative needed |
|---------|------------------------|----------------------------|
| `asyncio` (stdlib) | The overlap guard's `Lock` | Single-process, single-event-loop guard — a stdlib primitive is both correct and the established pattern (`github_publish._commit_lock`) |
| `sqlite3` (stdlib, via `core/db.py`) | Widened `jinxxy_sync_status` mirror + read side | Already the only bot↔app channel (locked project decision) |
| `discord.py` `tasks.loop` | Unchanged `_poll` cadence | Out of scope — poll cadence/logic is explicitly unchanged |
| FastAPI + Jinja2 + Alpine.js (vendored) | `/jinxxy` page, `/api/actions` reuse | Already shipped; no new frontend dependency (confirmed by UI-SPEC's Registry Safety section: "zero third-party frontend dependencies") |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.Lock` in-process guard | A DB-backed "claimed" row as the authoritative lock | Rejected by CONTEXT.md D-02 — a DB row is not a real mutex for two coroutines racing inside the SAME process/event loop, and a crash mid-write could leave it stuck with no natural unlock; the lock is strictly simpler and correct-by-construction here |
| `asyncio.Lock` | `asyncio.Semaphore(1)` | No behavioral difference at concurrency=1; `Lock` is the idiomatic and already-precedented choice (`github_publish._commit_lock`) |

## Package Legitimacy Audit

**Not applicable — this phase installs zero external packages.** No `pip install`/`npm install`
step exists anywhere in the CONTEXT.md decisions, the UI-SPEC (which explicitly states "this phase
adds zero third-party frontend dependencies"), or the reusable-asset list above. The slopcheck /
registry-verification gate is skipped per its own "Required whenever this phase installs external
packages" condition — none are installed.

## Architecture Patterns

### System Architecture Diagram

```
Manager clicks "Sincronizar catálogo" (browser, /jinxxy page)
        │
        ▼
POST /jinxxy/sync (new, Manager-gated FastAPI route)
        │  1. Dedupe check: SELECT ... FROM action_queue
        │     WHERE kind='jinxxy_sync' AND status IN ('pending','claimed')
        │     → found? return THAT id (D-04)
        │     → not found? action_queue.enqueue('jinxxy_sync', {source:'panel', ...}, requested_by)
        ▼
action_queue table (shared sqlite, WAL + busy_timeout)
        │
        │  bot process, ActionQueueCog._tick (1.5s loop, unchanged)
        ▼
ActionQueueCog._dispatch['jinxxy_sync'](payload)
        │  1. Resolve JinxxyCog from bot.get_cog(...)
        │  2. jinxxy_cog._run_sync_guarded(source=...)   <- NEW wrapper
        │        │
        │        ├─ lock.locked()? → return {"already": True}  (D-01, benign success)
        │        └─ else: async with lock:
        │               mirror: running=1, started_at=now, source=... (D-02/D-07)
        │               result = await self._run_sync()      <- UNCHANGED orchestration
        │               mirror: running=0 (widened jinxxy_sync_status: counts, D-09)
        │               await self._announce(result)          <- UNCHANGED (D-11)
        │  3. action_queue.complete(id, result)  <- counts land here too (D-09)
        ▼
jinxxy_sync_status (widened mirror row) + activity_log (D-12 attribution)
        │
        │  FastAPI app, GET /jinxxy + GET /jinxxy/status (or reuse /api/actions/{id})
        ▼
Browser Alpine app: own-action poll (1.5s, resolves click's own result)
                    + ambient mirror poll (30s, reuses overview.html's cadence,
                      shows busy state for POLL- or DISCORD-triggered syncs too)
                    + client-side elapsed tick (1s, cosmetic only)

Meanwhile, unattended:
_poll (tasks.loop, JINXXY_POLL_HOURS, UNCHANGED cadence)
        │
        ▼
jinxxy_cog._run_sync_guarded(source='scheduled')
        │  same lock/mirror wrapper — same fast-path skip-and-log if the panel/Discord
        │  is mid-sync (D-03, no announce, no error)
```

### Recommended Code Structure (files touched, not new files — this is a wrap, not a build)
```
cogs/jinxxy.py               # + asyncio.Lock, _run_sync_guarded(source), mirror writes,
                              #   lock clear in __init__ (D-06), _poll calls guarded wrapper
cogs/action_queue_worker.py  # + one dict entry: "jinxxy_sync": self._handle_jinxxy_sync
core/db.py                   # widen jinxxy_sync_status (ADD COLUMN idiom): running,
                              #   started_at, source, added_count, updated_count, removed_count
app/main.py or               # replace _module_stub_page for "jinxxy" with a real route +
app/routers/jinxxy.py        #   POST enqueue route with D-04 dedupe query
app/templates/jinxxy.html    # new template: status card + Sync button + product table
                              #   (composes overview.html's actionProofApp + gallery.html's
                              #    row.already idiom — see Code Examples)
app/static/dashboard.css     # no new tokens; at most 2-3 narrow class names (per UI-SPEC)
```

### Pattern 1: In-process asyncio.Lock as the authoritative guard, DB row as mirror-only
**What:** A single `asyncio.Lock` lives on the `JinxxyCog` instance (or module-level, matching
`github_publish._commit_lock`'s placement). Every entry point funnels through one guarded method
that checks `.locked()` for a non-blocking fast path BEFORE attempting to acquire, so a
already-running sync returns immediately rather than queuing behind the lock.
**When to use:** Exactly this shape — single process, single event loop, multiple call sites that
must never run concurrently, where "return a benign status" beats "block until free" (D-01's
mechanical reason: blocking would park the single `ActionQueueCog` dispatch slot for the sync's
whole multi-minute duration).
**Example (repo precedent, `core/github_publish.py`):**
```python
# Source: core/github_publish.py (already shipped, lines ~70)
# Serializes the whole read-modify-commit so concurrent publishes don't race the ref.
# The single-process bot uses one event loop; uncontended acquires take the fast path
# and never bind a loop, so this is also safe across the test suite's asyncio.run calls.
_commit_lock = asyncio.Lock()
```
The Phase 8 guard should mirror this exactly but ADD a `.locked()` pre-check (D-01 needs the
non-acquiring fast path; `_commit_lock`'s existing usage always blocks-and-waits, which is why it's
a callable precedent for the *shape* but not verbatim for the *non-blocking* return behavior):
```python
# NEW shape for JinxxyCog — sketch, not verbatim repo code
class JinxxyCog(...):
    def __init__(self, bot):
        ...
        self._sync_lock = asyncio.Lock()
        # D-06: the in-process lock is gone at startup, so the mirror's `running`
        # flag can never be true yet — clear it defensively (same idiom as
        # db.init_store_state()).
        db.set_jinxxy_sync_status(running=False, ...)  # or a dedicated clear helper

    async def _run_sync_guarded(self, source: str) -> dict:
        if self._sync_lock.locked():
            return {"already": True}  # D-01: benign success, not an error
        async with self._sync_lock:
            db.set_jinxxy_sync_running(True, started_at=..., source=source)  # D-02/D-07
            try:
                result = await self._run_sync()  # UNCHANGED orchestration
            finally:
                db.set_jinxxy_sync_running(False)  # D-02: same span the lock covers
        await self._announce(result)  # D-11, but only from the queue-handler caller —
                                        # _poll already calls _announce itself; don't double-call
        return result
```
**Important nuance for the planner:** `_poll` currently calls `_run_sync()` then `_announce(result)`
itself (two lines). `/tienda sync` does the same. If a shared `_run_sync_guarded` wrapper also
calls `_announce`, the call sites need to stop calling it a second time — decide ONE place
`_announce` is invoked (inside the guarded wrapper, called by all three entry points) to avoid a
double-announce regression. This is a concrete implementation trap worth a dedicated plan-checker
item.

### Pattern 2: DB-mirror widening via `ALTER TABLE ... ADD COLUMN` in try/except
**What:** `jinxxy_sync_status` already exists in deployed databases with only
`id/last_run_utc/ok/product_count/error`. `CREATE TABLE IF NOT EXISTS` is a no-op against an
existing table — it will NOT add new columns.
**When to use:** Any time an existing single-row status/config table needs new columns without a
destructive migration.
**Example (repo precedent, `core/db.py`, used twice already):**
```python
# Source: core/db.py init_reminders() (already shipped)
for col, default in [("paused", "0"), ("version", "1")]:
    try:
        conn.execute(
            f"ALTER TABLE reminders ADD COLUMN {col} "
            f"INTEGER NOT NULL DEFAULT {default}"
        )
    except sqlite3.OperationalError:
        pass  # Ya existe
```
Phase 8's `init_jinxxy_sync_status()` needs the identical idiom for `running` (INTEGER, default 0),
`started_at` (TEXT, nullable), `source` (TEXT, nullable), and the D-09 counts (`added_count`,
`updated_count`, `removed_count`, all INTEGER, nullable) — column names/types are Claude's
Discretion per CONTEXT.md, but the ADD-COLUMN mechanism itself is not discretionary; it is required
by the existing-deployed-DB constraint.

### Pattern 3: Dedupe-at-enqueue query (D-04) — no existing exact precedent, straightforward SQL
**What:** Before inserting a new `action_queue` row for `jinxxy_sync`, check whether one is already
`pending` or `claimed`; if so, return that row's id instead of inserting a duplicate.
**When to use:** Any action kind where a duplicate enqueue during the in-flight window would cause
a redundant expensive operation (here: a full Jinxxy enumeration + GitHub commit) that the
in-process lock (Pattern 1) would NOT catch, because the duplicate row dispatches AFTER the first
one releases the lock, not during it.
**No existing repo function does this today** — Phase 7's gallery/reviews `_enqueue_gallery_action`
(see `app/routers/gallery.py`) enqueues unconditionally on every click (acceptable there because
approve/remove are idempotent-by-marker-check, per Phase 7 D-08/D-11, and cheap to re-run). Phase 8
needs a NEW helper, e.g.:
```python
# NEW — sketch, not verbatim repo code. Add to core/action_queue.py alongside enqueue().
def enqueue_deduped(kind: str, payload: dict, requested_by: str) -> int:
    with db._get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM action_queue WHERE kind = ? AND status IN ('pending', 'claimed') "
            "ORDER BY id LIMIT 1",
            (kind,),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso()),
        )
        return cur.lastrowid
```
Whether this becomes a generic `action_queue.enqueue_deduped(kind, ...)` (reusable by future
single-instance action kinds) or a route-local dedupe query is Claude's Discretion (CONTEXT.md
says so explicitly) — the generic form costs nothing extra and avoids a second bespoke query if a
future phase needs the same shape.

### Anti-Patterns to Avoid
- **Don't make the DB row the authoritative lock.** A `running=1` flag alone is racy across two
  coroutines in the same process (TOCTOU between read-check and write-set) and a crash mid-sync
  leaves it permanently stuck with nothing to clear it except the exact startup-clear + heartbeat-
  staleness combination D-06 specifies. The `asyncio.Lock` must be the real guard.
- **Don't block the queue-handler on lock acquisition.** `await self._sync_lock.acquire()` (waiting)
  would park `ActionQueueCog`'s single dispatch slot for the sync's full duration, per D-01's
  mechanical reasoning — always use the non-blocking `.locked()` pre-check pattern.
- **Don't call `_announce` from more than one place per sync.** See Pattern 1's nuance — a naive
  refactor that leaves `_poll`'s existing `await self._announce(result)` AND adds another call
  inside a shared guarded wrapper will double-post the public embed.
- **Don't let a raw exception string reach the panel.** D-10 requires exception-TYPE-based
  category mapping (`JinxxyAPIError` / `GitHubPublishError` / anything else) BEFORE the string
  reaches `action_queue.fail(id, str(exc))` or the render layer — `str(exc)` from
  `jinxxy_api`/`github_publish` can carry URLs/status codes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Sync orchestration | A second sync code path for the panel trigger | `JinxxyCog._run_sync` (call it from the guarded wrapper) | The whole reason this phase is small — CONTEXT.md locks this: "the sync logic is never reimplemented in the app" |
| Action status polling UI | A new Alpine component from scratch | `overview.html`'s `actionProofApp()` shape + `gallery.html`'s `row.already` idiom | Both patterns already handle pending/claimed/done/failed, bot-offline, and the "already"/moot-success case — copy the shape, don't invent a new state machine |
| Concurrent-write sqlite safety | A custom retry/backoff wrapper for the new DB writes | `core/db.py::_get_conn()` (WAL + `busy_timeout=8000`) + `core/action_queue.py`'s `_retry_on_locked` decorator, if writes go through `action_queue.py` | Already hardened and proven under `tests/test_action_queue_concurrency.py`'s go/no-go gate; a bespoke retry loop would duplicate untested logic |
| Result/error rendering copy | Ad hoc string interpolation of `str(exc)` | D-10's fixed category table (`JinxxyAPIError`→..., `GitHubPublishError`→..., else→generic) | Locked decision; also the established "errors never leak raw" security posture across this whole cog |

**Key insight:** Every piece of "new" functionality in this phase is a thin wrapper or a widened
row around code that already exists and is already tested. The risk surface is almost entirely in
the guard's correctness (Pattern 1) and the widened-table migration (Pattern 2), not in inventing
new architecture.

## Common Pitfalls

### Pitfall 1: Double-announce from a shared guarded wrapper
**What goes wrong:** `_poll` and `/tienda sync` currently each call `_run_sync()` then
`_announce(result)` as two separate statements. If the new guarded wrapper ALSO calls `_announce`
internally, and the call sites aren't updated to remove their own call, a real store change gets
announced twice.
**Why it happens:** Refactoring three call sites (`_poll`, `/tienda sync`, new queue handler) to
share one wrapper is exactly the kind of "should be automatic" step that's easy to half-do.
**How to avoid:** Make `_announce` invocation happen in exactly ONE place — inside the guarded
wrapper — and have `_poll`/`/tienda sync`/the queue handler all call ONLY the wrapper, never
`_run_sync` directly and never `_announce` directly.
**Warning signs:** A test that mocks `_announce` and asserts call count == 1 per sync is the
cheapest way to catch a regression here; add it explicitly to the phase's test plan.

### Pitfall 2: `CREATE TABLE IF NOT EXISTS` silently not widening a deployed table
**What goes wrong:** If the planner writes `init_jinxxy_sync_status()` as a fresh `CREATE TABLE IF
NOT EXISTS` with the new columns included, it works perfectly in a fresh test DB but does NOTHING
in any already-deployed database where the table already exists with the old 5-column shape — the
new columns silently never appear, and every read of `running`/`started_at`/`source`/counts
returns a `KeyError` or `None` inconsistently.
**Why it happens:** `CREATE TABLE IF NOT EXISTS` is idempotent for table EXISTENCE, not for
SCHEMA — SQLite has no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` and this project doesn't use one.
**How to avoid:** Always pair the `CREATE TABLE IF NOT EXISTS` (fresh-DB case) with the
`ALTER TABLE ... ADD COLUMN` in try/except `sqlite3.OperationalError` (existing-DB case) — this
project's own idiom, used for `forum_posts` and `reminders`. Both code paths must ship together.
**Warning signs:** A test that calls `init_jinxxy_sync_status()` twice — once simulating an "old"
5-column table, once fresh — and asserts the new columns are queryable both times.

### Pitfall 3: Testing the overlap guard with `pytest-asyncio` when the repo doesn't use it
**What goes wrong:** `tests/test_jinxxy_cog.py`'s own docstring states the repo drives async code
with `asyncio.run()` directly and `SimpleNamespace`/`AsyncMock` fakes — NOT `pytest-asyncio`. A
plan that assumes `@pytest.mark.asyncio` is available will fail to collect/run (the dependency may
not even be installed) or diverge from the established test idiom, creating an inconsistent test
suite.
**Why it happens:** `pytest-asyncio` is the most common async-testing library in the wider Python
ecosystem, so it's an easy default to reach for without checking this specific repo's convention.
**How to avoid:** Write the overlap-guard test using `asyncio.run(...)` with a driver coroutine
that interleaves two calls to the guarded sync method (e.g., start one as a background `Task`,
`await asyncio.sleep(0)` to yield control, then invoke the second call while the first still holds
the lock) — this is the same style already used across every `test_*_cog.py` file in this repo.
**Warning signs:** `ModuleNotFoundError: pytest_asyncio` or a collection error citing an unknown
`asyncio` marker.

### Pitfall 4: Simulating "the poll is running" without a real long-running sync in tests
**What goes wrong:** A naive test tries to literally run `_run_sync()` (which calls out to
`jinxxy_api`/`github_publish`) and race a second trigger against it — slow, network-dependent, and
non-deterministic under CI.
**Why it happens:** The most literal reading of "prove the guard under test" is to run two real
syncs concurrently.
**How to avoid:** Monkeypatch the innards of `_run_sync` (as `test_jinxxy_cog.py`'s existing `_wire`
fixture already does for `jinxxy_api.get_me`/`list_all_products`/`get_product`,
`github_publish._fetch_store`/`sync_store`) so the mocked `sync_store` coroutine can be made to
`await asyncio.sleep(...)` (or wait on an `asyncio.Event`) for a controlled instant — long enough
for a second concurrent call to observe `.locked() == True`, but with zero real I/O. This is the
standard way to make an async race deterministic and fast.
**Warning signs:** A test that takes more than a few hundred milliseconds, or one that occasionally
flakes — either signals the race isn't being controlled deterministically.

### Pitfall 5: The Manager display-name gap breaking D-07/D-12 silently
**What goes wrong:** If the planner assumes `roles["discord_id"]`-only is enough and just renders
the raw snowflake ID as the "(Nombre)" in the source label / activity line, the copy reads as
"desde el panel (206872198273...)" — technically present but not what D-07/D-12 intend ("a label
for what started it" implies a human-readable name).
**Why it happens:** The session genuinely has no name today (see Open Questions) — it's easy to
wire the id through and call it done since the code compiles and the field is non-null.
**How to avoid:** Resolve this explicitly during planning (see Open Questions #1) — either persist
`username` into the session at login (cheapest, no bot-side change) or accept a documented
`[ASSUMED]`-tagged fallback of showing the raw Discord ID until a future phase adds proper
resolution.
**Warning signs:** A UAT/human-verify checkpoint where the in-flight label or activity line shows a
raw numeric ID instead of a name.

## Code Examples

### Reused verbatim: `.action-proof-status` state machine (Alpine)
```javascript
// Source: app/templates/overview.html actionProofApp() (already shipped)
stateKind() {
  if (this.isPending() && !this.botOnline) return 'offline';
  if (this.isPending()) return 'working';
  if (this.status === 'done') return 'ok';
  if (this.status === 'failed') return 'failed';
  return 'idle';
},
stateMark() {
  const marks = { working: '…', offline: '!' };
  return marks[this.stateKind()] || '';
},
```
Phase 8's Sync button/status card reuses this exact shape (per UI-SPEC's Component Inventory), but
must ALSO derive its busy state from the ambient mirror poll (`jinxxy_sync_status.running`), not
only from `this.actionId`'s own pending/claimed state — see D-05's "busy reflects ANY sync" and the
`gallery.html` `row.already` precedent below for the "moot success" rendering.

### Reused verbatim: the "already" moot-success render (D-01 parity)
```javascript
// Source: app/templates/gallery.html run()/poll() (already shipped, GAL-02 "Ya estaba publicada")
row.already = !!(body.result && body.result.already);
// ...stateKind() still returns 'ok' (green) when status === 'done', regardless of `already` —
// the calm-success rendering is FREE from the existing state machine; only the COPY branches
// on `already` to show "Ya se está sincronizando" vs. the normal counts summary.
```

### DB widening idiom (to copy verbatim, substituting column names)
```python
# Source: core/db.py init_reminders() (already shipped)
for col, default in [("paused", "0"), ("version", "1")]:
    try:
        conn.execute(
            f"ALTER TABLE reminders ADD COLUMN {col} "
            f"INTEGER NOT NULL DEFAULT {default}"
        )
    except sqlite3.OperationalError:
        pass  # Ya existe
```

### Overlap-guard test skeleton (repo idiom: no pytest-asyncio)
```python
# Sketch — matches tests/test_jinxxy_cog.py's asyncio.run + AsyncMock idiom
def test_concurrent_dispatch_during_sync_resolves_as_benign_success(monkeypatch):
    cog = ...  # built via the existing `cog` fixture pattern
    gate = asyncio.Event()

    async def _slow_sync_store(prods, *a, **k):
        await gate.wait()          # controlled, deterministic "still running" window
        return {"committed": True, "commit_sha": "x", "count": len(prods)}
    monkeypatch.setattr(jinxxy.github_publish, "sync_store", AsyncMock(side_effect=_slow_sync_store))

    async def scenario():
        first = asyncio.create_task(cog._run_sync_guarded(source="scheduled"))
        await asyncio.sleep(0)               # let `first` acquire the lock
        second = await cog._run_sync_guarded(source="panel")
        gate.set()
        first_result = await first
        return first_result, second

    first_result, second = asyncio.run(scenario())
    assert second == {"already": True}       # D-01: benign success, never an error
    # + assert github_publish.sync_store was awaited exactly ONCE (no double-sync)
    # + assert the announce mock was awaited exactly ONCE
```

## State of the Art

Not applicable in the usual "old library vs. new library" sense — this phase modifies in-house
code only. The one relevant "current approach" note: this repo's own action-queue infrastructure
(Phase 5) and its Phase-7 queue-riding precedent (gallery/reviews) are themselves only weeks old in
this codebase's history and represent the CURRENT established pattern — there is no older approach
being replaced here.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Column names for the `jinxxy_sync_status` widening (`running`, `started_at`, `source`, `added_count`/`updated_count`/`removed_count`) are illustrative, not fixed — CONTEXT.md explicitly leaves exact names to discretion | Architecture Patterns, Pattern 2 | Low — purely a naming choice, no functional risk either way |
| A2 | The recommended fix for the Manager display-name gap (persist `username` into the session at OAuth callback) has not been confirmed with the user/owner as acceptable — it is a deviation (small) from the session-minimalism note in `app/auth.py`'s docstring ("session stores only discord_id... never a tier") | Open Questions #1 | Medium — if rejected, D-07/D-12 attribution needs a different (heavier) mechanism, e.g. extending the bot-side `discord_names` cache to cover guild members, which is a bigger change than this phase's boundary implies |
| A3 | `asyncio.Lock` module- or cog-level placement (as opposed to some other guard shape) is assumed correct because it matches `github_publish._commit_lock`'s existing precedent — this is a design inference from an analogous but not identical use case (that lock guards commits, not "whole sync run" duration) | Architecture Patterns, Pattern 1 | Low — the underlying reasoning (single process, single event loop, no cross-process concern) applies identically; the analogy is structurally sound |

**If this table is empty:** N/A — see above; all three items are genuine open judgment calls,
not verification failures.

## Open Questions (RESOLVED)

> All three questions were resolved during the Phase 8 planning run (2026-07-24) and are already
> reflected in the plans. Kept here for the reasoning trail — do not re-open during execution.
>
> - **Q1 — RESOLVED (user decision):** persist the OAuth `username` into the session at the
>   callback, exactly as recommended below. The user explicitly signed off on relaxing the
>   session-minimalism note in `app/auth.py`; the alternatives (a member-name cache, or dropping
>   the name) were considered and rejected. Implemented by `08-02-PLAN.md`.
> - **Q2 — RESOLVED (partially against the recommendation):** `source` is inferred as `"panel"`
>   and is NOT a payload field, as recommended. However the payload is NOT empty — it carries
>   `actor_name`, because `_run_once` hands handlers only the payload and there is no other
>   channel from the app to the handler for the display name Q1 requires. Implemented by
>   `08-05-PLAN.md` / `08-06-PLAN.md`.
> - **Q3 — RESOLVED (yes, refactor all three):** `_poll`, `/tienda sync`, and the new queue
>   handler all route through one shared `_run_sync_guarded`, with `_announce` reduced to exactly
>   one call site (grep-enforced, plus a regression test) to avoid the double-announce trap.
>   Implemented by `08-03-PLAN.md`.

1. **How is the Manager's Discord display name resolved for D-07's "desde el panel (Nombre)" and
   D-12's activity-log attribution?**
   - What we know: `action_queue.requested_by` already carries the raw `discord_id` string (set
     from `roles["discord_id"]` in every existing enqueue route). The FastAPI session
     (`app/auth.py`) stores ONLY `discord_id` (+`slug` for editors) — the OAuth `username` is
     computed at login but discarded, never persisted. The bot-side `discord_names` cache
     (Phase 4/SETT-02) resolves channel and role names only, never individual guild members.
   - What's unclear: Whether extending the session to also store `username` (a one-line addition
     at the point `request.session["discord_id"] = user_id` is set in `app/auth.py`) is an
     acceptable deviation from that file's stated "session stores only discord_id... never a tier"
     design note, or whether the intent behind that note was narrowly about NOT caching
     authorization state (tier), in which case adding a display name is unrelated and safe.
   - Recommendation: Add `request.session["username"] = username` alongside the existing
     `discord_id` line in `app/auth.py`'s callback (the value is already computed on the very same
     line, one line above) — this needs zero new bot-side moving parts, zero new DB table, and
     resolves both D-07 and D-12 for the panel-triggered case. For the Discord-triggered case
     (`/tienda sync`), `interaction.user.display_name` is already available in that command's own
     scope and can be passed through `_run_sync_guarded(source=..., actor_name=...)` — no session
     needed there at all. Flag this as a specific line-item for the planner to confirm with the
     user before or during planning, since it touches an already-locked prior-phase design note.

2. **Does the queue-handler's `_dispatch["jinxxy_sync"]` entry need its own payload shape, or is an
   empty payload sufficient?**
   - What we know: CONTEXT.md's Claude's Discretion explicitly allows "the payload may be empty or
     carry only the trigger source." `requested_by` is already a separate column on `action_queue`
     independent of `payload_json`.
   - What's unclear: Whether `source` (for D-07's label) should be inferred from context
     (queue-triggered = "desde el panel" always, since Discord-triggered never goes through the
     queue) or explicitly carried in the payload for future-proofing.
   - Recommendation: Infer `source="panel"` for every queue-dispatched sync (the queue IS the panel
     trigger path by construction — Discord's `/tienda sync` and the scheduled `_poll` never touch
     `action_queue`), so the payload can stay empty. Simpler and needs no payload parsing at all.

3. **Should `_run_sync_guarded`'s single shared "call `_announce` here" placement replace the two
   existing standalone `_announce` call sites in `_poll` and `/tienda sync`, or should those two
   command paths stay as-is and only the NEW queue handler gets a guard?**
   - What we know: D-01/D-02/D-03/D-05 all describe the guard as covering "the whole `_run_sync`
     body" for ALL three entry points (poll, Discord command, panel) — not just the new one.
   - What's unclear: Whether refactoring `_poll` and `/tienda sync` to route through the same
     guarded wrapper (rather than adding a THIRD, separate lock-check only in the queue handler) is
     what CONTEXT.md intends. Re-reading D-02 ("Both `_poll` and the new queue handler funnel
     through the single `_run_sync` entry point... so a non-blocking `locked()` check is correct by
     construction") — this confirms ALL entry points must route through the guard, including
     `/tienda sync`, even though the roadmap's success criteria only mention "the periodic poll"
     and "the panel."
   - Recommendation: Refactor all three entry points (`_poll`, `/tienda sync`, the new queue
     handler) to call the same guarded wrapper — this is the only way D-03 (poll skip-and-log while
     panel syncs) and D-08 (poll's startup tick absorbing a queued dispatch) actually hold, and it
     is explicitly what D-02's binding language describes.

## Environment Availability

Skipped — this phase has no new external tool/service/runtime dependency. It reuses the same
Python interpreter, sqlite file, Discord bot process, and FastAPI app process already running for
Phases 3-7. No new CLI, database, or network service is introduced.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (no `pytest-asyncio` — async tests use `asyncio.run()` directly, per this repo's established idiom in every `test_*_cog.py` file) |
| Config file | none — no `pytest.ini`/`pyproject.toml`/`setup.cfg` found; `tests/conftest.py` only adds the repo root to `sys.path` |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_jinxxy_cog.py -v` (per project MEMORY: use the conda python, not PowerShell's Python314 which has no pytest) |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JINX-01 (SC1: trigger + status/spinner) | Manager POST enqueues `jinxxy_sync`; status endpoint reflects pending/running/done | integration | `pytest tests/test_app_jinxxy.py -x` | ❌ Wave 0 (new file, follows `test_app_actions.py`/`test_app_gallery.py` shape) |
| JINX-01 (SC1: last-sync display, D-09 counts) | Widened `jinxxy_sync_status` round-trips added/updated/removed counts | unit | `pytest tests/test_db_jinxxy_status.py -x` or add cases to an existing db test file | ❌ Wave 0 |
| JINX-01 (SC1: never-synced empty state D-15) | No `jinxxy_sync_status` row + empty `store_snapshot` → app renders the D-15 empty copy | integration | `pytest tests/test_app_jinxxy.py::test_never_synced_empty_state -x` | ❌ Wave 0 |
| JINX-01 (SC2: overlap guard, THE core requirement) | A `jinxxy_sync` dispatch arriving while `_run_sync` holds the lock produces exactly ONE `sync_store` call, ONE announce, and resolves as `{"already": True}` (success, not failure) | unit (async race, deterministic via `asyncio.Event`) | `pytest tests/test_jinxxy_cog.py -k overlap -v` | ❌ Wave 0 (extend existing file — fixtures/mocks already present) |
| JINX-01 (SC2: reverse collision, D-03) | The poll's tick firing while a manual sync runs skips silently (no sync, no announce, only a log line) | unit | `pytest tests/test_jinxxy_cog.py -k poll_skips -v` | ❌ Wave 0 |
| D-04 (dedupe at enqueue) | A second POST while one `jinxxy_sync` is `pending`/`claimed` returns the SAME action id, no second row | integration | `pytest tests/test_app_jinxxy.py::test_dedupe_at_enqueue -x` | ❌ Wave 0 |
| D-06 (stuck-mirror recovery) | `JinxxyCog.__init__` clears `running` on boot; app voids the mirror when `bot_heartbeat` is stale | unit + integration | `pytest tests/test_jinxxy_cog.py -k startup_clear` / `test_app_jinxxy.py -k stale_heartbeat` | ❌ Wave 0 |
| D-10 (error category mapping) | `JinxxyAPIError`/`GitHubPublishError`/generic each map to their exact bilingual category, never raw `str(exc)` | unit | `pytest tests/test_jinxxy_cog.py -k error_category -v` | ❌ Wave 0 |
| D-13/D-14 (product table) | `/jinxxy` renders `store_snapshot` rows with the locked column set, no image/description/editor implied | integration | `pytest tests/test_app_jinxxy.py::test_product_table_columns -x` | ❌ Wave 0 |
| INFRA-02 (unchanged, regression only) | The new write paths (dedupe query + widened mirror writes) don't reintroduce "database is locked" under the existing concurrency harness | integration | `pytest tests/test_action_queue_concurrency.py -v` (existing file — rerun as regression, extend only if the dedupe query needs its own concurrency case) | ✅ exists |

### Sampling Rate
- **Per task commit:** `pytest tests/test_jinxxy_cog.py tests/test_action_queue_cog.py -v` (fast,
  no network, matches this phase's touched files)
- **Per wave merge:** `pytest -v` (full suite — this phase touches shared infrastructure files
  `core/db.py` and `cogs/action_queue_worker.py` that other modules' tests also exercise)
- **Phase gate:** Full suite green, PLUS the overlap-guard test explicitly demonstrating exactly
  one `sync_store`/`_announce` call under the concurrent-dispatch scenario, before
  `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_app_jinxxy.py` — new file, covers the `/jinxxy` route + POST enqueue + dedupe +
      empty states; follow `tests/test_app_gallery.py`'s session-signing fixture pattern
      (`_set_session`/`_manager_override`)
- [ ] Extend `tests/test_jinxxy_cog.py` — add the guarded-wrapper, overlap-race, reverse-collision,
      startup-clear, and error-category test cases; the file's existing `cog`/`_wire` fixtures are
      directly reusable
- [ ] Extend `core/db.py`'s existing DB test coverage (whichever file currently exercises
      `jinxxy_sync_status` — verify via `grep -r jinxxy_sync_status tests/` during planning) with
      round-trip cases for the widened columns AND a "simulate pre-existing 5-column table, then
      call `init_jinxxy_sync_status()`, assert new columns queryable" migration-safety case
      (Pitfall 2)
- [ ] No new framework/config install needed — pytest is already the project's only test runner

## Security Domain

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | no (session-cookie auth already covers this route via the existing `require_manager` dependency) | — |
| V3 Session Management | yes, indirectly (Open Question #1's `username` persistence) | If `username` is added to the session, it must be the SAME OAuth-verified value already used elsewhere (`user.get("username")`) — never trust a client-supplied name; already satisfied by reusing the existing `_fetch_user(token)` result at the same callback point |
| V4 Access Control | yes | `require_manager` FastAPI dependency (already shipped, unchanged) gates every new route exactly like Gallery/Reviews/Reminders |
| V5 Input Validation | yes (minimal — this phase's only user input is a parameterless button click) | The POST route takes no body fields to validate; the dedupe query and enqueue call use parameterized SQL only (`?` placeholders), following this repo's existing `T-08-03` convention |
| V6 Cryptography | no | Not applicable — no secrets, tokens, or crypto operations in this phase |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Raw third-party exception strings leaking API URLs/status codes into a Manager-visible UI | Information Disclosure | D-10's exception-type→category mapping (already specified) — `str(exc)` never rendered, only logged |
| SQL injection via dynamic column/table names in the ADD-COLUMN migration | Tampering | Column names are hardcoded string literals in the migration code (never user input) — matches the existing `forum_posts`/`reminders` precedent exactly; no interpolation of any request-derived value |
| A Manager-gated route accidentally left un-gated (missing `Depends(require_manager)`) | Elevation of Privilege | Every new route must carry `Depends(require_manager)` exactly like every existing operational-module route (`gallery.py`, `reviews.py`, `reminders.py`); the plan-checker should grep for the decorator on the new route(s) |
| Session-stored display name (Open Question #1) accepting a spoofed value | Spoofing | If implemented, the value MUST come from the same OAuth-token-verified `_fetch_user(token)` call already in `app/auth.py` — never accept a `?display_name=` query param or similar client-controlled input |

## Sources

### Primary (HIGH confidence — direct reads of this repository's own code)
- `cogs/jinxxy.py` — full file read; confirmed NO existing lock/guard of any kind
- `core/action_queue.py` — full file read; `enqueue`/`claim_next`/`complete`/`fail`/`retry`/
  `get_status`, `_retry_on_locked`, `_STALE_CLAIM_SECONDS`
- `cogs/action_queue_worker.py` — full file read; `_dispatch` table, `_tick` 1.5s loop, `_run_once`
  claim→dispatch→complete/fail lifecycle
- `core/db.py` (relevant sections) — `_get_conn` (WAL + busy_timeout=8000), `init_jinxxy_sync_status`
  / `set_jinxxy_sync_status` / `get_jinxxy_sync_status` (current 5-column shape), `init_store_state`
  / `get_store_snapshot` / `upsert_store_snapshot` / `delete_store_snapshot`, `init_activity_log` /
  `log_activity`, `init_heartbeat` / `set_heartbeat` / `get_heartbeat`, `init_action_queue`, the
  `forum_posts`/`reminders` ADD-COLUMN idioms
- `app/main.py` (relevant sections) — `_MODULE_SECTIONS`, `_dashboard_asset_v`, `_compute_online`,
  `_build_overview_status`, `_read_overview_status`, `_module_stub_page`, `/jinxxy` route (current
  stub), `/api/actions` POST/GET/retry routes, `_ALLOWED_KINDS`
- `app/routers/gallery.py` — full file read; Manager-gated enqueue route precedent
  (`_enqueue_gallery_action`)
- `app/deps.py` (relevant sections) — `require_manager`/`_resolve_roles`/`TierForbidden`,
  confirmed `roles` dict shape (`discord_id`/`is_owner`/`is_manager`/`is_editor`, no name)
- `app/auth.py` (relevant sections) — OAuth callback; confirmed `username` is computed but never
  persisted to the session
- `cogs/discord_names.py` — confirmed the cache covers `channel`/`role` kinds only, never members
- `core/jinxxy_api.py` / `core/github_publish.py` (relevant sections) — `JinxxyAPIError`,
  `GitHubPublishError`, and the existing `_commit_lock = asyncio.Lock()` precedent
- `core/store_sync.py` (relevant sections) — `reconcile_store` return shape
  (`products`/`added`/`updated`/`removed`/`changed`)
- `app/templates/overview.html` — full file read; `actionProofApp()` state machine, 30s poll
  cadence precedent
- `app/templates/gallery.html` (relevant sections) — `row.already` moot-success rendering pattern
- `tests/test_jinxxy_cog.py` (relevant sections) — confirmed the repo's `asyncio.run()` +
  `AsyncMock` test idiom (no `pytest-asyncio`), existing `_wire`/`cog` fixtures
- `tests/test_action_queue_concurrency.py` — full file read; the existing INFRA-02 go/no-go
  concurrency gate (distinct from, and not a substitute for, this phase's overlap-guard test)
- `tests/test_action_queue_cog.py` (relevant sections) — dispatch-handler test pattern precedent
- `tests/test_app_actions.py` (relevant sections) — session-signing test fixture pattern
  (`_set_session`, `_manager_override`)
- `.planning/phases/08-jinxxy-manual-sync/08-CONTEXT.md` — all locked decisions D-01 through D-17
- `.planning/phases/08-jinxxy-manual-sync/08-UI-SPEC.md` — approved design contract
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md` — requirement JINX-01,
  phase success criteria, project-level locked decisions

### Secondary (MEDIUM confidence)
- None — every claim in this research traces to a direct repository read; no external
  ecosystem/library research was needed for a phase that adds zero new dependencies.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no external stack exists to research; every component is already
  installed and read directly.
- Architecture: HIGH — every pattern cited is either the exact existing code or a direct,
  verified-in-repo precedent (`github_publish._commit_lock`, the ADD-COLUMN idiom, the
  `actionProofApp`/`row.already` Alpine shapes).
- Pitfalls: HIGH for the three code-derived pitfalls (double-announce, migration idiom, test
  idiom mismatch) — each is grounded in a specific line of existing code. MEDIUM for the
  display-name gap (Open Question #1) — the gap itself is verified, but the recommended fix is a
  judgment call flagged for user confirmation, not a verified requirement.

**Research date:** 2026-07-24
**Valid until:** Effectively indefinite for the architectural findings (this is the project's own
code, not a third-party library subject to version drift) — but re-verify the `jinxxy_sync_status`
column shape and `_dispatch` table contents immediately before planning if any other phase (4-7)
touched `core/db.py` or `cogs/action_queue_worker.py` after this research date, since STATE.md's
progress tracker was found to be stale relative to the actual codebase during this research pass
(Phases 4-7 show "0 plans" in STATE.md's table but are fully implemented on disk).
