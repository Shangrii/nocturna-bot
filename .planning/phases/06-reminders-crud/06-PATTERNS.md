# Phase 6: Reminders CRUD - Pattern Map

**Mapped:** 2026-07-23
**Files analyzed:** 10 (2 modified core, 1 new core, 1 modified cog, 1 new router/routes,
1 new template, 1 modified stylesheet, 4 new/modified test files)
**Analogs found:** 10 / 10 (all have a strong in-repo analog; this phase is pure
extension of existing idioms — see RESEARCH.md "Don't Hand-Roll")

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `core/reminder_schedule.py` (NEW) | utility (pure module) | transform | `cogs/reminders.py` lines 1-197 (the exact code being moved) | exact (verbatim extraction) |
| `core/db.py` (MODIFIED: `init_reminders` migration) | model (schema/migration) | CRUD | `core/db.py::init_db` lines 23-44 (`forum_posts` ALTER TABLE idiom) | exact |
| `core/db.py` (MODIFIED: `update_reminder`/`delete_reminder`/`set_next_fire` gain `expected_version`) | model (CRUD + optimistic concurrency) | CRUD | `core/db.py::update_reminder`/`delete_reminder`/`set_next_fire` (same file, current shape, lines 326-366) | exact (in-place extension) |
| `core/db.py` (MODIFIED: `due_reminders` gains `AND paused = 0`) | model (query filter) | CRUD | `core/db.py::due_reminders` (same file, lines 351-357) | exact |
| `cogs/reminders.py` (MODIFIED: import from core, add biweekly, race-guard write-back) | controller (Discord command group + scheduler) | event-driven + request-response | itself, pre-change (741 lines, full file read) | exact (in-place extension) |
| `app/routers/reminders.py` (NEW — recommended split, see Shared Patterns note) | controller (FastAPI routes) | request-response (CRUD) | `app/main.py` lines 610-777 (`overview_page`/`_module_stub_page`/`settings_page`/`save_settings`) | role-match (closest existing route-group shape; no router package exists yet) |
| `app/templates/reminders.html` (NEW) | component (Jinja+Alpine page) | request-response (form CRUD) | `app/templates/settings.html` (full file, 211 lines) | exact (explicit clone target per RESEARCH.md Pattern 3) |
| `app/static/dashboard.css` (MODIFIED: new `reminders` block) | config (styles) | transform | same file's existing `.settings-*`/`.role-chip*`/`.mod-hdr`/`.toast` blocks (lines 171-347) | exact |
| `tests/test_reminder_schedule.py` (NEW) | test | transform | `tests/test_reminders_cog.py` lines 1-440 (schedule-math test section, pre-extraction) | exact |
| `tests/test_db_reminders_crud.py` (NEW) | test | CRUD | `tests/test_action_queue_concurrency.py` (tmp_path DB-isolation idiom) + `core/db.py` reminder CRUD itself | role-match |
| `tests/test_app_reminders.py` (NEW) | test | request-response | `tests/test_app_settings.py` (full file, `client` fixture + validate-then-write assertions) + `tests/test_app_actions.py` (`require_manager` override idiom) | exact |
| `tests/test_reminders_cog.py` (MODIFIED: pause/resume + concurrent-edit tests) | test | event-driven | itself, pre-change (`_row`/`_patch_db` fixtures, lines 448-473) | exact |

## Pattern Assignments

### `core/reminder_schedule.py` (NEW — utility, transform)

**Analog:** `cogs/reminders.py` lines 1-197 (everything above the `# ══ Discord layer ══`
marker at line 200)

This is a **verbatim move**, not a rewrite. Copy these functions unchanged into the new
module, then add `next_biweekly_fire` and `is_imminent` alongside them.

**Imports pattern** (source: `cogs/reminders.py` lines 17-27 — drop the `discord`-family
imports, keep the rest):
```python
import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
# NOTE: do NOT import discord/discord.ext here — this module must stay import-safe
# for the FastAPI process (RESEARCH.md Pattern 2 / Integration Points).

log = logging.getLogger(__name__)

_WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
```

**Core pattern — functions to move unchanged** (source: `cogs/reminders.py` lines 40-197):
`_clamp_day`, `next_weekly_fire`, `next_monthly_fire`, `next_oneoff_fire`, `compute_next`,
`classify_fire`, `parse_time`, `parse_date`, `valid_weekday`, `valid_day_of_month`,
`parse_emojis`, `schedule_summary`. Each already follows the exact
`ZoneInfo(tz or config.REMINDERS_TZ)` + local-wall-time-then-`.astimezone(timezone.utc)`
idiom D-06 requires for `next_biweekly_fire` — mirror it exactly (RESEARCH.md gives the
full `next_biweekly_fire`/`is_imminent` implementations to drop in, Architecture Patterns
Pattern 2 — treat those as ready-to-use, not merely illustrative).

**Re-export shim in `cogs/reminders.py`** (avoids churning every call site/test at once):
```python
from core.reminder_schedule import (
    _clamp_day, next_weekly_fire, next_monthly_fire, next_oneoff_fire,
    next_biweekly_fire, compute_next, classify_fire, is_imminent,
    parse_time, parse_date, valid_weekday, valid_day_of_month,
    parse_emojis, schedule_summary, _WEEKDAYS_ES,
)
```

**Error handling:** none of these functions catch exceptions — they raise `ValueError` on
malformed input (see `parse_time`/`parse_date`) and let the caller (the Discord command
handler or the FastAPI route) decide how to surface it. Preserve this — do not add
try/except inside the pure module.

---

### `core/db.py` — `init_reminders` migration (MODIFIED — model, CRUD)

**Analog:** `core/db.py::init_db` lines 23-44 (the `forum_posts` `ALTER TABLE` idiom —
the ONLY existing precedent for adding a column to a pre-existing table in this repo)

**Migration pattern to copy** (source: `core/db.py` lines 36-40):
```python
for col, default in [("image_url", "''"), ("source_url", "''")]:
    try:
        conn.execute(f"ALTER TABLE forum_posts ADD COLUMN {col} TEXT DEFAULT {default}")
    except sqlite3.OperationalError:
        pass  # Ya existe
```

Apply the same idiom to `init_reminders` (current body: `core/db.py` lines 257-284, a
bare `CREATE TABLE IF NOT EXISTS` with **no migration step today** — RESEARCH.md Pitfall 2
is exactly this gap). RESEARCH.md's Code Examples section gives the exact target shape:
```python
for col, default in [("paused", "0"), ("version", "1")]:
    try:
        conn.execute(
            f"ALTER TABLE reminders ADD COLUMN {col} INTEGER NOT NULL DEFAULT {default}")
    except sqlite3.OperationalError:
        pass  # already exists
```
If the planner adds a dedicated biweekly anchor column (vs. reusing `run_date`, A1 in
RESEARCH.md Assumptions Log), add it to this same loop.

---

### `core/db.py` — optimistic-concurrency write paths (MODIFIED — model, CRUD)

**Analog:** the same file's current `update_reminder`/`delete_reminder`/`set_next_fire`
(lines 326-366) — extend in place, do not create parallel functions.

**Current shape** (source: `core/db.py` lines 326-343):
```python
def update_reminder(reminder_id: int, **fields):
    cols = [(k, v) for k, v in fields.items() if k in _REMINDER_UPDATABLE]
    if not cols:
        return
    set_clause = ", ".join(k + " = ?" for k, _ in cols)
    values = [v for _, v in cols]
    values.append(reminder_id)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET " + set_clause + " WHERE id = ?", values
        )
```

**Target shape** (source: RESEARCH.md Architecture Patterns, Pattern 1 — exact code to
implement, adds `expected_version` kwarg + `version = version + 1` bump + conditional
`WHERE`, returns `bool` instead of `None` so callers can detect a lost race):
```python
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
```
Apply the same `where`/`expected_version` shape to `delete_reminder` and `set_next_fire`
(RESEARCH.md gives both in full). **Also extend `_REMINDER_UPDATABLE`** (source:
`core/db.py` lines 251-254) to include `"paused"` (and the biweekly anchor field, if a
new column is added rather than reusing `run_date`) — Pitfall 3 in RESEARCH.md: an
omission here makes pause/resume a silent no-op.

**`due_reminders` filter** (source: `core/db.py` lines 351-357, current):
```python
def due_reminders(now_utc_iso: str) -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reminders WHERE next_fire_utc <= ? ORDER BY next_fire_utc",
            (now_utc_iso,)
        ).fetchall()
```
Add `AND paused = 0` to the WHERE clause (Pitfall 3 in RESEARCH.md's Anti-Patterns —
skipping this makes `paused` a cosmetic-only column that still fires every tick).

---

### `cogs/reminders.py` — scheduler write-back race guard (MODIFIED — controller,
event-driven)

**Analog:** the same file's current `_process_due` (lines 693-718)

**Current shape** (source: `cogs/reminders.py` lines 703-718):
```python
for r in db.due_reminders(now.isoformat()):
    try:
        cls = classify_fire(now, datetime.fromisoformat(r["next_fire_utc"]),
                            config.REMINDERS_CATCHUP_GRACE_HOURS)
        if cls != "skip":
            await self._deliver(r, atrasado=(cls == "late"))
        if r["frequency"] == "oneoff":
            db.delete_reminder(r["id"])
        else:
            db.set_next_fire(r["id"], compute_next(r, now).isoformat())
    except Exception:
        log.exception(
            "reminders: fallo al disparar id=%s (los demás continúan)", r["id"])
```
**Target shape** (source: RESEARCH.md Architecture Patterns, Pattern 1 — thread
`expected_version=r["version"]` through both write-back branches, log-and-continue on a
lost race rather than raising — preserves the existing per-row try/except from Pitfall 1):
```python
if r["frequency"] == "oneoff":
    ok = db.delete_reminder(r["id"], expected_version=r["version"])
else:
    ok = db.set_next_fire(r["id"], compute_next(r, now).isoformat(),
                          expected_version=r["version"])
if not ok:
    log.info(
        "reminders: id=%s cambió durante el disparo (versión obsoleta) — "
        "se respeta el estado actual, no se sobrescribe", r["id"])
```
**Staff gate pattern** (reused verbatim for the biweekly Discord-parity choice, source:
`cogs/reminders.py` lines 361-364): every command checks `_is_staff(interaction.user)`
FIRST, before any other validation — apply the same order when adding the `biweekly`
`Choice` to `crear`'s/`editar`'s `@app_commands.choices(frecuencia=[...])` list (lines
351-355, 530-534) and their frequency-dispatch `if/elif` blocks (lines 386-420, 592-619).
**Validator pitfall (RESEARCH.md Pitfall 5):** do NOT reuse the one-off's
`next_oneoff_fire(...) <= now → reject` check for biweekly — D-06 makes a past anchor
valid.

---

### `app/routers/reminders.py` (NEW — controller, request-response CRUD)

**Analog:** `app/main.py` lines 610-777 (`overview_page`, `_module_stub_page`,
`settings_page`, `save_settings`) — the closest existing route-group shape, since no
`app/routers/` package exists yet (RESEARCH.md's "Claude's Discretion note" recommends
starting one now; this mapping assumes that call, but every excerpt below works
unchanged if the planner instead inlines routes into `app/main.py`).

**Imports pattern** (source: `app/main.py` lines 44-59, trimmed to what a reminders
router needs):
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

import config
from app.deps import require_manager
from core import db
from core.reminder_schedule import (
    compute_next, is_imminent, next_biweekly_fire, parse_date, parse_time,
    schedule_summary, valid_day_of_month, valid_weekday,
)
```

**Auth/Guard pattern** (source: `app/main.py` line 654-656, the existing `/reminders`
stub — reuse `Depends(require_manager)` on every route, unchanged dependency):
```python
@app.get("/reminders", response_class=HTMLResponse)
async def reminders_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "reminders", roles)
```
This exact GET route is **replaced** (not added alongside) by the new table+modal page.

**Core CRUD + validate-then-write pattern** (source: `app/main.py::save_settings`, lines
739-777 — the two-pass validate-collect-errors-then-write shape D-14 explicitly carries
forward; adapt the shape, not the settings-specific body):
```python
@app.post("/admin/settings")
async def save_settings(request: Request, ident: dict = Depends(require_owner)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    errors: dict[str, str] = {}
    validated: dict[str, object] = {}
    for key, raw_value in body.items():
        try:
            validated[key] = settings.validate_only(key, raw_value)  # dry-run, no write
        except settings.SettingRejected as exc:
            errors[key] = exc.reason

    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    for key, value in validated.items():
        settings.set(key, value)

    return {"ok": True, "message": _SETTINGS_SAVED_COPY}
```
For reminders: swap `settings.validate_only`/`settings.set` for the schedule-field
validators in `core/reminder_schedule.py` (`parse_time`, `parse_date`, `valid_weekday`,
`valid_day_of_month`) plus a server-side `compute_next`/`next_biweekly_fire`/
`next_oneoff_fire` call to derive `next_fire_utc` — **never trust a client-computed
next-fire value** (RESEARCH.md Security Domain V5). On success, call
`db.add_reminder(...)` / `db.update_reminder(..., expected_version=...)` (thread the
hidden `version` field through per RESEARCH.md's "Symmetric application" note) and return
`{"ok": True}`; on a lost version race, return **409** with a distinct "this reminder
changed, reload" error (RESEARCH.md Open Question 1) rather than re-using the 422
validation-error shape.

**D-13 live-preview endpoint** (new, no direct analog — small `POST`/`GET
/reminders/preview` that takes the in-progress schedule fields and returns
`compute_next(...)`/`next_biweekly_fire(...)` as JSON; called from the modal's Alpine
`recomputePreview()` on every relevant `@input`/`@change`, never reimplemented in JS —
RESEARCH.md Anti-Patterns / Don't Hand-Roll table).

**Error handling pattern:** mirror `save_settings`'s `try/except Exception` around
`request.json()` → 400; mirror the 422-with-errors-map shape for field validation; add
the new 409-version-conflict branch described above. Every route stays wrapped in
`Depends(require_manager)` — no bespoke per-route auth check (RESEARCH.md Security
Domain V4).

---

### `app/templates/reminders.html` (NEW — component, request-response form CRUD)

**Analog:** `app/templates/settings.html` (full file, 211 lines) — RESEARCH.md
Architecture Patterns Pattern 3 names this the exact clone target.

**Template header / x-data pattern** (source: `settings.html` lines 1-15 — note the
**single-quoted `x-data`** rule, load-bearing: `tojson` emits double-quoted JSON and
Jinja escapes `'` to `&#39;`, so a double-quoted attribute would be broken by the data):
```html
{% extends "_dashboard_base.html" %}
{% set roles = roles | default({"is_owner": true, "is_manager": false, "is_editor": false}) %}
{% set active_section = active_section | default("reminders") %}
{% set bot_online = bot_online | default(false) %}
{% block title %}Recordatorios · Reminders{% endblock %}
{% block content %}
<div class="reminders-page"
     x-data='remindersApp({{ rows | tojson }}, {{ names | tojson }})'
     x-cloak>
```

**Module header pattern** (source: `settings.html` lines 16-24, adapted with the
reminders accent):
```html
<div class="mod-hdr" style="--acc: var(--accent-reminders)">
  <span class="i">⏰</span>
  <div>
    <div class="t">Recordatorios · Reminders</div>
    <div class="s">...</div>
  </div>
  <button class="btn" type="button" @click="openCreate()">Nuevo recordatorio · New reminder</button>
</div>
```

**Field-type dispatch pattern** (source: `settings.html` lines 34-119 — the
`x-for`/`x-if` per-field-type template dispatch; reuse this exact `x-if
setting.type === '...'` idiom for the modal's frequency-conditional schedule field, per
D-14 "never show more than one schedule field at a time"):
```html
<template x-if="setting.type === 'int_range'">
  <input type="number" :min="setting.min" :max="setting.max" x-model.number="values[setting.key]" />
</template>
```

**Inline error + toast pattern** (source: `settings.html` lines 114, 121-124 — reused
verbatim, no new toast mechanism per D-14):
```html
<p class="field-error" x-show="errors[setting.key]" x-text="errors[setting.key]"></p>
...
<div class="toast" x-show="toast" x-cloak :data-kind="toastKind" x-text="toast"
     @click="toast=''" role="status" aria-live="polite"></div>
```

**Alpine component `<script>` pattern** (source: `settings.html` lines 129-209 — the
exact `function settingsApp(initial, names, namesFresh) { return {...} }` shape; clone
into `function remindersApp(rows, names) { return {...} }` adding `modalOpen`,
`editingId`, `confirmDelete`, `preview` state per RESEARCH.md Pattern 3):
```javascript
function settingsApp(initial, names, namesFresh) {
  const values = {};
  for (const group of initial) { for (const setting of group.settings) { values[setting.key] = setting.value; } }
  return {
    groups: initial, values, names, namesFresh, saving: false, toast: '', toastKind: 'ok', errors: {},
    async save() {
      this.saving = true; this.toast = ''; this.errors = {};
      try {
        const r = await fetch('/admin/settings', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.serialize()),
        });
        const data = await r.json().catch(() => ({}));
        if (r.ok && data.ok) { this.toastKind = 'ok'; this.toast = data.message || '...'; }
        else { this.toastKind = 'error'; this.errors = data.errors || {}; this.toast = 'Revisa los campos marcados. — Check the highlighted fields.'; }
      } catch (e) { this.toastKind = 'error'; this.toast = 'Error de red · Network error'; }
      finally { this.saving = false; }
    },
  };
}
```

**Role-chip pattern reused for the reactions chip-input** (source: `settings.html` lines
60-79, the `role_list` field type — reuse this flex-wrap chip-list shape for the D-12
emoji reactions input, cap 6 instead of unbounded):
```html
<div class="role-chip-list" x-show="roleIds(values[setting.key]).length">
  <template x-for="id in roleIds(values[setting.key])" :key="id">
    <div class="role-chip" :style="...">
      <span class="role-chip-name" x-text="..."></span>
    </div>
  </template>
</div>
```

**Searchable combobox (D-11):** no direct existing analog (settings.html's snowflake
field is a plain typed-ID input, not a searchable dropdown) — this is a genuinely new
component shape per UI-SPEC.md, built from the same `.resolved-name`/`--color-surface-2`
tokens `settings.html`'s snowflake resolved-name pill already uses (lines 44-56). No
Hand-Roll violation here; the *tokens* are reused even though the *shape* is new.

---

### `app/static/dashboard.css` (MODIFIED — config, transform)

**Analog:** the same file's existing `.settings-*`/`.role-chip*`/`.mod-hdr`/`.toast`
blocks (lines 171-347)

**Tokens available to reuse directly** (source: `app/static/dashboard.css` lines 10-64):
```css
--color-bg: #0f1115;
--color-surface: #161a21; --color-surface-2: #1d222b; --color-surface-3: #252b36;
--color-border: #262c37; --color-border-strong: #333b49;
--color-text: #e6e9ef; --color-text-muted: #8b93a3; --color-text-faint: #5c6474;
--color-primary: #4f7cff; --color-danger: #f0435a; --color-success: #2dd4a7;
--color-warning: #ffb020;
--accent-reminders: #38bdf8;
--space-1..16 (4/8/12/16/24/32/48/64px); --radius-sm/md/lg/full;
```

**Card/table base (reuse unchanged)** (source: lines 172-191):
```css
.card { background: var(--color-surface); border: 1px solid var(--color-border);
        border-radius: var(--radius-lg); padding: var(--space-6); margin-bottom: var(--space-6); }
table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
td { padding: var(--space-2); border-bottom: 1px solid var(--color-border); vertical-align: middle; }
.empty { text-align: center; color: var(--color-text-faint); padding: var(--space-8); font-size: var(--text-sm); }
```

**Resolved-name pill (reuse for the D-13 next-fire preview + D-08 channel/role names)**
(source: lines 298-308):
```css
.resolved-name {
  display: inline-flex; align-items: center; gap: var(--space-2);
  padding: var(--space-1) var(--space-3); font-size: var(--text-sm); color: var(--color-text);
  background: var(--color-surface-2); border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
}
```

**New block to add** (following the same per-module-block convention Phase 4 used for
`.settings-*`): `.status-badge` (active/paused variants per UI-SPEC), `.row-actions`
(ghost icon buttons), `.reminder-modal`/`.confirm-modal` (overlay + `.card`-derived
surface), `.combobox`/`.combobox-list` (new shape, built from `--color-surface-2`/
`--color-border`/`--font-sans` tokens), `.chip-input` (reuse `.role-chip-list` shape).
No new token — every value must resolve to an existing `--space-*`/`--color-*`/
`--radius-*` variable (UI-SPEC.md's locked "no new token" rule).

---

### `tests/test_reminder_schedule.py` (NEW — test, transform)

**Analog:** `tests/test_reminders_cog.py` lines 1-440 (the pre-extraction schedule-math
test section — same assertions, new import path)

Move (or duplicate then delete from the old file) every test currently calling
`reminders.next_weekly_fire(...)`/`reminders.next_monthly_fire(...)`/etc. to import from
`core.reminder_schedule` instead; add new `test_next_biweekly_fire_*` cases (past-anchor
validity, DST-window correctness, 14-day cadence) and `test_is_imminent_*` cases (within/
outside the 90s threshold, past AND future skew) following the existing test naming
convention (`test_<function>_<scenario>`).

---

### `tests/test_db_reminders_crud.py` (NEW — test, CRUD)

**Analog:** `tests/test_action_queue_concurrency.py` (tmp_path DB-isolation idiom) +
`core/db.py`'s reminder functions directly (no existing dedicated db-level reminder test
file — today's coverage is only indirect via `test_reminders_cog.py`'s mocks)

**Deterministic concurrent-edit test (D-17's required proof)** — this is the load-bearing
new test for REM-03, and RESEARCH.md provides the exact body to implement (source:
RESEARCH.md Code Examples, "Deterministic concurrent-edit test"):
```python
def test_scheduler_writeback_never_clobbers_concurrent_panel_edit(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "race.db"), raising=False)
    db.init_reminders()
    rid = db.add_reminder(
        name="Junta", frequency="weekly", weekday=0, hour=9, minute=0,
        channel_id=1, message="x", created_by=1,
        next_fire_utc=NOW.isoformat())

    stale_row = db.due_reminders(NOW.isoformat())[0]
    assert stale_row["version"] == 1

    panel_next_fire = "2026-07-10T09:00:00+00:00"
    assert db.update_reminder(rid, weekday=4, next_fire_utc=panel_next_fire) is True

    stale_next_fire = compute_next(stale_row, NOW).isoformat()
    ok = db.set_next_fire(rid, stale_next_fire, expected_version=stale_row["version"])
    assert ok is False

    final = db.get_reminder(rid)
    assert final["next_fire_utc"] == panel_next_fire
    assert final["weekday"] == 4
```
This is deliberately synchronous (no threads, no `time.sleep`) — the version column makes
the race deterministic to reproduce, per RESEARCH.md's rationale for choosing this over
the threaded harness `test_action_queue_concurrency.py` uses for the *action queue*'s
different (queue-claim) race.

**Migration test** (new, no direct analog beyond the pitfall description): create a
`reminders` table via the OLD (pre-`paused`/`version`) schema string, then call the new
`init_reminders()` and assert the columns now exist with the documented defaults — proves
Pitfall 2 (existing-install migration) doesn't regress.

---

### `tests/test_app_reminders.py` (NEW — test, request-response)

**Analog:** `tests/test_app_settings.py` (full file — `client` fixture, gate tests,
validate-then-write assertions) + `tests/test_app_actions.py` (the `require_manager`
override idiom, since reminders is manager-gated like actions, not owner-gated like
settings)

**Fixture pattern** (source: `tests/test_app_settings.py` lines 26-43, adapted to
`require_manager` per `tests/test_app_actions.py` lines 17-37):
```python
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "reminders.db"), raising=False)
    db.init_reminders()
    app.dependency_overrides[require_manager] = _manager_override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

**Gate test pattern** (source: `tests/test_app_settings.py` lines 47-60 — assert 403 +
no data leak without the override):
```python
def test_get_reminders_non_manager_gets_403(monkeypatch, tmp_path):
    ...
    with TestClient(app) as c:
        resp = c.get("/reminders", headers={"Accept": "application/json"})
    assert resp.status_code == 403
```

**Manager override + POST pattern** (source: `tests/test_app_actions.py` lines 31-37,
60-70):
```python
def _manager_override():
    return {"discord_id": "2", "is_owner": False, "is_manager": True, "is_editor": False}

def test_create_reminder_persists(client):
    resp = client.post("/reminders", json={...})
    assert resp.status_code == 200
    assert db.list_reminders()  # persisted via the real sqlite store, not a mock
```

---

## Shared Patterns

### Manager-tier gate (all new FastAPI reminders routes)
**Source:** `app/deps.py::require_manager` (lines 174-186), unchanged
**Apply to:** every route in `app/routers/reminders.py` (or the equivalent inline
`app/main.py` routes) — list/create/edit/delete/pause/resume/preview, no exceptions
(RESEARCH.md Security Domain V4).
```python
async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```

### ALTER TABLE migration idiom (schema changes to an existing table)
**Source:** `core/db.py::init_db` lines 36-40
**Apply to:** `init_reminders`'s new `paused`/`version` columns (and any biweekly anchor
column) — the ONLY correct way to evolve a table `CREATE TABLE IF NOT EXISTS` won't touch.

### Explicit column allowlist (`_REMINDER_UPDATABLE`)
**Source:** `core/db.py` lines 251-254
**Apply to:** any new updatable field (`paused`, biweekly anchor) — SQL-injection-by-
column-name guard (T-08-03 discipline); update_reminder silently no-ops on an unlisted key.

### Validate-then-write two-pass form submission
**Source:** `app/main.py::save_settings` lines 739-777
**Apply to:** the reminders create/edit POST handler — collect ALL field errors before any
write; a mixed valid/invalid submission persists nothing (D-14, locked).

### Alpine validate-then-write component shape
**Source:** `app/templates/settings.html` (full file, especially the `<script>` block
lines 129-209)
**Apply to:** `reminders.html`'s `remindersApp(...)` Alpine component — same
`values`/`errors`/`toast`/`saving` state shape, same single-quoted `x-data` rule.

### Optimistic-concurrency version column
**Source:** new pattern (RESEARCH.md Architecture Patterns Pattern 1) — first use of this
idiom in the repo, but modeled directly on the repo's existing SQLite-conditional-write
style (`INSERT OR REPLACE`/`ON CONFLICT` already used elsewhere in `core/db.py`, e.g.
`increment_view` lines 510-517, `set_presence` lines 545-549).
**Apply to:** `update_reminder`/`delete_reminder`/`set_next_fire` (both the scheduler's
write-back AND the panel's own write paths, per the "Symmetric application" note) —
`WHERE id = ? AND version = ?`, 0-rows-affected means a lost race, never assume success.

### Discord names cache for readable names
**Source:** `core/db.py::get_discord_names` (lines 750-755), consumed today by
`settings.html`'s `resolved-name`/`role-chip` rendering (lines 44-56, 60-79)
**Apply to:** the reminders table's channel/mention-role columns (D-08) and the modal's
searchable combobox (D-11) — never a live Discord REST call from the app process.

## No Analog Found

None — every file in this phase has a strong existing analog (this phase is explicitly
scoped by RESEARCH.md as "almost entirely wire it up to a second call site, not invent a
new algorithm"). The only genuinely new *component shape* (searchable combobox, D-11) is
still built entirely from existing CSS tokens (see `app/templates/reminders.html`
section above) — flagged there, not listed as a gap.

## Metadata

**Analog search scope:** `cogs/reminders.py`, `core/db.py`, `app/main.py`, `app/deps.py`,
`app/templates/settings.html`, `app/static/dashboard.css`, `tests/test_reminders_cog.py`,
`tests/test_app_settings.py`, `tests/test_app_actions.py`, `tests/test_action_queue_concurrency.py`
**Files scanned:** 10 (all read in full or via targeted grep+range reads; no file in this
set exceeds ~1100 lines, so no file required more than 2-3 non-overlapping reads)
**Pattern extraction date:** 2026-07-23
