# Phase 9: Meetings Browser + Re-publish - Pattern Map

**Mapped:** 2026-07-29
**Files analyzed:** 13 (7 new, 6 modified)
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `core/db.py` (add `meetings` table + CRUD + `dedupe_key` column) | model / migration | CRUD | `core/db.py::init_gallery_state`/`init_reminders` (same file, sibling idiom) | exact |
| `core/action_queue.py` (extend `enqueue_deduped`) | service | event-driven (queue) | `core/action_queue.py::enqueue_deduped` (same file, additive change) | exact |
| `cogs/action_queue_worker.py` (add `meeting_republish` dispatch) | controller (bot-side dispatcher) | event-driven | `cogs/action_queue_worker.py::_handle_jinxxy_sync` | exact |
| `cogs/meeting.py::_publish` (persist row on publish) | service (bot event handler) | CRUD + file-I/O | `cogs/meeting.py::_publish` (same file, add persistence) + `cogs/gallery.py::_publish`'s try/except-around-log_activity idiom | exact |
| `cogs/meeting.py::_republish` (new method — archived-thread edit) | service | request-response (Discord REST) | discord.py API directly (no repo analog); dispatch delegation shape from `_handle_jinxxy_sync` → `jinxxy_cog._run_sync_guarded` | role-match |
| `cogs/meeting.py::on_ready`/`_backfill_meetings` (new — startup backfill) | service (bot startup task) | batch / event-driven | `cogs/gallery.py::on_ready` + `_backfill` (D-20 idiom) | exact |
| `cogs/meeting.py` (attendee snapshot in `_teardown`) | service | transform | `cogs/meeting.py::MeetingSession`/`_teardown` (same file) | exact |
| `app/routers/meetings.py` (list + detail + republish routes) | controller (FastAPI router) | request-response | `app/routers/jinxxy.py` (page+status+POST shape) + `app/routers/reviews.py` (`{id}` path param + 404) | exact |
| `app/templates/meetings.html` (list page) | component (Jinja2 template) | request-response | `app/templates/jinxxy.html` | exact |
| `app/templates/meeting_detail.html` (detail/editor page) | component (Jinja2 template) | request-response | `app/templates/jinxxy.html` (Alpine state machine) + `dashboard.css` `.reminder-modal textarea`/`.role-chip-list` idioms | role-match |
| `app/main.py` (remove `/meetings` stub, register router) | config (route registration) | request-response | `app/main.py` lines 64-67 / 331-334 (gallery/jinxxy/reminders/reviews includes) | exact |
| `tests/test_db_meetings.py` (new) | test | CRUD | `tests/test_action_queue_dedupe.py` (tmp-db unit test shape) | role-match |
| `tests/test_meeting_cog.py` (new) | test | event-driven | `tests/test_action_queue_cog.py` (mocked discord objects, cog construction) | exact |
| `tests/test_app_meetings.py` (new) | test | request-response | `tests/test_app_jinxxy.py` (FastAPI TestClient fixture shape) | exact |
| `tests/test_action_queue_dedupe.py` (extend) | test | event-driven | same file — add a per-`dedupe_key` case beside existing kind-only cases | exact |
| `tests/test_action_queue_cog.py` (extend) | test | event-driven | same file — add a `meeting_republish` case to `_DISPATCH_CASES` | exact |

---

## Pattern Assignments

### `core/db.py` (model, CRUD) — meetings table + queries

**Analog:** `core/db.py::init_gallery_state` (lines 67-81), `init_reminders` (lines 257-292, esp. the ADD-COLUMN loop), `init_action_queue` (lines 825-846), `log_activity` (lines 798-813)

**Connection idiom** (lines 1-20, already shared — do not re-declare):
```python
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    return conn
```

**New-table idiom to copy** (`init_gallery_state`, lines 67-81 — single `CREATE TABLE IF NOT EXISTS` inside `with _get_conn() as conn:`, called from the cog's `__init__`, NOT from `init_db()`):
```python
def init_gallery_state():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gallery_state (
                id                        INTEGER PRIMARY KEY CHECK (id = 1),
                last_processed_message_id INTEGER
            )
        """)
```

**ADD-COLUMN idiom to copy** (`init_reminders`, lines 285-292 — defensive `try/except sqlite3.OperationalError: pass` loop for bolted-on columns on an already-deployed db; this is exactly the mechanism the `dedupe_key` column on `action_queue` should use):
```python
for col, default in [("paused", "0"), ("version", "1")]:
    try:
        conn.execute(
            f"ALTER TABLE reminders ADD COLUMN {col} "
            f"INTEGER NOT NULL DEFAULT {default}"
        )
    except sqlite3.OperationalError:
        pass  # Ya existe
```
Apply the same loop to `init_action_queue` for `dedupe_key TEXT`, plus a sibling index:
```python
conn.execute("CREATE INDEX IF NOT EXISTS idx_action_queue_dedupe_key ON action_queue(dedupe_key)")
```

**`meetings` table schema + insert/lookup — copy verbatim from RESEARCH.md's Code Examples** (already vetted against the ADD-COLUMN/new-table idiom above):
```python
def init_meetings():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tema               TEXT    NOT NULL DEFAULT '',
                started_at         TEXT    NOT NULL,   -- ISO 8601 UTC
                ended_at           TEXT,
                attendees_json     TEXT    NOT NULL DEFAULT '[]',
                notes_json         TEXT    NOT NULL DEFAULT '[]',
                transcript         TEXT,                -- NULL = unavailable (D-12 gap)
                summary            TEXT    NOT NULL DEFAULT '',
                thread_id          INTEGER,              -- NULL = text-channel fallback (D-14)
                starter_message_id INTEGER,
                created_at         TEXT    NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_thread_id ON meetings(thread_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_meetings_started_at ON meetings(started_at)")


def insert_meeting(tema, started_at, ended_at, attendees, notes, transcript, summary,
                    thread_id=None, starter_message_id=None) -> int:
    with _get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO meetings
                (tema, started_at, ended_at, attendees_json, notes_json,
                 transcript, summary, thread_id, starter_message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tema, started_at, ended_at, json.dumps(attendees), json.dumps(notes),
              transcript, summary, thread_id, starter_message_id,
              datetime.now(timezone.utc).isoformat()))
        return cur.lastrowid


def get_meeting_by_thread_id(thread_id: int) -> sqlite3.Row | None:
    """Existence check for the idempotent backfill (D-13) — plain SELECT, NOT an
    ON CONFLICT target (see RESEARCH.md Anti-Patterns re: partial-index conflict targets)."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT id FROM meetings WHERE thread_id = ?", (thread_id,)
        ).fetchone()
```
Add `get_meeting(meeting_id)`, `list_meetings()` (reverse-chronological, mirror `list_reminders`'s `ORDER BY` idiom at `core/db.py` line 318-323), and `update_meeting_summary(meeting_id, summary)` (single-column `UPDATE ... WHERE id = ?`, mirrors `clear_jinxxy_sync_running`'s targeted-update shape at lines 756-765).

**Activity-log reuse** (already invoked by `_publish` — do not re-derive, D-07 re-publish attribution reuses this exact call shape, lines 798-813):
```python
def log_activity(event_type: str, message: str, keep_last: int = 500):
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

---

### `core/action_queue.py` (service, event-driven) — `dedupe_key`-extended `enqueue_deduped`

**Analog:** same file, current `enqueue_deduped` (lines 50-73)

**Current (kind-only dedupe, to be generalized — Jinxxy caller keeps working unmodified):**
```python
@_retry_on_locked
def enqueue_deduped(kind: str, payload: dict, requested_by: str) -> int:
    with db._get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM action_queue WHERE kind = ? "
            "AND status IN ('pending', 'claimed') ORDER BY id LIMIT 1",
            (kind,),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO action_queue "
            "(kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso()),
        )
        return cur.lastrowid
```

**New signature (additive, backward compatible — copy from RESEARCH.md Pattern 1):**
```python
@_retry_on_locked
def enqueue_deduped(kind: str, payload: dict, requested_by: str,
                     dedupe_key: str | None = None) -> int:
    key = dedupe_key or kind
    with db._get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM action_queue WHERE dedupe_key = ? "
            "AND status IN ('pending', 'claimed') ORDER BY id LIMIT 1",
            (key,),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO action_queue "
            "(kind, payload_json, status, requested_by, requested_at, dedupe_key) "
            "VALUES (?, ?, 'pending', ?, ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso(), key),
        )
        return cur.lastrowid
```
**Critical:** `enqueue_deduped("jinxxy_sync", {...}, requested_by)` (the existing caller in `app/routers/jinxxy.py` line 118-123) needs ZERO changes — `dedupe_key` defaults to `kind`, same global-by-kind behavior. The meetings caller passes `dedupe_key=f"meeting_republish:{meeting_id}"`.

---

### `cogs/action_queue_worker.py` (controller, event-driven) — `meeting_republish` dispatch entry

**Analog:** `_handle_jinxxy_sync` (lines 181-209), the `_dispatch` dict (lines 25-32), `_run_once` (lines 42-62)

**Dispatch dict registration pattern** (lines 25-32):
```python
self._dispatch = {
    "noop": self._handle_noop,
    "gallery_publish": self._handle_gallery_publish,
    "gallery_remove": self._handle_gallery_remove,
    "review_publish": self._handle_review_publish,
    "review_remove": self._handle_review_remove,
    "jinxxy_sync": self._handle_jinxxy_sync,
}
```
Add `"meeting_republish": self._handle_meeting_republish,` — **`kind` stays the literal string, never encode the meeting id into it** (RESEARCH.md Pattern 2 — the dict lookup at line 54 `self._dispatch.get(row["kind"])` would break).

**Delegate-to-cog pattern to copy** (`_handle_jinxxy_sync`, lines 181-198 — resolve cog by its `name=` GroupCog kwarg, not class name; missing-cog raises a bilingual `RuntimeError`):
```python
async def _handle_jinxxy_sync(self, payload: dict) -> dict:
    actor_name = payload.get("actor_name") or None
    try:
        jinxxy_cog = self.bot.get_cog("Jinxxy")
        if jinxxy_cog is None:
            raise RuntimeError(
                "JinxxyCog no está cargado · JinxxyCog is not loaded"
            )
        result = await jinxxy_cog._run_sync_guarded(source="panel", actor_name=actor_name)
    except Exception as exc:
        log.exception("action_queue: jinxxy_sync falló")
        raise RuntimeError(sync_error_category(exc)) from exc
    ...
```
**New handler (copy from RESEARCH.md Code Examples — note "Meeting" is the GroupCog `name=` kwarg in `cogs/meeting.py`, not the class name `MeetingCog`):**
```python
async def _handle_meeting_republish(self, payload: dict) -> dict:
    meeting_id = int(payload["meeting_id"])
    meeting_cog = self.bot.get_cog("Meeting")
    if meeting_cog is None:
        raise RuntimeError("MeetingCog no está cargado · MeetingCog is not loaded")
    return await meeting_cog._republish(meeting_id)
```
**Error handling pattern (shared):** `_run_once` (lines 53-62) already wraps every handler in `try/except Exception` → `action_queue.fail(row["id"], str(exc))` — no per-handler try/except needed beyond what `_handle_meeting_republish` itself does; `discord.Forbidden`/`discord.NotFound` bubble up naturally and land here (mirrors `_fetch_message`'s `NotFound → RuntimeError` translation at lines 84-91, reuse that exact idiom inside `_republish` for a "message no longer exists" case).

---

### `cogs/meeting.py::_publish` (service, CRUD+file-I/O) — persist row on publish

**Analog:** same file, current `_publish` (lines 244-295); `cogs/gallery.py`'s try/except-around-log_activity idiom already present at lines 283-289 of `meeting.py` itself

**Current forum-create + activity-log shape (lines 274-295 — only `created.thread` is kept today, D-02 requires ALSO keeping `created.message`):**
```python
forum = self.bot.get_channel(config.MEETINGS_FORUM_ID)
if isinstance(forum, discord.ForumChannel):
    try:
        created = await forum.create_thread(name=title[:100], embed=embed, file=_md_file())
        if session.text_channel and session.text_channel.id != created.thread.id:
            await session.text_channel.send(f"📋 Acta publicada en el foro: {created.thread.mention}")
        try:
            await asyncio.to_thread(
                db.log_activity, "meeting_posted",
                f"Acta de reunión publicada: {title} / Meeting minutes posted: {title}")
        except Exception:
            log.exception("meeting: no pude registrar la actividad de publicación (%s)", title)
        return
    except discord.HTTPException as e:
        log.error("No se pudo publicar el acta en el foro: %s", e)

# Fallback: publicar en el canal donde se usó /parar
await session.text_channel.send(embed=embed, file=_md_file())
```
**Modification (D-14 — persist on BOTH paths, forum ids only when forum succeeded):** capture `created.thread.id` + `created.message.id` (RESEARCH.md Pattern 5) and call `db.insert_meeting(...)` via `asyncio.to_thread` right beside the existing `db.log_activity` call on the forum-success path, AND again (with `thread_id=None, starter_message_id=None`) on the text-channel-fallback path after `session.text_channel.send(embed=embed, file=_md_file())`. Wrap each insert in the same defensive `try/except Exception: log.exception(...)` idiom already used for `log_activity` — persistence must never abort the publish.

**Attendee snapshot (Pitfall 5 — new, no direct repo analog beyond the `MeetingSession`/`_teardown` shape already in this file, lines 60-70 and 155-165):** snapshot `[m.display_name for m in session.voice_channel.members if not m.bot]` at the START of `_teardown` (before `stop_listening()`/`disconnect()`), union with `session.recorder.users` keys, store on `session` for `_publish` to read.

---

### `cogs/meeting.py::_republish` (service, request-response/Discord REST) — archived-thread defensive edit

**Analog:** discord.py 2.5.2 API directly (no repo precedent for archived-thread handling); dispatch delegation shape mirrors `_handle_jinxxy_sync` → `jinxxy_cog._run_sync_guarded` (`cogs/action_queue_worker.py` line 195)

**Pattern 3 (read mutation target from DB, never trust payload) + Pattern 4 (unarchive → edit → restore) — copy from RESEARCH.md Code Examples:**
```python
async def _republish(self, meeting_id: int) -> dict:
    row = await asyncio.to_thread(db.get_meeting, meeting_id)  # never trust payload for target ids
    if row is None or row["thread_id"] is None or row["starter_message_id"] is None:
        raise RuntimeError("esta reunión no tiene una publicación en el foro · no forum post to edit")

    channel = self.bot.get_channel(row["thread_id"]) or await self.bot.fetch_channel(row["thread_id"])
    if not isinstance(channel, discord.Thread):
        raise RuntimeError("el hilo ya no existe · thread no longer exists")

    embed = discord.Embed(
        title=(f"📝 ... {row['tema']}")[:256],           # rebuild from STORED tema/started_at, never "now"
        description=(row["summary"] or "*Sin resumen.*")[:4096],
        color=EMBED_COLOR,
    )
    # ... re-add notes field with the SAME [:1024] truncation as the original _publish

    was_archived = channel.archived
    if was_archived:
        await channel.edit(archived=False)
    try:
        partial = channel.get_partial_message(row["starter_message_id"])
        await partial.edit(embed=embed)
    finally:
        if was_archived:
            await channel.edit(archived=True)   # D-07: restore silently, no announcement

    await asyncio.to_thread(
        db.log_activity, "meeting_republished",
        f"Acta editada por {actor_name}: {row['tema']} / Meeting minutes edited by {actor_name}")
    return {"ok": True}
```
**Anti-patterns to avoid (RESEARCH.md):** do not regenerate title/notes from `datetime.now()`; do not skip the `[:4096]`/`[:1024]` truncation on rebuild — both must exactly mirror the original `_publish` embed-building code (lines 252-259 of this file) or the edit PATCH can 400.

---

### `cogs/meeting.py::on_ready`/`_backfill_meetings` (service, batch/event-driven) — startup backfill

**Analog:** `cogs/gallery.py::on_ready` (lines 362-371) + `_backfill` (lines 373-401)

**Exact idiom to copy:**
```python
# cogs/gallery.py lines 108-111 (constructor guard)
def __init__(self, bot: commands.Bot):
    self.bot = bot
    self._backfilled = False   # startup reconcile runs once (on_ready can re-fire)
    db.init_gallery_state()

# cogs/gallery.py lines 362-371 (guarded, swallowed-exception trigger)
@commands.Cog.listener()
async def on_ready(self):
    """Run the startup reconcile once (``on_ready`` can re-fire on reconnects)."""
    if self._backfilled:
        return
    self._backfilled = True
    try:
        await self._backfill()
    except Exception:
        log.exception("gallery startup backfill failed")
```
Apply verbatim to `MeetingCog.__init__` (`self._backfilled = False`, `db.init_meetings()`) and add an `on_ready` listener calling `_backfill_meetings()` wrapped the same way. Inside `_backfill_meetings`: walk `forum.threads` + `forum.archived_threads(limit=None)`, existence-check each via `db.get_meeting_by_thread_id(thread.id)` (D-13 idempotent upsert-by-thread-id — **use the plain `SELECT` existence check, NOT an `ON CONFLICT` partial-index target**, per RESEARCH.md Anti-Patterns), extract summary from the embed + best-effort `.md` attachment download (D-12), and call `db.insert_meeting(...)` for anything absent.

---

### `app/routers/meetings.py` (controller, request-response) — list + detail + republish routes

**Analog:** `app/routers/jinxxy.py` (page/status/POST shape, full file) + `app/routers/reviews.py` (`{message_id}` path param + 404, lines 57-97)

**Imports pattern** (`jinxxy.py` lines 1-14):
```python
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.deps import bot_online, require_manager
from core import action_queue, db

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))
```

**Manager-gated page pattern** (`jinxxy.py` lines 74-104 — asset cache-buster, template-exists fallback to `module_stub.html`, template context shape):
```python
@router.get("/meetings", response_class=HTMLResponse)
async def meetings_page(request: Request, roles: dict = Depends(require_manager)):
    rows = await run_in_threadpool(db.list_meetings)   # reverse-chron (D-08)
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        asset_v = 0
    return templates.TemplateResponse(
        request, "meetings.html",
        {
            "roles": roles, "active_section": "meetings", "asset_v": asset_v,
            "bot_online": await bot_online(),
            "rows": rows,
            "section_label": "Reuniones · Meetings", "icon": "🎙",
            "accent": "var(--accent-meetings)",
        },
    )
```

**`{id}` path param + 404 pattern** (`reviews.py` lines 68-83 — copy this shape for `GET /meetings/{id}`, raising `HTTPException(404, ...)` when the row is absent, exactly like `_enqueue_review_action`'s `row is None` guard):
```python
async def _enqueue_review_action(message_id: int, kind: str, roles: dict) -> JSONResponse:
    row = await run_in_threadpool(db.get_reviews_queue_row, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="reseña no encontrada · review not found")
    action_id = await run_in_threadpool(
        action_queue.enqueue, kind, {"message_id": message_id}, str(roles["discord_id"]),
    )
    return JSONResponse({"id": action_id})
```

**Republish POST — dedupe_key-scoped enqueue (copy from RESEARCH.md Code Examples, extends `jinxxy.py`'s `trigger_jinxxy_sync` shape at lines 113-124):**
```python
@router.post("/meetings/{meeting_id}/republish")
async def republish_meeting(meeting_id: int, request: Request,
                             roles: dict = Depends(require_manager)):
    body = await request.json()
    new_summary = (body.get("summary") or "").strip()
    await run_in_threadpool(db.update_meeting_summary, meeting_id, new_summary)
    actor_name = roles.get("username") or str(roles["discord_id"])
    action_id = await run_in_threadpool(
        action_queue.enqueue_deduped,
        "meeting_republish",
        {"meeting_id": meeting_id, "actor_name": actor_name},
        str(roles["discord_id"]),
        dedupe_key=f"meeting_republish:{meeting_id}",
    )
    return JSONResponse({"id": action_id})
```
**V5 input validation note (RESEARCH.md Security Domain):** strip + cap `new_summary` length before it reaches sqlite (Discord's 4096-char embed limit is the real backstop, applied again at rebuild time in `_republish`).

---

### `app/templates/meetings.html` (component, request-response) — list page

**Analog:** `app/templates/jinxxy.html` (full file, 309 lines)

**Page shell + Alpine data binding pattern** (lines 1-33):
```jinja
{% extends "_dashboard_base.html" %}
{% set roles = roles | default({}) %}
{% set active_section = active_section | default("jinxxy") %}
...
{% block content %}
<div class="jinxxy-page" x-data='jinxxySyncApp({{ sync | tojson }}, {{ products | tojson }})' x-cloak>
  <div class="mod-hdr" style="--acc: var(--accent-jinxxy)">
    <span class="i">🛍</span>
    <div>
      <div class="t">Tienda Jinxxy · Jinxxy Store</div>
      <div class="s">...</div>
    </div>
  </div>
```
Adapt to `--acc: var(--accent-meetings)`, icon `🎙`, title "Reuniones · Meetings" (per UI-SPEC).

**Table + empty-state pattern** (lines 77-117 — this is THE structural template for the meetings list table: `.card` wrapper, `<table>` with `x-show="products.length"`, per-row `<template x-for>`, `.empty` fallback):
```jinja
<section class="card">
  <table x-show="products.length">
    <thead><tr><th>...</th></tr></thead>
    <tbody>
      <template x-for="p in products" :key="p.checkout_url">
        <tr> ... </tr>
      </template>
    </tbody>
  </table>
  <div class="empty" x-show="!products.length">
    <div class="h">Aún no hay productos sincronizados · No synced products yet</div>
  </div>
</section>
```
Per UI-SPEC: columns are Topic / Date-time / Attendees (count) / Summary preview (`-webkit-line-clamp: 2`); each row wraps an `<a href="/meetings/{{ row.id }}">` (server-rendered `{% for %}` is sufficient here — no Alpine needed for a static reverse-chron table, unlike jinxxy's live-polling sync card).

---

### `app/templates/meeting_detail.html` (component, request-response) — detail/editor page

**Analog:** `app/templates/jinxxy.html`'s Alpine state machine (lines 122-307, esp. `runSync`/`pollAction`/`stateKind`), `dashboard.css`'s `.reminder-modal textarea` + `.role-chip-list` idioms

**Alpine save+poll state machine to copy almost verbatim** (jinxxy.html lines 248-299 — `runSync`/`pollAction`/`stopActionPoll`, renamed to `saveSummary`/republish semantics):
```javascript
async runSync() {
  if (this.isBusy()) return;
  this.stopActionPoll();
  this.status = 'pending'; this.error = ''; this.result = null; this.botOnline = true;
  try {
    const response = await fetch('/jinxxy/sync', { method: 'POST', headers: { 'Accept': 'application/json' } });
    if (!response.ok) throw new Error('network');
    const body = await response.json();
    this.actionId = body.id;
    await this.pollAction();
  } catch (error) {
    this.actionId = null; this.status = 'idle';
    this.toast = 'Error de red · Network error';
  }
},

async pollAction() {
  if (!this.actionId || !this.isPending()) return;
  try {
    const response = await fetch('/api/actions/' + this.actionId, { headers: { 'Accept': 'application/json' } });
    if (!response.ok) throw new Error('network');
    const body = await response.json();
    this.status = body.status; this.error = body.error || ''; this.result = body.result || null;
    this.botOnline = body.bot_online;
    if (this.isPending()) { this.pollTimer = setTimeout(() => this.pollAction(), 1500); return; }
  } catch (error) {
    this.toast = 'Error de red · Network error';
    if (this.actionId && this.isPending()) this.pollTimer = setTimeout(() => this.pollAction(), 1500);
  }
},
```
For the meetings detail page's POST body must carry `{summary: this.summaryText}` to `/meetings/{id}/republish` (differs from jinxxy's bodyless POST — mirror `reminders.html`'s form-body-POST idiom instead of jinxxy's parameterless one, since `edit_reminder`'s router already validates a JSON body shape at `app/routers/reminders.py` lines 361-382).

**Textarea styling to reuse** (`dashboard.css` lines 482-503, `.reminder-modal textarea` — apply the same class/selector shape to the summary editor, not a new one):
```css
.reminder-modal textarea {
  width: 100%; padding: var(--space-3);
  border: 1px solid var(--color-border-strong); border-radius: var(--radius-sm);
  background: var(--color-surface-2); color: var(--color-text); font: inherit; outline: none;
}
.reminder-modal textarea { resize: vertical; }
.reminder-modal textarea:focus { border-color: var(--color-primary); }
```

**Attendee chip styling to reuse** (`dashboard.css` lines 319-327, `.role-chip-list`/`.role-chip` — per UI-SPEC note 3, reuse directly for attendee name chips):
```css
.role-chip-list { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.role-chip {
  display: flex; flex-direction: column; gap: var(--space-1);
  min-width: 0; padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border); border-left: 3px solid var(--color-border-strong);
  border-radius: var(--radius-md); background: var(--color-surface-2);
}
.role-chip-name { color: var(--color-text); font-size: var(--text-sm); }
```

**Warning-badge idiom for "transcript unavailable" / "no forum post" states** (`dashboard.css` lines 329-339, `.settings-cache-banner` — border-left + icon + copy, warning color):
```css
.settings-cache-banner {
  display: flex; align-items: center; gap: var(--space-4);
  margin-bottom: var(--space-6); padding: var(--space-4);
  border: 1px solid var(--color-border); border-left: 3px solid var(--color-warning);
  border-radius: var(--radius-md); background: var(--color-surface);
}
.settings-cache-icon { color: var(--color-warning); font-size: var(--text-lg); }
```

**Status badge idiom for the action-proof-status card** (`dashboard.css` lines 219-231, already generic — reuse unchanged, do not fork):
```css
.action-proof-status {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border); border-left: 3px solid var(--color-warning);
  border-radius: var(--radius-md); background: var(--color-surface-2);
}
.action-proof-status[data-state="ok"] { border-left-color: var(--color-success); }
.action-proof-status[data-state="failed"] { border-left-color: var(--color-danger); }
```

---

### `app/main.py` (config, request-response) — remove stub, register router

**Analog:** same file, existing router includes (lines 64-67, 331-334) and `_MODULE_SECTIONS`/`_module_stub_page` (lines 513-521, 632-647)

**Current router-include pattern to copy** (lines 64-67, 331-334):
```python
from app.routers import gallery as gallery_router
from app.routers import jinxxy as jinxxy_router
from app.routers import reminders as reminders_router
from app.routers import reviews as reviews_router
...
app.include_router(gallery_router.router)
app.include_router(jinxxy_router.router)
app.include_router(reminders_router.router)
app.include_router(reviews_router.router)
```
Add `from app.routers import meetings as meetings_router` and `app.include_router(meetings_router.router)` alongside these four.

**MUST DELETE — the existing stub (Pitfall 4, lines 645-647), or Starlette's first-match-wins routing means the stub silently wins:**
```python
@app.get("/meetings", response_class=HTMLResponse)
async def meetings_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "meetings", roles)
```
`_MODULE_SECTIONS["meetings"]` entry (line 520) may be left in place — it becomes dead the same way `"gallery"`/`"reviews"`/`"reminders"`/`"jinxxy"` entries already are (harmless pre-existing debt, not this phase's regression to fix). **Registration order matters:** `include_router(meetings_router.router)` must be added at the same point as the other four includes (lines 331-334), and the stub function deleted, not merely left unreachable below the include.

---

## Shared Patterns

### Manager gating
**Source:** `app/deps.py::require_manager` (lines 203-214), built on `_resolve_roles` (lines 148-200)
**Apply to:** Every route in `app/routers/meetings.py` (list, detail, republish) — identical `Depends(require_manager)` on all three, same as every other operational module. Never re-derive auth per-route (ACCESS-02 discipline).
```python
async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```

### Bot-liveness / staleness check
**Source:** `app/deps.py::bot_online`/`compute_bot_online` (lines 64-81)
**Apply to:** `meetings_page`'s `bot_online` context value (same pattern jinxxy/overview use for the sidebar's online indicator).

### Idempotent panel→bot action queue
**Source:** `core/action_queue.py::enqueue_deduped` (extended, see above) + `cogs/action_queue_worker.py::_run_once` (lines 42-62)
**Apply to:** `app/routers/meetings.py::republish_meeting` (enqueue side) and `cogs/action_queue_worker.py::_handle_meeting_republish` (dispatch side). The `dedupe_key` extension is the ONE genuinely new mechanism this phase adds to shared infrastructure — every other pattern above is pure reuse.

### Attribution / activity logging
**Source:** `core/db.py::log_activity` (lines 798-813), already called from `cogs/meeting.py::_publish` (lines 283-289)
**Apply to:** `cogs/meeting.py::_republish` — log `"meeting_republished"` with the editing Manager's OAuth display name (`actor_name`, threaded through the queue payload per Pattern 3 — read the target ids from the DB, but `actor_name` for the LOG MESSAGE is fine to carry in the payload since it's attribution text, not a mutation target).

### Archived-thread defensive edit (new mechanism, no repo precedent)
**Source:** RESEARCH.md Pattern 4, discord.py 2.5.2 `Thread.edit(archived=...)`/`get_partial_message`
**Apply to:** `cogs/meeting.py::_republish` only. See full excerpt above.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `cogs/meeting.py::_republish`'s unarchive/edit/restore body | service | request-response | No existing cog edits an archived Discord thread — this is the phase's one genuinely new engineering surface (RESEARCH.md "Key insight"). Use the RESEARCH.md Pattern 4 code directly; do not search further, discord.py's own API is the authoritative source here. |
| `app/templates/meeting_detail.html`'s two-panel (Summary card + Transcript card, one page) layout | component | request-response | No existing dashboard page combines an editable-textarea card with a separate collapsible read-only card on one page (jinxxy is single-card; reminders uses a modal, not a page). Compose from the `.card`/`.mod-hdr` primitives directly per UI-SPEC's "Interaction & Layout Notes" section 2 — do not invent new CSS classes, only new HTML composition of existing classes. |

---

## Metadata

**Analog search scope:** `cogs/`, `core/`, `app/routers/`, `app/templates/`, `app/static/dashboard.css`, `app/deps.py`, `app/main.py`, `tests/`
**Files scanned:** `cogs/meeting.py`, `cogs/gallery.py`, `cogs/action_queue_worker.py`, `core/action_queue.py`, `core/db.py`, `app/routers/jinxxy.py`, `app/routers/reviews.py`, `app/routers/reminders.py`, `app/deps.py`, `app/main.py`, `app/templates/jinxxy.html`, `app/static/dashboard.css`, `tests/test_action_queue_dedupe.py`, `tests/test_action_queue_cog.py`, `tests/test_app_jinxxy.py`
**Pattern extraction date:** 2026-07-29
