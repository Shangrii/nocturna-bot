# Phase 5: sqlite Hardening + Action Queue Infrastructure - Pattern Map

**Mapped:** 2026-07-22
**Files analyzed:** 9 (2 modify, 7 new)
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `core/db.py` (MODIFY: `_get_conn`, `init_action_queue`) | model/utility | CRUD | `core/db.py` itself (`_get_conn`, `init_heartbeat`/`init_discord_names`, `log_activity` purge) | exact (same file, existing idiom) |
| `core/action_queue.py` (NEW) | service (pure module) | event-driven state machine + CRUD | `core/db.py` upsert/purge idioms (`gallery_state`, `bot_heartbeat`, `jinxxy_sync_status`, `activity_log`) | role-match (generalizes 4 existing idioms into one) |
| `cogs/action_queue_worker.py` (NEW, `ActionQueueCog`) | controller (bot cog) | event-driven / polling | `cogs/heartbeat.py` (single-row upsert + `tasks.loop`) and `cogs/discord_names.py` (threaded write + pure-helper split) | exact (idiom identical, tick interval differs) |
| `app/main.py` (MODIFY: +3 routes, +lifespan init) | route/controller | request-response | `app/main.py::api_overview_status` (manager-gated GET+JSON) and `api_presence` (id-keyed GET+JSON) | exact |
| `bot.py` (MODIFY: register extension) | config | — | `bot.py::setup_hook` existing `load_extension` calls | exact |
| `tests/test_action_queue.py` (NEW) | test | CRUD | `tests/test_discord_names.py` | exact |
| `tests/test_action_queue_cog.py` (NEW) | test | event-driven | `tests/test_discord_names_cog.py` | exact |
| `tests/test_app_actions.py` (NEW) | test | request-response | `tests/test_app_dashboard.py` | exact |
| `tests/test_action_queue_concurrency.py` / `test_db_hardening.py` (NEW, D-12 gate) | test | concurrent/load | `tests/test_settings.py::test_wal_mode_active` / `test_wal_concurrent_read_write` | exact |

**Naming note:** the orchestrator's known-files list calls the concurrency test
`tests/test_db_hardening.py`; RESEARCH.md's Validation Architecture table calls it
`tests/test_action_queue_concurrency.py`. Both refer to the same D-12 go/no-go gate — pick one
name at planning time (RESEARCH.md's code example is written against
`tests/test_action_queue_concurrency.py`, so that name requires zero rework of the provided
code). The busy_timeout-presence assertion can either live in a tiny `tests/test_db_hardening.py`
or be folded into `tests/test_settings.py`'s existing CONC-01 section (both are explicitly
sanctioned by RESEARCH.md's Test Map).

## Pattern Assignments

### `core/db.py` (MODIFY — `_get_conn` busy_timeout, `init_action_queue`)

**Analog:** the file's own existing idioms — no external analog needed, this is an additive
change to an already-open file.

**Current `_get_conn()`** (`core/db.py:8-17`):
```python
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # CONC-01: WAL journal mode lets the bot read while the panel writes the same file
    # without "database is locked". WAL is persistent per-database, so this self-heals on
    # whichever process opens the file first; the pragma is non-transactional and applies
    # immediately (the `with conn:` idiom is unaffected). Requires a LOCAL filesystem —
    # WAL does not work over a network share (both processes here run on the same host).
    conn.execute("PRAGMA journal_mode=WAL")
    return conn
```
**Change:** add one line after the WAL pragma (RESEARCH.md Code Examples, INFRA-02 floor):
```python
    conn.execute("PRAGMA busy_timeout=8000")
```

**Single-row upsert idiom to follow for any new helper** — `init_heartbeat`/`set_heartbeat`
(`core/db.py:569-609`), `init_jinxxy_sync_status` (`core/db.py:612-627`), and `gallery_state`
(`core/db.py:64-78`) all share: `CREATE TABLE IF NOT EXISTS` inside `with _get_conn() as conn:`,
called from the owning cog's `__init__` (dual-process defensive init). `init_action_queue`
follows this exact shape — see Pattern 1 in RESEARCH.md for the full `action_queue` DDL
(multi-row + status column, closer in shape to `reminders`, `core/db.py:254-281`, than to the
single-row tables).

**Purge-on-write idiom (D-03) — the ONE idiom that needs a guard, not a verbatim copy**
(`core/db.py::log_activity`, `core/db.py:668-683`):
```python
def log_activity(event_type: str, message: str, keep_last: int = 500):
    """Append one activity row, then purge to the last ``keep_last`` rows (T-03-07)."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO activity_log (event_type, message, created_at) VALUES (?, ?, ?)",
            (event_type, message, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("""
            DELETE FROM activity_log WHERE id NOT IN (
                SELECT id FROM activity_log ORDER BY id DESC LIMIT ?
            )
        """, (keep_last,))
```
**Do NOT copy this verbatim onto `action_queue`.** `activity_log` has no non-terminal state —
every row is immediately final. `action_queue` MUST scope both the inner `SELECT` and outer
`DELETE` to `WHERE status IN ('done','failed')` (RESEARCH.md Pitfall 1) or a still-`pending`
row (e.g. waiting for the bot to reconnect, D-07) gets deleted the moment enough *other*
actions complete. See `_purge_terminal` in Pattern 1 below for the corrected version.

---

### `core/action_queue.py` (NEW — pure module)

**Analog (composite):** `core/db.py`'s `gallery_state`/`bot_heartbeat`/`jinxxy_sync_status`
upsert idioms + `activity_log`'s purge-on-write (corrected per Pitfall 1) + the project's
"pure module, no discord/fastapi import" discipline (matches `core/editors_model.py`,
`core/settings.py` — business logic modules that never import `discord` or `fastapi`).

**Imports pattern** (mirrors `core/db.py:1-5`'s own header):
```python
import json, sqlite3, time, functools
from datetime import datetime, timezone, timedelta
from core import db
```

**Fresh-connection-per-call idiom** (every `core/db.py` helper, e.g. `core/db.py:100-104`
`set_cursor`):
```python
def set_cursor(message_id: int):
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO gallery_state (id, last_processed_message_id) VALUES (1, ?)",
            (message_id,),
        )
```
`action_queue.py`'s `enqueue`/`claim_next`/`complete`/`fail`/`retry`/`recover_stale_claims` all
follow this same `with db._get_conn() as conn:` per-call shape — see RESEARCH.md Pattern 1 for
the complete, ready-to-use implementation (already written against this repo's exact idiom,
including the corrected `_purge_terminal` helper and the `_retry_on_locked` decorator). Use
that code directly; it is not pseudocode.

**Retry/backoff wrapper — NEW pattern, no direct in-repo precedent** (the closest structural
precedent for "a small decorator wrapping a DB call" is `core/db.py`'s bare `with _get_conn()
as conn:` blocks, but none of them retry). RESEARCH.md's `_retry_on_locked` (~15 lines,
`time.sleep` + fixed delays, catches only `sqlite3.OperationalError` whose message contains
"database is locked") is the correct shape — do not reach for `tenacity` (rejected in
RESEARCH.md's Don't-Hand-Roll table, mirrors the project's existing `slowapi` rejection).

**D-11 floor — apply `_retry_on_locked` to exactly these 5 functions** (per CONTEXT.md D-11 and
RESEARCH.md's scope table): `enqueue`, `recover_stale_claims`, `claim_next`, `complete`, `fail`,
`retry`. Existing low-frequency writers (`save_post`, reminders, heartbeat, jinxxy sync) are
LEFT UNCHANGED — `busy_timeout` alone is judged sufficient for them.

---

### `cogs/action_queue_worker.py` (NEW — `ActionQueueCog`)

**Analog:** `cogs/heartbeat.py` (closer match — single always-loaded cog, no optional-deps
try/except, `tasks.loop` + `before_loop`/`cog_unload` idiom) and `cogs/discord_names.py` (for
the pure-helper extraction discipline the tests need, Pitfall 5).

**Full `cogs/heartbeat.py` structure to mirror** (`cogs/heartbeat.py:23-61`):
```python
class HeartbeatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._started_at = datetime.now(timezone.utc).isoformat()
        db.init_heartbeat()                         # dual-process defensive init (Pitfall 6)
        self._beat.start()

    async def cog_unload(self):
        self._beat.cancel()

    @tasks.loop(seconds=45)
    async def _beat(self):
        ...
        try:
            await asyncio.to_thread(db.set_heartbeat, ...)
        except Exception:
            log.exception("heartbeat: no pude escribir el latido")

    @_beat.before_loop
    async def _before_beat(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(HeartbeatCog(bot))
```
`ActionQueueCog` is structurally identical, with two deltas: `@tasks.loop(seconds=1.5)` instead
of `45` (D-04), and the body does claim→dispatch→complete/fail instead of a single upsert — see
RESEARCH.md Pattern 2 for the complete implementation (already written against this exact
skeleton, including the `{kind: handler}` dispatch registry and the `noop` proof action).

**`asyncio.to_thread` around every blocking DB call — non-negotiable at 1.5s tick** (same as
`cogs/discord_names.py:64`):
```python
        try:
            await asyncio.to_thread(db.replace_discord_names, rows)
        except Exception:
            log.exception("discord_names: no pude escribir la caché de nombres")
```

**Pitfall 5 — test the extracted pure logic, not the `tasks.loop`-wrapped method.**
`cogs/discord_names.py` factors its loop body into three top-level pure functions
(`_map_channel_kind`, `_role_hex`, `_snapshot_rows`, `cogs/discord_names.py:15-42`) that
`tests/test_discord_names_cog.py` imports and calls directly — never invoking `_push` itself.
`ActionQueueCog` must do the same: keep `_tick`'s body trivial and delegate to a plain
`async def _run_once(self)` (or call `cog._tick.coro(cog)` per discord.py's documented
one-shot invocation) so `tests/test_action_queue_cog.py` can exercise claim→dispatch→
complete/fail without starting the real scheduler.

**Register in `bot.py::setup_hook`** alongside the other always-loaded cogs (`bot.py:60-61`):
```python
        await self.load_extension("cogs.heartbeat")
        await self.load_extension("cogs.discord_names")
```
Add `await self.load_extension("cogs.action_queue_worker")` in this same always-loaded block
(NOT inside the `cogs.meeting` optional-deps try/except at `bot.py:65-68` — the queue has zero
heavy dependencies, same as heartbeat/discord_names).

---

### `app/main.py` (MODIFY — 3 new routes + lifespan init)

**Analog:** `app/main.py::api_overview_status` (manager-gated, `JSONResponse`, thin) and
`app/main.py::api_presence` (id-keyed lookup, graceful 404/null on missing row).

**Imports already present, reuse as-is** (`app/main.py:43-58`):
```python
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
import config
from app.deps import require_editor, require_manager, require_owner, TierForbidden
from core import db, github_publish, settings
```
Add `from core import action_queue` (or `from core import action_queue, db, ...` folded into
the existing `core` import line) and `import json` if not already imported at module scope.

**Manager-gated GET + JSONResponse idiom** (`app/main.py:664-674`):
```python
@app.get("/api/overview/status")
async def api_overview_status(roles: dict = Depends(require_manager)):
    """Overview's 30s poll target (D-12) — ...
    Reads all three tables via ``run_in_threadpool`` and degrades gracefully on an empty
    database (bot never ran) ... never a 500 (T-03-24 / Pitfall 6).
    """
    return JSONResponse(await _read_overview_status())
```

**Id-keyed public read idiom (404/graceful-null shape) for the status-read endpoint**
(`app/main.py:394-406`):
```python
@app.get("/api/presence/{discord_id}")
async def api_presence(discord_id: str):
    if not discord_id.isdigit() or len(discord_id) > 20:
        return JSONResponse({"status": None})
    row = await run_in_threadpool(db.get_presence, discord_id)
    return JSONResponse({"status": row["status"] if row else None})
```
The new `GET /api/actions/{id}` differs by being **manager-gated** (unlike the public
`api_presence`) and by reusing `_bot_online()` for D-07 — see RESEARCH.md Pattern 3 for the
complete 3-route implementation (`POST /api/actions`, `GET /api/actions/{id}`,
`POST /api/actions/{id}/retry`), already written against these two exact precedents plus
`app/main.py::_bot_online` (`app/main.py:573-577`):
```python
async def _bot_online() -> bool:
    heartbeat = await run_in_threadpool(db.get_heartbeat)
    return _compute_online(heartbeat)
```

**Lifespan dual-process defensive init** (`app/main.py:284-292`):
```python
    try:
        db.init_presence()
        db.init_view_counts()
        db.init_heartbeat()
        db.init_jinxxy_sync_status()
        db.init_activity_log()
        db.init_discord_names()
    except Exception:
        log.exception("no pude inicializar las tablas de presencia/vistas/dashboard")
```
Add `db.init_action_queue()` to this SAME try/except block (not a second init path) — matches
the comment already there: "the three Phase 3 Overview tables join the SAME try/except path as
the pre-existing presence/view_counts init, not a second init path."

**Access control:** all three new routes use `Depends(require_manager)`
(`app/deps.py:174-186`) — the existing owner-or-Manager choke point, no new auth surface:
```python
async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```

---

### `bot.py` (MODIFY — register `ActionQueueCog`)

**Analog:** `bot.py:60-61` (existing always-loaded extension registrations, see above). One
line added to `setup_hook`, no other change.

---

### `tests/test_action_queue.py` (NEW)

**Analog:** `tests/test_discord_names.py` (full file, DB-contract test shape — 96 lines).

**`_use_tmp_db` fixture idiom** (`tests/test_discord_names.py:7-9`, identical in
`tests/test_settings.py:27-29`):
```python
def _use_tmp_db(monkeypatch, tmp_path, name="discord_names.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)
```
Use `name="action_queue.db"`.

**Round-trip test shape** (`tests/test_discord_names.py:33-66`, `test_replace_discord_names_...`):
plain `assert`, no heavy fixtures, `db.init_*()` then call the function under test then read
back via a second helper or raw `with db._get_conn() as conn: conn.execute(...)`.

**Tests to write, per RESEARCH.md's Phase Requirements → Test Map and Pitfalls 1/2/3:**
- `enqueue`/`claim_next`/`complete`/`fail`/`retry`/`recover_stale_claims` round-trip (basic
  contract, mirrors `test_replace_discord_names_round_trips_string_snowflake`)
- `test_purge_never_deletes_pending` — Pitfall 1 regression: insert a `pending` row, complete
  `keep_last + 5` other actions, assert the pending row survives
- `test_recover_stale_claims_requeues_orphan` — D-08: a `claimed` row older than
  `_STALE_CLAIM_SECONDS` gets requeued to `pending`
- A Pitfall-2 test: a handler that "sleeps" past the tick interval but under the stale
  threshold must NOT be reclaimed mid-flight (assert `claim_next()` returns `None` for a
  still-fresh `claimed` row)
- `retry()`'s guard: only mutates/re-enqueues from a `failed` row, returns `None` otherwise
  (Pitfall 3 regression)

---

### `tests/test_action_queue_cog.py` (NEW)

**Analog:** `tests/test_discord_names_cog.py` (full file, 49 lines — the Pitfall-5 "test the
pure helper, not the loop" pattern):
```python
from cogs.discord_names import _map_channel_kind, _role_hex, _snapshot_rows

def test_map_channel_kind(channel_type, expected):
    assert _map_channel_kind(channel_type) == expected
```
`ActionQueueCog`'s tests must import and directly `await` the extracted `_run_once(self)` (or
call `cog._tick.coro(cog)`) rather than starting the real `tasks.loop` — construct a
`SimpleNamespace`/minimal fake bot the same way `test_snapshot_rows_skips_everyone_role` builds
a fake `guild` (`tests/test_discord_names_cog.py:32-45`) rather than a real `discord.Client`.

**Cases to cover:** claim → dispatch(`noop`) → complete; claim → dispatch(`noop`,
`force_fail=True`) → fail → auto-retry (D-06) → eventual `failed` after `_MAX_DISPATCH_ATTEMPTS`;
unknown `kind` → `fail()` with a `ValueError` message, never an unhandled exception escaping the
tick.

---

### `tests/test_app_actions.py` (NEW)

**Analog:** `tests/test_app_dashboard.py` (full file, 207 lines — the `TestClient` +
`app.dependency_overrides[require_manager]` pattern).

**`client` fixture** (`tests/test_app_dashboard.py:42-58`):
```python
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "dashboard.db"), raising=False)
    settings.seed_defaults()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```
Reuse verbatim (rename the tmp db file to `actions.db`), plus `db.init_action_queue()` after
`settings.seed_defaults()`.

**Manager-gate + override idiom** (`tests/test_app_dashboard.py:128-144`):
```python
def test_manager_operational_access_settings_403(client):
    from app.deps import require_manager
    app.dependency_overrides[require_manager] = lambda: {
        "discord_id": "2", "is_owner": False, "is_manager": True, "is_editor": False,
    }
    try:
        ...
    finally:
        app.dependency_overrides.clear()
```

**Tests to write, per RESEARCH.md's Phase Requirements → Test Map:**
- `POST /api/actions` requires manager tier (403 without override, matches
  `test_manager_operational_access_settings_403`'s shape); unknown `kind` → 422
  (`_ALLOWED_KINDS` allowlist, V5)
- `GET /api/actions/{id}` returns `status`/`error`/`result`/`bot_online`; 404 for an unknown id
  (mirrors `api_presence`'s graceful-miss shape but manager-gated, not public)
- `test_status_reports_bot_offline` — seed a stale/absent `bot_heartbeat` row, assert
  `bot_online: false` on a pending action's status read (D-07)
- `POST /api/actions/{id}/retry` — 409 when the target row isn't `failed`; 200 + new `id` when
  it is (D-02, mint-a-fresh-row semantics)

---

### `tests/test_action_queue_concurrency.py` (NEW — D-12 go/no-go gate)

**Analog:** `tests/test_settings.py::test_wal_mode_active` (`tests/test_settings.py:267-272`)
and `test_wal_concurrent_read_write` (`tests/test_settings.py:371-385`) — the existing CONC-01
precedent this test extends into real multi-threaded contention:
```python
def test_wal_concurrent_read_write(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    settings.set("PHOTO_CHANNEL_ID", 1416329356426481717)
    reader = db._get_conn()
    try:
        cur = reader.execute("SELECT key FROM settings")
        cur.fetchone()                                       # hold an open read cursor
        try:
            settings.set("JINXXY_POLL_HOURS", 8)             # write on a second connection
        except sqlite3.OperationalError as exc:
            pytest.fail(f"WAL should permit a concurrent write: {exc}")
    finally:
        reader.close()
```
This existing test only proves reader/writer non-blocking (WAL's actual guarantee); it does
NOT exercise writer/writer contention (Pitfall 4 / PITFALLS.md Pitfall 3), which needs real
concurrent threads. Use RESEARCH.md's complete `test_concurrent_bot_and_panel_writes_never_
raise_database_locked` (Code Examples section) directly — a `ThreadPoolExecutor`-driven panel
burst racing a tight bot-loop thread against the same tmp sqlite file, asserting
`errors == []` and `remaining_pending == 0`. This is the literal D-12 gate; commit it exactly
as RESEARCH.md wrote it (it is not pseudocode).

**Optional companion `tests/test_db_hardening.py`** (busy_timeout presence, if not folded into
`test_settings.py`):
```python
def test_busy_timeout_pragma_active(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    with db._get_conn() as conn:
        value = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert value == 8000
```
(mirrors `test_wal_mode_active`'s exact shape — `PRAGMA <x>` read via a fresh `_get_conn()`).

## Shared Patterns

### Fresh-connection-per-call + dual-process defensive init
**Source:** `core/db.py` (every `init_*`/CRUD helper); called from the owning cog's
`__init__` (`cogs/heartbeat.py:29`, `cogs/discord_names.py:50`) AND from `app/main.py`'s
`lifespan` (`app/main.py:284-290`) — both processes call the same `init_*()` defensively so
neither ever 500s/crashes on a table the other process hasn't created yet.
**Apply to:** `core/db.py::init_action_queue` (called from `ActionQueueCog.__init__` and added
to `app/main.py`'s lifespan try/except block).

### `PRAGMA busy_timeout` + `_retry_on_locked` (INFRA-02)
**Source:** `core/db.py::_get_conn()` (global PRAGMA) + `core/action_queue.py::_retry_on_locked`
(new, scoped decorator).
**Apply to:** `_get_conn()` protects EVERY write path in the app (global, one line). The
decorator applies ONLY to `core/action_queue.py`'s 5 write functions (D-11 floor) — do not wrap
`save_post`/reminders/heartbeat/jinxxy-sync writers, per D-11's explicit scope decision.

### Manager-gated route + `TierForbidden`
**Source:** `app/deps.py::require_manager` (`app/deps.py:174-186`), already wired into 6
existing routes (`app/main.py:606,640,645,650,655,660,665`).
**Apply to:** all 3 new `/api/actions*` routes — no new auth surface, reuse verbatim via
`Depends(require_manager)`.

### `asyncio.to_thread` around every blocking sqlite call in a cog
**Source:** `cogs/heartbeat.py:44-50`, `cogs/discord_names.py:64`.
**Apply to:** every `core.action_queue` call inside `ActionQueueCog._tick`/`_run_once` — at a
1.5s tick this is proportionally more important than heartbeat's 45s cadence (RESEARCH.md
Anti-Pattern 3).

### Purge-on-write with a status guard (D-03, corrected for a non-terminal state)
**Source:** `core/db.py::log_activity` (`core/db.py:668-683`) generalized in
`core/action_queue.py::_purge_terminal` (RESEARCH.md Pattern 1) — the ONLY difference from the
`activity_log` original is the added `WHERE status IN ('done','failed')` clause on both the
inner `SELECT` and outer `DELETE`.
**Apply to:** `complete()` and the terminal branch of `fail()` in `core/action_queue.py` only —
never apply the unguarded `activity_log` version to `action_queue`.

### `_use_tmp_db(monkeypatch, tmp_path)` per-test DB isolation
**Source:** duplicated identically in `tests/test_discord_names.py:7-9`,
`tests/test_settings.py:27-29`, `tests/test_app_dashboard.py` (inline in the `client` fixture).
**Apply to:** `tests/test_action_queue.py`, `tests/test_action_queue_concurrency.py`. (A shared
`conftest.py` fixture would de-duplicate this a 4th/5th/6th time — RESEARCH.md flags this as a
low-cost, optional cleanup, not required for this phase.)

## No Analog Found

None — every file this phase touches has a direct, recently-modified in-repo precedent
(heartbeat/discord_names for the cog+tests, dashboard/settings for the routes+tests). The
retry-on-lock decorator (`_retry_on_locked`) has no structural precedent in this codebase (it
is the phase's one genuinely new code shape), but RESEARCH.md ships it complete and ready to
use — flagged above under `core/action_queue.py`, not a planning gap.

## Metadata

**Analog search scope:** `core/db.py`, `cogs/heartbeat.py`, `cogs/discord_names.py`,
`app/main.py`, `app/deps.py`, `bot.py`, `tests/test_settings.py`, `tests/test_discord_names.py`,
`tests/test_discord_names_cog.py`, `tests/test_app_dashboard.py`, `tests/conftest.py` — all read
directly this session.
**Files scanned:** 11 (all listed above) + directory listings of `app/`, `cogs/`, `core/`,
`tests/` to confirm no closer/newer analog was missed.
**Pattern extraction date:** 2026-07-22
