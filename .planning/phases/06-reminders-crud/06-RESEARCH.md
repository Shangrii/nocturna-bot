# Phase 6: Reminders CRUD - Research

**Researched:** 2026-07-23
**Domain:** FastAPI panel CRUD over an existing discord.py-owned SQLite table, with a
scheduler-vs-panel optimistic-concurrency race guard.
**Confidence:** HIGH — every recommendation below is grounded directly in this repo's existing
code (read in full: `cogs/reminders.py`, `core/db.py`, `app/main.py`, `app/deps.py`,
`app/templates/settings.html`, `app/static/dashboard.css`, `tests/test_reminders_cog.py`,
`tests/test_action_queue_concurrency.py`, `.planning/research/{ARCHITECTURE,PITFALLS}.md`), not
generic ecosystem docs. No external package research was needed — this phase adds zero new
dependencies.

## Summary

Phase 6 extends a fully-working, well-tested Discord-only reminder engine
(`cogs/reminders.py` + `core/db.py`) with a **second writer**: the FastAPI panel. The engine's
schedule math, validators, and CRUD helpers already exist and are directly reusable — this
phase is primarily **integration + a concurrency guard + one new frequency**, not new
algorithm design.

Three things must happen, in this order of foundational-ness:

1. **Extract the pure schedule math** out of `cogs/reminders.py` (which imports `discord`) into
   a new framework-agnostic `core/reminder_schedule.py`, matching the house pattern
   (`core/settings.py`, `core/store_sync.py`). Both the cog and the new FastAPI router import
   from here. This is a prerequisite for D-13's live next-fire preview and for the biweekly math
   parity — it is not optional plumbing, it is the seam the rest of the phase is built on.
2. **Add the concurrency guard columns** (`paused`, `version`) via the existing
   `ALTER TABLE ... ADD COLUMN` migration idiom (`core/db.py`'s `init_db` already does this for
   `forum_posts`; `init_reminders` currently does not and must gain it). Adopt an **optimistic
   `version` column** (not the re-fetch-before-act alternative) — see Architecture Patterns for
   why, and Code Examples for the exact conditional-UPDATE shape.
3. **Build the table+modal panel surface** (new `reminders.html` + inline Alpine, following
   `settings.html`'s exact `x-data`/toast/validate-then-write conventions) as a set of new routes
   replacing the `/reminders` `_module_stub_page` call in `app/main.py`.

**Primary recommendation:** Use an optimistic-concurrency `version` column bumped on every write
(panel AND scheduler), with conditional `WHERE id = ? AND version = ?` on every
`update_reminder`/`delete_reminder`/`set_next_fire` call. This is deterministically testable
(no real threading/timing needed — the required concurrent-edit test can simulate the race with
two sequential calls) and it eliminates the race rather than merely narrowing its window.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REM-01 | Manager can create/edit/delete reminders via table+modal | `app/templates/settings.html` is the exact template/Alpine pattern to clone; `core/db.py`'s existing `add_reminder`/`update_reminder`/`delete_reminder`/`get_reminder`/`list_reminders` are reused as-is (extended for `paused`+biweekly); new `app/main.py` routes (or `app/routers/reminders.py`, see Architecture Patterns) replace the `_module_stub_page` stub |
| REM-02 | Manager can pause/resume | New `paused` column + `WHERE paused = 0` in `due_reminders`; D-01 clean-forward-resume and D-02 overdue-oneoff-fires-once are pure schedule-math additions to the extracted `core/reminder_schedule.py` |
| REM-03 | Never fires stale, never loses the edit to scheduler write-back (version/re-fetch guard, concurrent-edit test) | Pitfall 7 (`.planning/research/PITFALLS.md` lines 378-447) is the authoritative bug description; Code Examples below give the exact conditional-SQL shape and a deterministic (non-threaded) test recipe modeled on `tests/test_action_queue_concurrency.py`'s existing concurrency-gate precedent |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reminder schedule math (next-fire, DST, month-clamp, biweekly anchor) | Backend (pure `core/` module) | Browser (D-13 live preview re-uses it) | Deterministic, framework-agnostic — must be importable by both the bot cog and the FastAPI app without pulling in `discord` (Pitfall: coupling the app process to Discord internals it doesn't need) |
| Reminder persistence (CRUD, pause state, version guard) | Database (`core/db.py` against shared sqlite) | — | Both writers (bot scheduler, FastAPI panel) share one physical table; sqlite is the only cross-process channel (locked project decision) |
| Table+modal UI, live preview rendering, imminent-fire caveats | Frontend Server (Jinja2 SSR) + Browser (Alpine.js reactivity) | — | Server-rendered shell (no build step) with Alpine handling in-page interactivity, matching Phases 3/4's established pattern exactly |
| Scheduler tick (fire due reminders, advance cursor) | Backend (bot process, `cogs/reminders.py`) | — | Only the bot process holds Discord credentials/gateway access; the panel never sends to Discord (pure DB CRUD, locked) |
| Manager-tier authorization | API / Backend (`app/deps.py::require_manager`) | — | Existing dependency, unchanged; reminders routes are just a new consumer of it |
| Discord name resolution (`#channel`, `@role`) | Database (cached `discord_names` table, bot-pushed) | Frontend (renders cached names) | Established Phase 4 pattern — the panel never makes a live Discord REST call |

## Standard Stack

No new libraries. This phase is 100% additive code against the existing stack:

| Component | Version (installed) | Purpose | Source |
|-----------|---------------------|---------|--------|
| FastAPI + Jinja2Templates | already in `app/main.py` | Server-rendered routes/templates | [VERIFIED: repo] |
| Alpine.js (vendored, `app/static/alpine.min.js`) | 3.15.12 (per `editor.html` script comment) | Client-side reactivity, no build step | [VERIFIED: repo] |
| `discord.py` (`discord.ext.tasks`, `discord.ui.Modal`) | already in `cogs/reminders.py` | Discord-side `/recordatorio` parity commands | [VERIFIED: repo] |
| `zoneinfo` (stdlib) | Python 3.9+ | DST-correct local↔UTC schedule math | [VERIFIED: repo, already used] |
| `sqlite3` (stdlib) + WAL + `busy_timeout=8000` | — | Shared cross-process store | [VERIFIED: repo, `core/db.py::_get_conn`] |

**No installation step required.** No `npm install`/`pip install` for this phase.

## Package Legitimacy Audit

**Not applicable** — this phase installs zero external packages. Everything it needs
(FastAPI, Jinja2, Alpine, `zoneinfo`, `sqlite3`) is already a dependency of the shipped app.
Skip the slopcheck/registry-verification gate entirely for this phase.

## Architecture Patterns

### System Architecture Diagram

```
Manager's browser
   │  GET /reminders                          POST /reminders (create)
   │  GET /reminders/{id}/preview (D-13)       POST /reminders/{id} (edit)
   │                                           POST /reminders/{id}/pause|resume
   │                                           POST /reminders/{id}/delete
   ▼
FastAPI app process (editors-app, require_manager gate)
   │
   ├─► core/reminder_schedule.py  (pure: next_weekly/monthly/oneoff/biweekly_fire,
   │      compute_next, classify_fire, schedule_summary, validators, is_imminent)
   │      — used to VALIDATE + compute next_fire_utc BEFORE any write, and to serve
   │        the D-13 live-preview endpoint
   │
   ├─► core/db.py  add_reminder / update_reminder(expected_version=...) /
   │      delete_reminder(expected_version=...) / list_reminders / get_reminder /
   │      due_reminders (WHERE paused = 0) / set_next_fire(expected_version=...)
   │        — every write conditioned on the `version` column (race guard)
   │
   └─► shared sqlite (bot.db, WAL, busy_timeout=8000) ◄──── reminders table
                                                          (id, name, frequency,
                                                           weekday, day_of_month,
                                                           run_date, hour, minute,
                                                           channel_id, message,
                                                           mentions, reactions,
                                                           next_fire_utc, paused,
                                                           version, created_by,
                                                           created_at)
                                                              ▲
                                                              │ read-at-use every tick
                                                              │ (no queue, no IPC)
                                                              │
Bot process (discord.py, systemd unit "bot")                 │
   │                                                          │
   ├─► cogs/reminders.py::_scheduler (tasks.loop 1min)  ──────┘
   │      _process_due(now):
   │        for r in db.due_reminders(now):        # WHERE paused = 0
   │          cls = classify_fire(...)             # ontime | late | skip
   │          if cls != skip: await self._deliver(r, atrasado=...)  # Discord send
   │          # write-back is CONDITIONAL on r["version"] (race guard):
   │          if frequency == oneoff: db.delete_reminder(r.id, expected_version=r.version)
   │          else: db.set_next_fire(r.id, compute_next(r, now), expected_version=r.version)
   │          # 0 rows affected → row changed mid-flight → log + skip, fresh state stands
   │
   └─► /recordatorio crear|listar|borrar|editar  (Discord slash commands, unchanged
          shape, extended with the `biweekly` frequency choice for parity, D-05)
```

A reader can trace the primary use case (Manager edits a reminder while the scheduler is
mid-tick for the same row) end to end: browser POST → `core/db.py` conditional UPDATE → if the
scheduler's own write-back loses the version race, it logs and backs off, leaving the panel's
edit as the final persisted state — REM-03 proven.

### Recommended Project Structure

```
core/
├── db.py                       # MODIFIED: init_reminders migration (paused, version
│                                #   columns via ALTER TABLE ADD COLUMN, existing idiom);
│                                #   update_reminder/delete_reminder/set_next_fire gain an
│                                #   optional expected_version kwarg; due_reminders gains
│                                #   `AND paused = 0`; _REMINDER_UPDATABLE grows `paused`
│                                #   (+ biweekly's schedule field, likely reusing `run_date`)
└── reminder_schedule.py        # NEW — pure, no discord import: next_weekly_fire,
                                 #   next_monthly_fire, next_oneoff_fire, next_biweekly_fire
                                 #   (NEW, D-06), compute_next, classify_fire, _clamp_day,
                                 #   parse_time/parse_date/valid_weekday/valid_day_of_month/
                                 #   parse_emojis, schedule_summary, is_imminent (NEW, D-15/16)
                                 #   — moved verbatim from cogs/reminders.py's top half

cogs/
└── reminders.py                # MODIFIED: imports the moved functions from
                                 #   core.reminder_schedule instead of defining them; adds
                                 #   the `biweekly` Choice to crear/editar (D-05 parity);
                                 #   _process_due passes expected_version through to the
                                 #   write-back calls (race guard, REM-03)

app/
├── main.py                     # MODIFIED: replace the `/reminders` _module_stub_page GET
│                                #   with the real table page; add the CRUD/pause/preview
│                                #   POST routes (see Claude's Discretion note below on
│                                #   whether to split into app/routers/reminders.py)
└── templates/
    ├── reminders.html           # NEW — table + create/edit modal + confirm-delete dialog,
    │                            #   cloned from settings.html's x-data/toast/validate-
    │                            #   then-write skeleton (same `<script>` block shape)
    └── _dashboard_base.html     # UNCHANGED (sidebar, topbar, .mod-hdr shell reused)
```

**Claude's Discretion note (router file split):** `.planning/research/ARCHITECTURE.md`'s
target structure names `app/routers/reminders.py` as **NEW**, but as of this phase's research
`app/routers/` does not exist yet — every prior module (Overview, Settings, the 5 module
stubs, actions, editor) is a flat set of routes inline in `app/main.py` (already 1074 lines).
Two honest options for the planner:
1. **Follow the existing precedent** (all routes in `app/main.py`) — zero new pattern, but
   `main.py` grows past 1300 lines with reminders' ~8 new routes (list, create, edit, delete,
   pause, resume, preview, plus the page GET).
2. **Start the `app/routers/` package now**, matching ARCHITECTURE.md's original intent, and
   mount it with `app.include_router(...)`. This is the "textbook FastAPI" answer and pays down
   the ARCHITECTURE.md-promised structure, but changes `require_manager`'s dependency-injection
   wiring slightly (still works via `Depends`, just imported from `app.deps` into a new file)
   and is a bigger diff for this one phase to carry alone.
Given reminders is the first CRUD-heavy module (more routes than any single stub so far, and
four more modules with CRUD are still coming per ROADMAP.md), **recommend starting
`app/routers/reminders.py` now** — later phases (Gallery/Reviews/Jinxxy/Meetings) will otherwise
each face the same “do we finally split main.py” decision with more inertia against it. This is
a recommendation, not a lock — CONTEXT.md does not decide this, so it is squarely the planner's
call to make explicitly rather than defaulting silently to "keep piling into main.py."

### Pattern 1: Optimistic-concurrency version column (the REM-03 mechanism)

**What:** A `version INTEGER NOT NULL DEFAULT 1` column, bumped by every mutating call. Every
write becomes conditional: `UPDATE reminders SET ..., version = version + 1 WHERE id = ? AND
version = ?` (and `DELETE ... WHERE id = ? AND version = ?`). The caller passes in the version
it read at fetch time; 0 rows affected means "someone else changed this row since I read it" —
the caller must NOT assume its write happened.

**When to use:** Any write path that reads a row, does work (including `await`ing something
slow, like a Discord send), then writes back a value computed from the ORIGINALLY-READ fields.
This is exactly `RemindersCog._process_due`'s shape (Pitfall 7).

**Why this over "re-fetch-before-act in `_process_due`" (PITFALLS.md's alternative):** The
re-fetch alternative only *shrinks* the race window (from "up to a full tick" to "the width of
one Discord send") — it does not eliminate the race, and a test proving "it didn't happen" for a
probabilistic window-narrowing requires real concurrent threads with timing (like
`tests/test_action_queue_concurrency.py`'s thread-pool harness). The version column makes the
race **impossible to lose silently** and — critically for REM-03's explicit test requirement —
lets the concurrent-edit test be **deterministic and synchronous**: fetch, mutate, attempt a
stale write, assert 0-rows-affected, assert final state. No threads, no `time.sleep`, no flake
risk. See Code Examples for the exact test shape.

**Symmetric application (recommended, not just the scheduler side):** Since D-17 only mandates
the guard on the scheduler-vs-panel direction, it would be inconsistent to leave the panel's OWN
update path unprotected against the *scheduler* changing `next_fire_utc` between the edit
modal's GET and the Save POST. Recommend threading the same `expected_version` kwarg through the
panel's update/delete/pause/resume handlers too (capture version when the row is fetched for the
modal, submit it as a hidden field, 409 on mismatch with "this reminder changed, reload and
retry" copy) — cheap to add now, and it is the same code path either way.

```python
# Source: derived directly from core/db.py's existing update_reminder/delete_reminder shape
# (T-08-03 allowlist discipline preserved) — NOT yet in the codebase, this is the pattern
# to implement.
def update_reminder(reminder_id: int, *, expected_version: int | None = None, **fields) -> bool:
    cols = [(k, v) for k, v in fields.items() if k in _REMINDER_UPDATABLE]
    if not cols:
        return True
    set_clause = ", ".join(k + " = ?" for k, _ in cols) + ", version = version + 1"
    values = [v for _, v in cols]
    where = "id = ?"
    values.append(reminder_id)
    if expected_version is not None:
        where += " AND version = ?"
        values.append(expected_version)
    with _get_conn() as conn:
        cur = conn.execute(f"UPDATE reminders SET {set_clause} WHERE {where}", values)
        return cur.rowcount > 0


def delete_reminder(reminder_id: int, *, expected_version: int | None = None) -> bool:
    where, values = "id = ?", [reminder_id]
    if expected_version is not None:
        where += " AND version = ?"
        values.append(expected_version)
    with _get_conn() as conn:
        cur = conn.execute(f"DELETE FROM reminders WHERE {where}", values)
        return cur.rowcount > 0


def set_next_fire(reminder_id: int, next_fire_utc_iso: str, *,
                   expected_version: int | None = None) -> bool:
    where, values = "id = ?", [next_fire_utc_iso, reminder_id]
    if expected_version is not None:
        where += " AND version = ?"
        values.append(expected_version)
    with _get_conn() as conn:
        cur = conn.execute(
            f"UPDATE reminders SET next_fire_utc = ?, version = version + 1 WHERE {where}",
            values)
        return cur.rowcount > 0
```

```python
# Source: derived from cogs/reminders.py::_process_due (existing) — the race-guard change.
async def _process_due(self, now: datetime):
    for r in db.due_reminders(now.isoformat()):
        try:
            cls = classify_fire(now, datetime.fromisoformat(r["next_fire_utc"]),
                                config.REMINDERS_CATCHUP_GRACE_HOURS)
            if cls != "skip":
                await self._deliver(r, atrasado=(cls == "late"))
            if r["frequency"] == "oneoff":
                ok = db.delete_reminder(r["id"], expected_version=r["version"])
            else:
                ok = db.set_next_fire(r["id"], compute_next(r, now).isoformat(),
                                      expected_version=r["version"])
            if not ok:
                log.info(
                    "reminders: id=%s cambió durante el disparo (versión obsoleta) — "
                    "se respeta el estado actual, no se sobrescribe", r["id"])
        except Exception:
            log.exception(
                "reminders: fallo al disparar id=%s (los demás continúan)", r["id"])
```

### Pattern 2: Extracted pure schedule module (`core/reminder_schedule.py`)

**What:** Move every function above the `# ══ Discord layer ══` marker in
`cogs/reminders.py` (lines 1-197 in the current file: `_clamp_day`, `next_weekly_fire`,
`next_monthly_fire`, `next_oneoff_fire`, `compute_next`, `classify_fire`, `parse_time`,
`parse_date`, `valid_weekday`, `valid_day_of_month`, `parse_emojis`, `schedule_summary`) into
`core/reminder_schedule.py`, unchanged. Add `next_biweekly_fire` (D-06) and a new `is_imminent`
helper (D-15/D-16) alongside them. `cogs/reminders.py` imports these back
(`from core.reminder_schedule import next_weekly_fire, ...`) so every existing test in
`tests/test_reminders_cog.py` that does `reminders.next_weekly_fire(...)` etc. keeps working via
re-export, or the test file's imports get a one-line update — planner's call on which is less
churn.

**When to use:** Any function computation reachable from BOTH the FastAPI process and the bot
process must live here, never in `cogs/reminders.py` (which imports `discord`).

**Why now, not deferred:** D-13's live next-fire preview and the app-side create/edit validation
both need this exact math. `config.py` (which `next_weekly_fire` et al. call for
`REMINDERS_TZ`) has zero `discord` dependency already (`import os`, `from pathlib import Path`,
`from dotenv import load_dotenv` — verified), so this extraction has no hidden coupling problem;
it is a pure "move code" operation.

```python
# Source: new function for core/reminder_schedule.py, following the exact shape/idiom of
# next_weekly_fire/next_monthly_fire already in cogs/reminders.py (D-06: anchored biweekly).
def next_biweekly_fire(now_utc: datetime, anchor_date: str, hour: int, minute: int,
                       tz: str | None = None) -> datetime:
    """Next occurrence of a 14-day cadence anchored on ``anchor_date`` (D-06).

    A PAST anchor_date is valid (only parity/cadence matters) — unlike a one-off's run_date,
    which is rejected in the past. Computes anchor + 14*n for the smallest n giving an
    instant >= now, via whole-day arithmetic in the LOCAL zone (never a fixed-offset UTC
    delta) so DST transitions inside the 14-day window stay correct (matches next_weekly_fire/
    next_monthly_fire's existing zoneinfo discipline).
    """
    zone = ZoneInfo(tz or config.REMINDERS_TZ)
    anchor = parse_date(anchor_date)
    anchor_local = datetime(anchor.year, anchor.month, anchor.day, hour, minute, tzinfo=zone)
    local_now = now_utc.astimezone(zone)
    days_since_anchor = (local_now.date() - anchor_local.date()).days
    periods = max(0, -(-days_since_anchor // 14))  # ceil division, never negative
    candidate = anchor_local + timedelta(days=14 * periods)
    if candidate <= local_now:
        candidate += timedelta(days=14)
    return candidate.astimezone(timezone.utc)
```

```python
# Source: new function for core/reminder_schedule.py (D-15/D-16 imminent-fire threshold).
def is_imminent(next_fire_utc: datetime, now_utc: datetime,
                threshold_seconds: int = 90) -> bool:
    """True iff ``next_fire_utc`` is within ``threshold_seconds`` of ``now_utc`` (past or
    future) — the D-15/D-16 "may already be mid-send" caveat trigger. Default 90s = 1.5x the
    60s scheduler tick (UI-SPEC's recommended default), covering the case where the row is
    already slightly overdue (scheduler claimed it, hasn't written back yet) as well as the
    case where it's about to become due.
    """
    return abs((next_fire_utc - now_utc).total_seconds()) <= threshold_seconds
```

### Pattern 3: Table+modal Alpine component, cloned from `settings.html`

**What:** `settings.html`'s `x-data='settingsApp({{ groups | tojson }}, ...)'` +
inline `<script>` defining `function settingsApp(...)` (returning `{values, save(), errors,
toast, ...}`) is the EXACT shape to reuse for `remindersApp(...)`. Reminders adds:
`rows` (table data), `modalOpen`/`editingId`, `confirmDelete` state, and a `preview` computed
field (D-13) recomputed on every relevant `x-model` change via a `watch`-style method call
(`this.recomputePreview()` invoked from `@input`/`@change` on the schedule fields, calling
`core/reminder_schedule.py`'s math server-side via a small `GET/POST /reminders/preview`
endpoint — client-side reimplementation of the DST/month-clamp math is explicitly NOT
recommended, see Don't Hand-Roll).

**When to use:** This is the only front-end pattern in the codebase for a validate-then-write
form with per-field errors + a toast — reuse verbatim, do not invent a second convention.

```html
<!-- Source: pattern derived from app/templates/settings.html lines 1-24, 121-124, 129-210 -->
<div class="reminders-page" x-data='remindersApp({{ rows | tojson }}, {{ names | tojson }})' x-cloak>
  <div class="ph">
    <div class="ttl">Recordatorios · Reminders</div>
    <div class="spacer"></div>
    <button class="btn" type="button" @click="openCreate()">Nuevo recordatorio · New reminder</button>
  </div>
  <div class="mod-hdr" style="--acc: var(--accent-reminders)">...</div>
  <!-- table / .empty, per D-07..D-10 -->
  <!-- modal via x-show/x-if, per D-11..D-14 -->
  <!-- confirm dialog via x-show/x-if, per D-15/D-17/D-18 -->
  <div class="toast" x-show="toast" x-cloak :data-kind="toastKind" x-text="toast"
       @click="toast=''" role="status" aria-live="polite"></div>
</div>
```

### Anti-Patterns to Avoid

- **Re-implementing the schedule math (DST/month-clamp/biweekly anchor) in client-side
  JavaScript for the D-13 live preview.** The bot's `zoneinfo`-based math is the single source
  of truth; a hand-rolled JS reimplementation WILL drift on DST edges and month-end clamping
  (exactly the bug class `_clamp_day`/`ZoneInfo` already guard against). Call a small server
  endpoint that runs the real `core/reminder_schedule.py` functions instead.
- **Making `version` a client-settable field.** It must only ever be read (to echo back as
  `expected_version`) and incremented server-side (`version = version + 1` in the SQL, never
  `version = ?` from client input) — otherwise a stale client could "reset" the version and
  defeat the guard.
- **Skipping the `paused` filter change in `due_reminders`.** Adding the `paused` column without
  adding `AND paused = 0` to `due_reminders`'s WHERE clause is a silent no-op feature — a paused
  reminder would still fire every tick.
- **Splitting reminders write logic between `app/main.py` and a NEW `app/routers/reminders.py`
  inconsistently within the same phase** (e.g. some routes inline, some in the new file) — pick
  one per the Claude's Discretion note above and apply it wholly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DST-correct local↔UTC schedule math | A new "smart" date library or manual UTC-offset arithmetic | `zoneinfo.ZoneInfo` + the existing `next_weekly_fire`/`next_monthly_fire`/`next_oneoff_fire` pattern, extended with `next_biweekly_fire` in the same style | Already correct, already tested (`tests/test_reminders_cog.py`); a second implementation for the panel's preview would inevitably drift |
| Optimistic concurrency / row-versioning | A custom lock table, a `threading.Lock`, or a distributed lock | A plain `version` integer column + conditional `WHERE ... AND version = ?` | This is the textbook SQLite optimistic-concurrency idiom; no new dependency, works across two separate OS processes (a `threading.Lock` would NOT — the bot and app are different processes) |
| Validate-then-write two-pass form submission | A hand-rolled draft/commit state machine | The existing `settings.validate_only` → collect errors → only write if ALL valid pattern (`app/main.py::save_settings`) | REM-01's CONTEXT.md D-14 explicitly locks this as "carried forward," not re-decided |
| Channel/role name resolution | A live Discord REST call from the FastAPI process on every page render | The existing `discord_names` bot-pushed cache (`core/db.py::get_discord_names`) | Locked architecture: the app process never talks to Discord directly (single-writer principle); a live call here would also be slow and rate-limit-risky on every table render |

**Key insight:** Every piece of hard logic this phase needs (schedule math, concurrency
control, validate-then-write, name resolution) already has a working, tested precedent
somewhere in this repo. The work is almost entirely "wire it up to a second call site,"
not "invent a new algorithm."

## Common Pitfalls

### Pitfall 1: The scheduler write-back race (Pitfall 7 in PITFALLS.md) — REM-03's core risk

**What goes wrong:** `_process_due` reads a row once, does an `await` (Discord send), then
writes back computed from the stale in-memory row. A concurrent panel edit/delete between the
read and the write-back either gets silently overwritten (edit case) or the reminder fires once
more after being deleted (delete case, accepted risk per D-18).

**Why it happens:** No transaction spans "read due row" → "act" → "write outcome"; introducing
a second writer (the panel) on a table only the scheduler used to touch is new to this
milestone.

**How to avoid:** The `version` column pattern above (Architecture Patterns, Pattern 1) — apply
it to every write path, panel and scheduler alike.

**Warning signs:** A support report of "I changed the time but it still fired at the old
time once"; a reminder briefly reappearing after delete (would be a DIFFERENT, worse bug —
worth a defensive test even though today's `delete_reminder` is a plain unconditional DELETE
today).

### Pitfall 2: Forgetting the `ALTER TABLE` migration for existing installations

**What goes wrong:** `init_reminders()` currently does a bare `CREATE TABLE IF NOT EXISTS` with
no column-migration step (unlike `init_db()`'s `forum_posts`, which already has the
try/except `ALTER TABLE ... ADD COLUMN` idiom for `image_url`/`source_url`). If the new
`paused`/`version` columns are only added to the `CREATE TABLE` string, every environment with
an EXISTING `bot.db` (the production reminders table, already populated) will keep the old
schema forever — `init_reminders()` is a no-op against an existing table.

**Why it happens:** SQLite's `CREATE TABLE IF NOT EXISTS` does not retroactively add columns to
an already-existing table; only `ALTER TABLE ... ADD COLUMN` does.

**How to avoid:** Add the same `try: conn.execute("ALTER TABLE reminders ADD COLUMN paused
INTEGER NOT NULL DEFAULT 0") except sqlite3.OperationalError: pass` idiom (copy `init_db`'s
existing 3-line pattern at `core/db.py` lines 36-40) for both `paused` and `version`.

**Warning signs:** `sqlite3.OperationalError: no such column: paused` at runtime against a
pre-existing `bot.db`, even though a fresh test's `tmp_path` db works fine (tests always create
the table fresh, masking this class of bug — this is exactly the kind of thing a fresh-db test
suite won't catch).

### Pitfall 3: `_REMINDER_UPDATABLE` allowlist omission (T-08-03 discipline, still applies)

**What goes wrong:** `update_reminder(**fields)` silently drops any key not in
`_REMINDER_UPDATABLE` (existing, correct security behavior against SQL-injection-by-column-name)
— but if `paused` (and whatever biweekly anchor field is chosen) isn't ADDED to that tuple, a
pause/resume or biweekly-edit call becomes a silent no-op with no error raised.

**How to avoid:** Explicitly add `"paused"` (and the biweekly schedule field, if a new column is
introduced rather than reusing `run_date`) to `_REMINDER_UPDATABLE`. Write a test that pauses via
`update_reminder` and asserts the row's `paused` actually changed — the existing test suite has
no such test today because `paused` doesn't exist yet.

### Pitfall 4: Mixing up `version`'s two writers

**What goes wrong:** If ONLY the scheduler's write-back is guarded by `version` and the panel's
own `update_reminder`/`delete_reminder` calls omit `expected_version`, the panel's edit will
ALWAYS win the race trivially (because it isn't conditional at all) — but the REVERSE race (panel
opens the edit modal, scheduler advances the row, panel then saves a schedule computed from a
stale weekday/day-of-month it displayed) is silently unprotected. This may be acceptable
(D-17 only strictly requires the scheduler-vs-panel direction) but is worth flagging as an
intentional scope decision, not an oversight, in the plan's task list.

**How to avoid:** Either explicitly scope this out with a one-line justification in the plan, or
(recommended) thread `expected_version` through the panel's own write paths too — see Pattern 1's
"Symmetric application" note.

### Pitfall 5: Biweekly's "past anchor is valid" rule inverting the one-off validation

**What goes wrong:** `crear`'s existing one-off validation rejects a past date+time
(`next_oneoff_fire(fecha, hour, minute) <= now → reject`). D-06 explicitly says a biweekly
anchor may be in the PAST (it only sets parity/cadence). If the biweekly validator is copy-pasted
from the one-off validator without removing that check, every biweekly reminder anchored more
than one cycle ago will incorrectly reject at creation time.

**How to avoid:** `next_biweekly_fire`'s own logic already rolls a past anchor forward to the
next valid occurrence (see Code Examples) — the validator for biweekly must NOT reuse
`next_oneoff_fire(...)  <= now → reject`; it should simply always succeed for any parseable date
(no past-date rejection at all for this frequency).

### Pitfall 6: `classify_fire`'s catch-up grace window interacting with D-01's clean resume

**What goes wrong:** D-01 requires a resumed recurring reminder to recompute forward from NOW,
never firing a backlog. If "resume" is implemented as merely flipping `paused` back to 0 without
recomputing `next_fire_utc`, the NEXT scheduler tick will see a stale (possibly far-past)
`next_fire_utc`, and `classify_fire`'s existing grace-window logic (`late` up to
`REMINDERS_CATCHUP_GRACE_HOURS`, `skip` beyond) will kick in unpredictably — sometimes firing a
stale "atrasado" message for a RECURRING reminder, which D-01 explicitly says should never
happen (that behavior is reserved for one-off overdue reminders, D-02).

**How to avoid:** The resume endpoint must call the appropriate `next_*_fire` function to
recompute `next_fire_utc` fresh AT RESUME TIME (not just flip the paused flag), for every
frequency except the D-02 overdue-one-off special case (which instead fires once immediately
then deletes, bypassing the normal scheduler tick entirely).

## Code Examples

### Schema migration (extends the existing `init_db` idiom)

```python
# Source: pattern already established at core/db.py lines 36-40 (forum_posts), applied to
# init_reminders (currently missing this migration step entirely).
def init_reminders():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                frequency     TEXT    NOT NULL,
                weekday       INTEGER,
                day_of_month  INTEGER,
                run_date      TEXT,
                hour          INTEGER NOT NULL,
                minute        INTEGER NOT NULL,
                channel_id    INTEGER NOT NULL,
                message       TEXT    NOT NULL,
                mentions      TEXT    DEFAULT '',
                reactions     TEXT    DEFAULT '',
                next_fire_utc TEXT    NOT NULL,
                created_by    INTEGER NOT NULL,
                created_at    TEXT    NOT NULL
            )
        """)
        for col, default in [("paused", "0"), ("version", "1")]:
            try:
                conn.execute(
                    f"ALTER TABLE reminders ADD COLUMN {col} INTEGER NOT NULL DEFAULT {default}")
            except sqlite3.OperationalError:
                pass  # already exists
```

### Deterministic concurrent-edit test (D-17's required proof, no threading needed)

```python
# Source: new test, modeled on the required-behavior described in PITFALLS.md Pitfall 7 and
# following this repo's existing tmp_path/monkeypatch DB-isolation idiom
# (tests/test_action_queue_concurrency.py's _use_tmp_db pattern).
def test_scheduler_writeback_never_clobbers_concurrent_panel_edit(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "race.db"), raising=False)
    db.init_reminders()
    rid = db.add_reminder(
        name="Junta", frequency="weekly", weekday=0, hour=9, minute=0,
        channel_id=1, message="x", created_by=1,
        next_fire_utc=NOW.isoformat())

    # 1. Scheduler's due_reminders() fetch — captures a snapshot INCLUDING version=1.
    stale_row = db.due_reminders(NOW.isoformat())[0]
    assert stale_row["version"] == 1

    # 2. "Concurrent" panel edit lands BEFORE the scheduler's write-back (bumps version to 2,
    #    changes weekday Mon->Fri and its implied next_fire_utc).
    panel_next_fire = "2026-07-10T09:00:00+00:00"  # the Friday this implies
    assert db.update_reminder(rid, weekday=4, next_fire_utc=panel_next_fire) is True

    # 3. Scheduler now attempts its write-back using the STALE snapshot's version (1) and a
    #    next_fire_utc computed from the OLD weekday — this must be REJECTED (0 rows affected).
    stale_next_fire = compute_next(stale_row, NOW).isoformat()
    ok = db.set_next_fire(rid, stale_next_fire, expected_version=stale_row["version"])
    assert ok is False

    # 4. Final persisted state reflects the PANEL's edit, not the scheduler's stale compute.
    final = db.get_reminder(rid)
    assert final["next_fire_utc"] == panel_next_fire
    assert final["weekday"] == 4
```

## State of the Art

No "old vs new approach" table applies here — this phase does not replace a prior version of
itself, it is the first time reminders gets panel CRUD. The one relevant "state of the art"
note: **this project's own `init_db()` already demonstrates the correct SQLite column-migration
idiom** (`ALTER TABLE ... ADD COLUMN` inside `try/except sqlite3.OperationalError`) — this phase
should follow that existing precedent for `init_reminders()`, not invent a different migration
mechanism (e.g. a versioned migrations framework, which would be over-engineering for a
single-file sqlite store with ~5 tables total).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Reusing the existing `run_date` column (rather than adding a new `anchor_date` column) for biweekly's anchor is the lower-friction choice | Recommended Project Structure / Pattern 2 | Low — CONTEXT.md D-06 explicitly leaves this decision to the planner; if a dedicated column is preferred instead, only `core/db.py`'s CREATE TABLE / migration / `_REMINDER_UPDATABLE` need one extra column, no other design changes |
| A2 | 90 seconds is an adequate "imminent fire" threshold for the D-15/D-16 warning trigger | Pattern 2 (`is_imminent`) | Low — UI-SPEC.md already states this as its own "recommended default... exact threshold is implementation discretion," so this is carrying forward an already-flagged discretion point, not introducing a new unverified claim |
| A3 | Starting `app/routers/reminders.py` now (rather than adding routes inline to `app/main.py`) is the better call for this phase | Recommended Project Structure | Medium — this is a structural recommendation with real trade-offs (see the discretion note); if the planner disagrees, all the reminders-CRUD logic proposed here still works unchanged, only the file location differs |

**If this table is empty:** N/A — see rows above. None of these are compliance/security/
retention claims; they are structural/UX discretion calls that CONTEXT.md and UI-SPEC.md already
explicitly delegated to the planner.

## Open Questions (RESOLVED)

1. **Does `version` need to be exposed to the panel's read endpoints (table list / modal GET) at
   all, or only round-tripped internally?**
   - **RESOLVED** — recommendation adopted: Plan 04 threads `version` as a hidden,
     non-rendered value and returns a distinct 409 on a stale edit; Plan 05 captures that
     hidden version in the modal's Alpine state and maps the 409 to the dedicated
     "this reminder changed — reload" toast variant.
   - What we know: the modal's edit-save POST needs SOME way to detect "this row changed since I
     opened the modal" if the Symmetric Application recommendation (Pattern 1) is adopted.
   - What's unclear: whether the UI-SPEC's locked visual/copy contract has room for a "this
     reminder changed, please reload" toast state (it currently only specifies validation-error
     and imminent-fire toasts).
   - Recommendation: thread `version` as a hidden value in the modal's Alpine state (not
     rendered visually), and treat a 409 from the edit-save endpoint as a distinct toast variant
     ("Este recordatorio cambió mientras editabas — recarga la página. · This reminder changed
     while you were editing — reload the page.") — small, low-risk addition within the existing
     toast mechanism, not a new UI surface.

2. **Exact biweekly weekday-label derivation for `schedule_summary`'s "Cada 2 semanas · <día>
   HH:MM" format.**
   - **RESOLVED** — implemented by Plan 01 Task 2: `schedule_summary` derives the Spanish
     weekday via `_WEEKDAYS_ES[datetime.fromisoformat(run_date).weekday()]` to emit
     "Cada 2 semanas · <día> HH:MM".
   - What we know: the anchor date determines the day-of-week; the format string needs the
     Spanish weekday name, which `_WEEKDAYS_ES` (in the to-be-extracted schedule module) already
     provides by index.
   - What's unclear: nothing structurally — `datetime.fromisoformat(run_date).weekday()` gives
     the index directly. This is a straightforward implementation detail, not a genuine research
     gap; flagged only so the planner writes it as an explicit task rather than assuming
     `schedule_summary`'s dispatch "just works" for a new frequency without a code change.

## Environment Availability

Skipped — this phase has no new external dependencies (no new packages, no new system binaries
like `ffmpeg`, no new third-party service). Everything needed (Python stdlib `zoneinfo`/
`sqlite3`, the already-vendored Alpine.js, the already-installed FastAPI/Jinja2/discord.py) is
already present and already in use elsewhere in this exact codebase.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (no `pytest.ini`/`pyproject.toml` config section found — plain discovery via `tests/` + `tests/conftest.py`'s `sys.path` bootstrap) |
| Config file | none — see Wave 0 note below |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminders_cog.py -v` (per project convention in MEMORY.md — NOT the PowerShell `Python314` interpreter, which has no pytest) |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REM-01 | Panel create/edit/delete round-trips through `core/db.py` correctly (incl. new `paused`/biweekly fields persisted) | unit | `pytest tests/test_db_reminders_crud.py -x` | ❌ Wave 0 (new file — extends `core/db.py`'s reminder helpers, no existing dedicated db-level reminder test file; current coverage is only via `tests/test_reminders_cog.py`'s cog-level mocks) |
| REM-01 | Table+modal panel routes (list/create/edit/delete) return correct status codes + persist state | integration | `pytest tests/test_app_reminders.py -x` | ❌ Wave 0 (new file, mirrors `tests/test_app_settings.py`'s existing FastAPI-route-test pattern) |
| REM-02 | Pause suppresses `due_reminders`; resume recomputes forward (D-01) / fires-once-then-deletes for overdue one-off (D-02) | unit | `pytest tests/test_reminders_cog.py -k pause_resume -x` | ❌ Wave 0 (extends the existing 875-line file's scheduler-test section) |
| REM-03 | Concurrent-edit test: scheduler write-back never clobbers a panel edit that landed first (version guard) | unit | `pytest tests/test_reminders_cog.py -k concurrent_edit -x` | ❌ Wave 0 — this is the LOCKED, required test per D-17; see Code Examples for its exact deterministic shape |
| REM-04 (biweekly, scope expansion) | `next_biweekly_fire` anchor math, incl. past-anchor validity and DST correctness | unit | `pytest tests/test_reminder_schedule.py -k biweekly -x` | ❌ Wave 0 (new file for the extracted `core/reminder_schedule.py`, mirrors the schedule-math test section already in `tests/test_reminders_cog.py` lines 1-440-ish) |

### Sampling Rate

- **Per task commit:** `pytest tests/test_reminders_cog.py tests/test_reminder_schedule.py -q`
  (fast — pure-function + mocked-DB tests, no real threading)
- **Per wave merge:** `pytest -q` (full suite, catches any cross-module regression e.g. in
  `core/db.py`'s shared `_get_conn`)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `core/reminder_schedule.py` doesn't exist yet — must be created (extraction) before any
      test can import from it; existing tests in `tests/test_reminders_cog.py` that call
      `reminders.next_weekly_fire(...)` etc. need their import updated or a re-export added.
- [ ] `tests/test_db_reminders_crud.py` — new file, covers `paused`/`version` column behavior at
      the `core/db.py` layer directly (today's reminder DB coverage is entirely indirect, via the
      cog-level mocks in `test_reminders_cog.py`).
- [ ] `tests/test_app_reminders.py` — new file, covers the new FastAPI routes; no
      `require_manager`-gated CRUD route test exists yet for reminders specifically (the closest
      precedent is `tests/test_app_settings.py`/`tests/test_app_actions.py`).
- [ ] No framework install needed — pytest is already the project's test runner.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Session-cookie auth is already established (Phase 3), unchanged by this phase |
| V3 Session Management | no | Unchanged — `require_manager` reused as-is |
| V4 Access Control | yes | Every new route MUST use `Depends(require_manager)` (existing dependency, unchanged) — no reminders route should ever be reachable without it, matching the other 5 module stubs' pattern exactly |
| V5 Input Validation | yes | Reuse the existing validators (`parse_time`, `parse_date`, `valid_weekday`, `valid_day_of_month`, `parse_emojis`) verbatim server-side; the panel must NEVER trust client-computed `next_fire_utc` for a write — always recompute server-side from the validated schedule fields (same discipline `editar` already has) |
| V6 Cryptography | no | No new secrets/crypto surface in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via dynamic column names in `update_reminder`'s `**fields` | Tampering | Existing `_REMINDER_UPDATABLE` explicit allowlist (T-08-03) — MUST be extended to include `paused` and the biweekly anchor field, never bypassed for convenience |
| IDOR: a Manager editing/deleting a reminder ID not meant to be theirs | Tampering / Info disclosure | Not applicable at this tier — reminders are a shared team resource (any Manager may act on any reminder), unlike editor pages (D-08's per-editor IDOR concern doesn't apply here); no additional ownership check needed beyond `require_manager` |
| CSRF on the new POST routes (create/edit/delete/pause/resume) | Tampering | Existing `SameSite=Lax` session cookie is the established CSRF mitigation for every POST in this app (T-10-10-04) — no new hand-rolled CSRF token needed, same as Settings' `/admin/settings` POST |
| Optimistic-concurrency version bypass (client supplies a fabricated `version` to force an overwrite) | Tampering | `version` must be a server-computed echo-back value the panel never lets the client set arbitrarily beyond "the value I last read" — the SQL always does `version = version + 1` server-side, never accepts a client-supplied version to WRITE, only to match in the WHERE clause |
| Injection via the message body / mention / reaction-emoji fields reaching the panel's create/edit form | Tampering / Injection | Already mitigated: `core/db.py` uses parameterized `?` placeholders everywhere (T-08-03); Discord's own message rendering handles the body text safely (no HTML/template injection surface since Jinja2 auto-escapes and the message is never rendered as HTML in the panel table — only in the modal's plain textarea) |

## Sources

### Primary (HIGH confidence — direct codebase reads)
- `cogs/reminders.py` (full file, 741 lines) — the entire existing schedule math, validators,
  modal flow, scheduler, and Discord command group
- `core/db.py` (full file, 756 lines) — every existing table's CRUD idiom, incl. the
  `ALTER TABLE ADD COLUMN` migration pattern already used for `forum_posts`
- `app/main.py` (full file, 1074 lines) — every existing route pattern, `_module_stub_page`,
  `require_manager`/`require_owner` usage, the `/reminders` GET stub to be replaced
- `app/deps.py` (full file) — `require_manager`/`_resolve_roles`/`TierForbidden`
- `app/templates/settings.html` + its inline `<script>` — the exact Alpine validate-then-write
  pattern to clone
- `app/templates/module_stub.html` — the stub this phase's real page replaces
- `app/static/dashboard.css` (full file, 347 lines) — every CSS token/class already available
  (`.mod-hdr`, `.card`, `table`/`th`/`td`, `.role-chip`, `.resolved-name`, `.toast`,
  `.field-error`, `--accent-reminders`, etc.)
- `tests/test_reminders_cog.py` (875 lines) — existing test conventions for the scheduler,
  `_process_due`, `_row()`/`_patch_db()` fixtures
- `tests/test_action_queue_concurrency.py` — the project's own precedent for a concurrency-gate
  test (threaded version; this phase's REM-03 test is deliberately deterministic instead, see
  Pattern 1's rationale)
- `.planning/research/ARCHITECTURE.md` — target structure (`app/routers/reminders.py`),
  component responsibility table, "reminders CRUD hits core/db.py directly (no queue)"
- `.planning/research/PITFALLS.md` Pitfall 7 (lines 378-447) — the authoritative bug
  description and both mitigation options this research chooses between
- `.planning/phases/06-reminders-crud/06-CONTEXT.md` — every locked decision (D-01 through D-18)
- `.planning/phases/06-reminders-crud/06-UI-SPEC.md` — visual/copy contract, incl. the
  recommended 90s imminent-fire threshold
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` — REM-01/02/03 definitions, project decision
  history
- `config.py` (relevant sections + `__getattr__` shim, verified: zero `discord` import)
- `core/settings.py` (grep-verified: `REMINDERS_TZ`/`REMINDERS_STAFF_ROLE_IDS`/
  `REMINDERS_CATCHUP_GRACE_HOURS` schema entries)

### Secondary / Tertiary
None — no WebSearch or Context7 lookups were needed; this phase is entirely an extension of
in-repo, already-shipped patterns with no new third-party library surface.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, everything verified by direct file reads
- Architecture: HIGH — every pattern is either already shipped in this repo or a direct,
  small extension of one that is (version column is a well-established, textbook SQLite idiom)
- Pitfalls: HIGH — Pitfall 7 is pre-documented in this repo's own research with exact code
  references; the migration/allowlist pitfalls are directly observable in `core/db.py`'s current
  state (verified: `init_reminders` has no ALTER TABLE step today)

**Research date:** 2026-07-23
**Valid until:** No external expiry — this research is grounded in the current state of this
specific codebase, not a third-party API/library that could version-drift. Re-verify only if
`cogs/reminders.py`/`core/db.py`/`app/main.py` change materially before this phase is planned.
