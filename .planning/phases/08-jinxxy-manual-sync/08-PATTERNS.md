# Phase 8: Jinxxy Manual Sync - Pattern Map

**Mapped:** 2026-07-24
**Files analyzed:** 13 (8 modify, 5 new)
**Analogs found:** 13 / 13

All analogs below were read directly from the current repo state (not trusted from
RESEARCH.md's summary alone) — line numbers/excerpts are verbatim as of this mapping pass.
Note: RESEARCH.md's `<required_reading>` names `cogs/jinxxy_cog.py` and `tests/test_jinxxy_cog.py`
for the cog; the actual file on disk is **`cogs/jinxxy.py`** (confirmed via `Glob`) — the test
file name is correct as given. Every reference below uses the real path.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `cogs/jinxxy.py` (MODIFY) | service/controller (Discord cog) | event-driven + request-response | `core/github_publish.py` (`_commit_lock`) + itself (`_run_sync`/`_poll`) | exact (lock shape) |
| `cogs/action_queue_worker.py` (MODIFY) | controller (queue dispatcher) | event-driven | itself — `_handle_gallery_publish`/`_handle_review_publish` | exact |
| `core/db.py` (MODIFY — widen `jinxxy_sync_status`) | model/migration | CRUD | itself — `init_reminders()` ADD-COLUMN idiom | exact |
| `core/action_queue.py` (MODIFY — dedupe helper) | service/model | CRUD | itself — `enqueue()` | exact |
| `app/routers/jinxxy.py` (NEW) *or* `app/main.py` (MODIFY, if kept inline) | route/controller | request-response | `app/routers/gallery.py` | exact |
| `app/templates/jinxxy.html` (NEW) | component/template | request-response + client poll | `app/templates/reminders.html` (table) + `app/templates/overview.html` (`actionProofApp`, stat tile) + `app/templates/gallery.html` (`row.already`, `queueApp` poll) | exact (composite) |
| `app/static/dashboard.css` (MODIFY — narrow additions) | config/style | n/a | existing `.mod-hdr`/`.action-proof-status`/`.status-badge`/`.empty` blocks | exact (verbatim reuse) |
| `app/auth.py` (MODIFY — persist `username`) | middleware (OAuth callback) | request-response | itself — the `request.session["discord_id"] = user_id` line | exact |
| `app/deps.py` (MODIFY — thread `username` into `roles`) | middleware (session/tier resolver) | request-response | itself — `_resolve_roles`'s return dict | exact |
| `tests/test_jinxxy_cog.py` (MODIFY) | test | event-driven (async race) | itself (`cog`/`_wire` fixtures) + `tests/test_action_queue_concurrency.py` (race harness idiom) | exact |
| `tests/test_app_jinxxy.py` (NEW) | test | request-response | `tests/test_app_gallery.py` | exact |
| `tests/test_action_queue_cog.py` (MODIFY, optional dispatch case) | test | event-driven | itself — existing dispatch-handler tests | exact |
| `tests/test_db_reminders_crud.py`-shaped new test (in a jinxxy/db test file) | test | CRUD/migration | `tests/test_db_reminders_crud.py::test_init_reminders_migrates_paused_version_onto_existing_table` | exact |

---

## Pattern Assignments

### `cogs/jinxxy.py` (service/controller, event-driven + request-response)

**Analog 1 — lock shape:** `core/github_publish.py` lines 66-70

```python
# ─── core/github_publish.py:66-70 ───
# Serializes the whole read-modify-commit so concurrent publishes don't race the ref.
# The single-process bot uses one event loop; uncontended acquires take the fast path
# and never bind a loop, so this is also safe across the test suite's asyncio.run calls.
_commit_lock = asyncio.Lock()
```
Every commit method in that file wraps its body identically:
```python
# ─── core/github_publish.py:878-879 (sync_store, one of ~8 identical wrappers) ───
async with _commit_lock:
    return await asyncio.to_thread(_sync_store_sync, products, message)
```
**Divergence Phase 8 needs (not present in this analog):** `_commit_lock`'s usage always
BLOCKS on `async with` (waits for the lock). D-01 requires a non-blocking fast path —
check `.locked()` BEFORE attempting acquire, and return a benign result instead of waiting:
```python
# NEW shape — sketch, not verbatim repo code (per RESEARCH.md Pattern 1)
async def _run_sync_guarded(self, source: str) -> dict:
    if self._sync_lock.locked():
        return {"already": True}          # D-01: benign success, never an error
    async with self._sync_lock:
        ...
```

**Analog 2 — the orchestration body being wrapped:** `cogs/jinxxy.py:169-281` (`_run_sync`,
unchanged by this phase — call it, never reimplement) and `cogs/jinxxy.py:283-301` (`_poll` +
its `_on_poll_error` cooldown-restart, D-03's target for the reverse-collision skip-and-log).

**Analog 3 — the status/activity instrumentation seam to widen:** `cogs/jinxxy.py:148-166`
(`_record_sync_status`) — the exact method D-09 (counts) and D-12 (attribution) extend:
```python
# ─── cogs/jinxxy.py:149-166 ───
async def _record_sync_status(
        self, *, ok: bool, product_count: int | None, error: str | None) -> None:
    try:
        await asyncio.to_thread(
            db.set_jinxxy_sync_status, ok=ok, product_count=product_count, error=error)
        message = ("Sync de Jinxxy ejecutado / Jinxxy sync ran" if ok else
                   "Sync de Jinxxy falló / Jinxxy sync failed")
        await asyncio.to_thread(db.log_activity, "jinxxy_sync", message)
    except Exception:
        log.exception("jinxxy: no pude registrar el estado de sync")
```
D-12 changes the `message` string to name the source (e.g. `"desde el panel (Nombre)"` vs
`"programada"`), and the call gains `source`/counts kwargs threaded from `_run_sync_guarded`.

**Analog 4 — the `/tienda sync` command, whose error-to-logs-only shape D-10 must match
for the panel path too:** `cogs/jinxxy.py:307-344`:
```python
# ─── cogs/jinxxy.py:322-334 ───
try:
    result = await self._run_sync()
except Exception:
    log.exception("jinxxy: /tienda sync falló")
    await interaction.followup.send(
        "No pude sincronizar ahora; revisa los logs.", ephemeral=True)
    return
```
D-10 requires the SAME exception-type mapping applied to the panel/queue path (mapping
`JinxxyAPIError` → Jinxxy-unreachable copy, `GitHubPublishError` → GitHub-publish copy,
anything else → generic) BEFORE the string reaches `action_queue.fail(id, str(exc))`.

**Init-time mirror clear (D-06):** `cogs/jinxxy.py:137-141` (`__init__`) is the analog site —
mirrors the existing `db.init_store_state()` defensive-init call already there; add a
`db.set_jinxxy_sync_status(running=False, ...)`-shaped clear alongside it.

**Critical implementation trap (from RESEARCH.md Pitfall 1, confirmed against the actual
file):** `_poll` (`cogs/jinxxy.py:285-287`) and `/tienda sync` (`cogs/jinxxy.py:336-337`) BOTH
independently call `await self._announce(result)` today as a second statement after
`_run_sync()`. If the new guarded wrapper also calls `_announce` internally, both call sites
MUST be refactored to call the wrapper (which alone calls `_announce`) — never both.

---

### `cogs/action_queue_worker.py` (controller, event-driven)

**Analog:** `_handle_gallery_publish` (`cogs/action_queue_worker.py:91-111`) — the shape a
new `_handle_jinxxy_sync` follows exactly (resolve cog → call cog method → shape result):
```python
# ─── cogs/action_queue_worker.py:91-111 ───
async def _handle_gallery_publish(self, payload: dict) -> dict:
    message_id = int(payload["message_id"])
    channel = await self._resolve_channel(config.PHOTO_CHANNEL_ID)
    message = await self._fetch_message(channel, message_id)
    was_published = gallery_is_published(message)

    gallery_cog = self.bot.get_cog("GalleryCog")
    if gallery_cog is None:
        raise RuntimeError(
            "GalleryCog no está cargado · GalleryCog is not loaded"
        )
    await gallery_cog._publish(message)

    message = await self._fetch_message(channel, message_id)
    is_published = gallery_is_published(message)
    if is_published:
        return {"already": was_published}
    raise RuntimeError(
        "no se pudo publicar · publish did not complete "
        "(see ⚠️ on the Discord message)"
    )
```
**Dict-registration pattern to extend** (`cogs/action_queue_worker.py:24-30`):
```python
self._dispatch = {
    "noop": self._handle_noop,
    "gallery_publish": self._handle_gallery_publish,
    "gallery_remove": self._handle_gallery_remove,
    "review_publish": self._handle_review_publish,
    "review_remove": self._handle_review_remove,
    # + "jinxxy_sync": self._handle_jinxxy_sync,
}
```
**Error handling (already generic, reused verbatim):** `_run_once` (`cogs/action_queue_worker.py:40-60`)
already maps any handler exception to `action_queue.fail(id, str(exc))` — this is the exact
seam RESEARCH.md flags as needing D-10's category mapping BEFORE the string reaches it (map
inside `_handle_jinxxy_sync`'s except clause, not here, to avoid touching shared dispatch code).
The new handler resolves `JinxxyCog` the same way gallery/reviews resolve their cogs:
`self.bot.get_cog("JinxxyCog")` → `RuntimeError` if `None` (same "no está cargado" idiom).

---

### `core/db.py` (model/migration, CRUD) — widen `jinxxy_sync_status`

**Analog — the exact ADD-COLUMN idiom to copy, substituting column names**
(`core/db.py:285-292`, inside `init_reminders()`):
```python
# ─── core/db.py:285-292 ───
for col, default in [("paused", "0"), ("version", "1")]:
    try:
        conn.execute(
            f"ALTER TABLE reminders ADD COLUMN {col} "
            f"INTEGER NOT NULL DEFAULT {default}"
        )
    except sqlite3.OperationalError:
        pass  # Ya existe
```
A second, TEXT-typed instance of the same idiom already exists at `core/db.py:36-40`
(`forum_posts`, `image_url`/`source_url` — useful for the `source`/`started_at` TEXT columns):
```python
# ─── core/db.py:36-40 ───
for col, default in [("image_url", "''"), ("source_url", "''")]:
    try:
        conn.execute(f"ALTER TABLE forum_posts ADD COLUMN {col} TEXT DEFAULT {default}")
    except sqlite3.OperationalError:
        pass  # Ya existe
```

**The exact table/functions being widened** (`core/db.py:657-694`):
```python
# ─── core/db.py:657-694 (current 5-column shape, BEFORE widening) ───
def init_jinxxy_sync_status():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jinxxy_sync_status (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                last_run_utc   TEXT,
                ok             INTEGER,
                product_count  INTEGER,
                error          TEXT
            )
        """)

def set_jinxxy_sync_status(ok: bool, product_count: int | None, error: str | None):
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO jinxxy_sync_status
                (id, last_run_utc, ok, product_count, error)
            VALUES (1, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), 1 if ok else 0, product_count, error))

def get_jinxxy_sync_status() -> sqlite3.Row | None:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT last_run_utc, ok, product_count, error FROM jinxxy_sync_status WHERE id = 1"
        ).fetchone()
```
`init_jinxxy_sync_status()` MUST pair its `CREATE TABLE IF NOT EXISTS` with the ADD-COLUMN
loop above (Pitfall 2) — a fresh `CREATE TABLE IF NOT EXISTS` including the new columns
works only on a brand-new DB and is a silent no-op against any already-deployed 5-column
table. `set_jinxxy_sync_status`'s `INSERT OR REPLACE` and `get_jinxxy_sync_status`'s
explicit column `SELECT` both need their column lists extended to match.

**Data-shape analog for the `store_snapshot` table** D-13's product table reads
(unchanged by this phase, read-only from the app) — `core/db.py:420-451`
(`init_store_state`/`get_store_snapshot`), same file, same section.

---

### `core/action_queue.py` (service/model, CRUD) — D-04 dedupe helper

**Analog:** the file's own `enqueue()` (`core/action_queue.py:39-47`), which the new
`enqueue_deduped` (or route-local dedupe query) extends with a pre-insert `SELECT`:
```python
# ─── core/action_queue.py:39-47 ───
@_retry_on_locked
def enqueue(kind: str, payload: dict, requested_by: str) -> int:
    with db._get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso()),
        )
        return cur.lastrowid
```
The `@_retry_on_locked` decorator (`core/action_queue.py:21-37`) and the `with
db._get_conn() as conn:` idiom must wrap the new dedupe-aware function identically — this
is the project's ONLY sqlite-contention hardening and every write path uses it. No other
function in the codebase does a pre-insert existence check today (confirmed — RESEARCH.md's
claim holds): the dedupe SELECT (`WHERE kind='jinxxy_sync' AND status IN ('pending','claimed')
ORDER BY id LIMIT 1`) is new SQL, but the transactional shape around it is not.

---

### `app/routers/jinxxy.py` (NEW, route/controller, request-response)

**Analog:** `app/routers/gallery.py` (full file, 98 lines) — same three-part shape:
GET page route, GET JSON status route, POST enqueue route(s), all `Depends(require_manager)`.
```python
# ─── app/routers/gallery.py:26-54 (GET page) ───
@router.get("/gallery", response_class=HTMLResponse)
async def gallery_page(
    request: Request, roles: dict = Depends(require_manager)
):
    pending, published = await _queue_rows()
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        asset_v = 0
    template_name = (
        "gallery.html"
        if (_APP_DIR / "templates" / "gallery.html").is_file()
        else "module_stub.html"
    )
    return templates.TemplateResponse(
        request, template_name,
        {
            "roles": roles, "active_section": "gallery", "asset_v": asset_v,
            "bot_online": False, "pending_rows": pending, "published_rows": published,
            "section_label": "Galería · Gallery", "icon": "🖼",
            "accent": "var(--accent-gallery)",
        },
    )
```
**POST enqueue pattern** (`app/routers/gallery.py:68-97`) — the D-04 dedupe-at-enqueue route
follows this shape but swaps the unconditional `action_queue.enqueue` for the new dedupe
helper:
```python
# ─── app/routers/gallery.py:68-97 ───
async def _enqueue_gallery_action(
    message_id: int, kind: str, roles: dict
) -> JSONResponse:
    row = await run_in_threadpool(db.get_gallery_queue_row, message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="foto no encontrada · photo not found")
    action_id = await run_in_threadpool(
        action_queue.enqueue, kind, {"message_id": message_id}, str(roles["discord_id"]),
    )
    return JSONResponse({"id": action_id})

@router.post("/gallery/{message_id}/approve")
async def approve_gallery_item(
    message_id: int, roles: dict = Depends(require_manager)
):
    return await _enqueue_gallery_action(message_id, "gallery_publish", roles)
```
For Jinxxy the payload takes no id (a store-wide sync, not per-item), so the POST route has
no 404 branch — only the dedupe-or-enqueue call.

**The currently-shipped stub site to replace** (`app/main.py:659-661`):
```python
# ─── app/main.py:659-661 (current) ───
@app.get("/jinxxy", response_class=HTMLResponse)
async def jinxxy_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "jinxxy", roles)
```
Section metadata to reuse verbatim (`app/main.py:502-510`, `_MODULE_SECTIONS["jinxxy"]`):
`label="Tienda Jinxxy · Jinxxy Store"`, `icon="🛍"`, `accent="var(--accent-jinxxy)"`.

**The `_ALLOWED_KINDS` allowlist to extend** (`app/main.py:73-79`):
```python
_ALLOWED_KINDS = {
    "noop", "gallery_publish", "gallery_remove", "review_publish", "review_remove",
    # + "jinxxy_sync"
}
```
**The status-read analog** (`app/main.py:669-679`, `/api/overview/status`) already reads
`db.get_jinxxy_sync_status()` via `run_in_threadpool` — the same read (widened) backs the
Jinxxy page's own status card; `/api/actions/{id}` (`app/main.py:694-703`) is reused verbatim
for the own-action poll, no new endpoint required for that part.

---

### `app/templates/jinxxy.html` (NEW, template, request-response + client poll)

**Analog 1 — page shell + table** (`app/templates/reminders.html:1-79`):
```html
<!-- app/templates/reminders.html:13-22 -->
<div class="mod-hdr" style="--acc: var(--accent-reminders)">
  <span class="i">⏰</span>
  <div>
    <div class="t">Recordatorios · Reminders</div>
    <div class="s">Programa avisos para el equipo · Schedule notices for the team</div>
  </div>
  <button class="btn reminders-create" type="button" @click="openCreate()">
    Nuevo recordatorio · New reminder
  </button>
</div>
```
Table shape (`app/templates/reminders.html:26-73`) — `<table><thead>...<tbody><template
x-for...>` with a `.status-badge` cell and an `.empty` fallback block
(`app/templates/reminders.html:75-78`):
```html
<div class="empty" x-show="!rows.length">
  <div class="h">Sin recordatorios · No reminders yet</div>
  <p>Crea el primero para empezar a recordar al equipo. · Create the first one to start reminding the team.</p>
</div>
```
D-15's never-synced empty state follows this exact `.empty`/`.h` shape with the locked copy
substituted verbatim ("Nunca se ha sincronizado · Never synced" / "Aún no hay productos
sincronizados · No synced products yet").

**Analog 2 — status card + busy-state machine** (`app/templates/overview.html:60-97` markup,
`137-252` JS, `actionProofApp()`):
```html
<!-- app/templates/overview.html:75-96 -->
<div class="action-proof-status" :data-state="stateKind()" x-show="status !== 'idle'"
     role="status" aria-live="polite">
  <span class="action-proof-mark" aria-hidden="true" x-show="stateMark()" x-text="stateMark()"></span>
  <span class="action-proof-copy" x-text="statusCopy()"></span>
  <button class="btn ghost action-proof-retry" type="button" x-show="status === 'failed'"
          @click="retry()" :disabled="busy">Reintentar · Retry</button>
</div>
```
```javascript
// app/templates/overview.html:150-161
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
Ambient 30s poll cadence to reuse for the D-05 mirror-derived busy state
(`app/templates/overview.html:106-118`):
```javascript
poll() {
  setInterval(() => this.refresh(), 30000);
},
async refresh() {
  try {
    const r = await fetch('/api/overview/status');
    const json = await r.json().catch(() => null);
    if (json) this.data = json;
  } catch (e) { /* keep last-known-good state */ }
},
```
Stat-tile markup for the "Última sync Jinxxy" precedent whose wording the new status card
should stay consistent with (`app/templates/overview.html:31-35`):
```html
<div class="stat" style="--acc: var(--accent-jinxxy)">
  <div class="k">Última sync Jinxxy · Last Jinxxy sync</div>
  <div class="v" x-text="(data.last_sync && data.last_sync.when) ? data.last_sync.when : '—'"></div>
  <div class="d" x-text="syncDetail()"></div>
</div>
```

**Analog 3 — the D-01 "moot success" render + own-action 1500ms poll + network-error toast**
(`app/templates/gallery.html`, `queueApp()`):
```javascript
// app/templates/gallery.html:325-339
async poll(row) {
  ...
  const body = await response.json();
  row.status = body.status;
  row.error = body.error || '';
  row.botOnline = body.bot_online;
  row.already = !!(body.result && body.result.already);
  if (this.isPending(row)) {
    row.pollTimer = setTimeout(() => this.poll(row), 1500);
  }
  ...
}
```
```html
<!-- app/templates/gallery.html:87-90 -->
<span class="queue-status-detail" x-show="row.status === 'done' && row.already && row.lastAction === 'approve'">
  Ya estaba publicada. · Already published.
</span>
```
Phase 8's D-01 copy branch ("Ya se está sincronizando · Sync already running") follows this
exact `already`-flag idiom — `stateKind()` still returns `'ok'` (green) when `status ===
'done'`, regardless of `already`; only the COPY branches. Toast markup
(`app/templates/gallery.html:160-166`):
```html
<div class="toast" data-kind="error" x-show="toast" x-text="toast" @click="toast = ''"
     role="status" aria-live="polite"></div>
```

**Button label-swap idiom** (D-07's "Sincronizando… · Syncing…", `app/templates/reminders.html:323-328`):
```html
<button class="btn" type="submit" :disabled="saving"
        x-text="saving ? 'Guardando… · Saving…' : (editingId ? 'Guardar cambios · Save changes' : 'Crear recordatorio · Create reminder')"></button>
```

---

### `app/static/dashboard.css` (config/style, verbatim reuse + narrow additions)

**Blocks to reuse with ZERO changes** (per UI-SPEC "compose only"):
```css
/* dashboard.css:236-244 — .mod-hdr */
.mod-hdr {
  display: flex; align-items: center; gap: var(--space-4);
  background: var(--color-surface); border: 1px solid var(--color-border);
  ...
  margin-bottom: var(--space-6); border-left: 4px solid var(--acc, var(--color-primary));
}
.mod-hdr .i { font-size: var(--text-2xl); }
.mod-hdr .t { font-weight: 600; font-size: var(--text-lg); }
.mod-hdr .s { font-size: var(--text-sm); color: var(--color-text-muted); margin-top: var(--space-1); }
```
```css
/* dashboard.css:219-232 — .action-proof-status family */
.action-proof-status {
  display: flex; align-items: center; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border); border-left: 3px solid var(--color-warning);
  border-radius: var(--radius-md); background: var(--color-surface-2);
}
.action-proof-status[data-state="ok"] { border-left-color: var(--color-success); }
.action-proof-status[data-state="failed"] { border-left-color: var(--color-danger); }
.action-proof-status[data-state="offline"] { border-left-color: var(--color-warning); }
```
```css
/* dashboard.css:363-379 — .status-badge (NSFW badge reuses this shape) */
.status-badge {
  display: inline-flex; align-items: center;
  padding: var(--space-1) var(--space-2);
  ...
  white-space: nowrap;
}
```
`--accent-jinxxy: #34d399` already defined (`dashboard.css:34`) — no new token. Per UI-SPEC,
at most 2-3 new narrow class names for the product-table row accents (e.g. a link-styled
name cell) are permitted; everything else composes the blocks above verbatim.

---

### `app/auth.py` (middleware, request-response) — D-07/D-12 name persistence

**Analog — the exact session-write site to extend** (`app/auth.py:259-264`):
```python
# ─── app/auth.py:259-264 (current) ───
entry = await ensure_draft(user_id, username) if is_editor else None

# Session issued last, only on the fully-authorized path — no tier is ever cached (D-02).
request.session["discord_id"] = user_id
if entry is not None:
    request.session["slug"] = entry["slug"]
```
`username` is already computed one line above the analog site (`app/auth.py:243`:
`username = user.get("username") or user.get("global_name") or user_id`), and is the SAME
OAuth-verified value already used for `ensure_draft` — per the user's post-research decision,
add `request.session["username"] = username` alongside the `discord_id` line. This is a
one-line addition at an already-locked trust boundary; do not compute or accept a name from
anywhere else (no query param, no client input — Security Domain V3/Spoofing note in
RESEARCH.md).

---

### `app/deps.py` (middleware, request-response) — thread `username` into `roles`

**Analog — the exact dict the route handlers/dependency consume** (`app/deps.py:139-171`,
`_resolve_roles`):
```python
# ─── app/deps.py:139-171 (current, no username key) ───
discord_id = request.session.get("discord_id")
if not discord_id:
    raise HTTPException(status_code=401, detail="Not authenticated")
...
return {
    "discord_id": discord_id,
    "is_owner": is_owner,
    "is_manager": is_manager,
    "is_editor": is_editor,
}
```
Add `"username": request.session.get("username")` to this returned dict so the Jinxxy route's
enqueue path can pass a human name (not just the raw snowflake id) through to
`action_queue.enqueue`/`_record_sync_status` for D-07/D-12 — mirrors exactly how
`discord_id` is already read from the session and passed through in the same dict.
`require_manager` (`app/deps.py:174-185`) returns this dict unchanged, so no other call site
needs touching.

---

### `tests/test_jinxxy_cog.py` (test, event-driven async race)

**Analog — existing fixtures to reuse verbatim** (`tests/test_jinxxy_cog.py:41-60`, `cog`
and `_wire`):
```python
# ─── tests/test_jinxxy_cog.py:55-60 ───
@pytest.fixture
def cog(monkeypatch):
    """A JinxxyCog with the DB table init + poll-loop start neutralized (no side effects)."""
    monkeypatch.setattr(jinxxy.db, "init_store_state", lambda: None)
    monkeypatch.setattr(jinxxy.tasks.Loop, "start", lambda self, *a, **k: None)
    return jinxxy.JinxxyCog(bot=types.SimpleNamespace())
```
```python
# ─── tests/test_jinxxy_cog.py:94-99 — the controllable-duration sync_store mock shape ───
async def _sync_store(prods, *a, **k):
    rec.synced.append(list(prods))
    return {"committed": True, "commit_sha": "abc", "count": len(prods)}
monkeypatch.setattr(jinxxy.github_publish, "sync_store", AsyncMock(side_effect=_sync_store))
rec.sync_mock = jinxxy.github_publish.sync_store
```
The overlap-guard test replaces this `_sync_store` with one that `await`s an `asyncio.Event`
(gate) before returning — the exact pattern RESEARCH.md's Code Examples section sketches,
and the one used by `tests/test_action_queue_concurrency.py`'s threaded-race harness (same
"deterministic controlled contention" idea, applied to `asyncio.Task`s instead of threads
since this repo drives async tests with `asyncio.run()`, never `pytest-asyncio` — confirmed,
no `pytest_asyncio` import anywhere in `tests/`).

---

### `tests/test_app_jinxxy.py` (NEW, test, request-response)

**Analog — the full session-signing + dependency-override fixture pattern**
(`tests/test_app_gallery.py:1-73`):
```python
# ─── tests/test_app_gallery.py:55-72 ───
def _manager_override():
    return {
        "discord_id": "manager-2",
        "is_owner": False,
        "is_manager": True,
        "is_editor": False,
    }

@pytest.fixture
def client(monkeypatch, tmp_path):
    _configure_app(monkeypatch, tmp_path)
    app.dependency_overrides[require_manager] = _manager_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
```
Note: `_manager_override` will need a `"username"` key added (matching the `app/deps.py`
widening above) so D-07/D-12 attribution assertions have something to check.
**Enqueue-assertion analog** (`tests/test_app_gallery.py:75-84`, `_assert_enqueued`):
```python
def _assert_enqueued(response, expected_kind, expected_message_id):
    assert response.status_code == 200
    action_id = response.json()["id"]
    assert isinstance(action_id, int)
    row = action_queue.get_status(action_id)
    assert row["status"] == "pending"
    assert row["kind"] == expected_kind
    assert json.loads(row["payload_json"]) == {"message_id": expected_message_id}
```
For D-04's dedupe test, the analog shape is the same, but the assertion is "a second POST
returns the SAME `id`, and `SELECT COUNT(*) ... WHERE kind='jinxxy_sync'` stays 1" — no
existing test does this exact double-POST assertion, so it is new test logic on a familiar
fixture skeleton. **Manager-gate regression analog**
(`tests/test_app_gallery.py:129-149`, `test_gallery_routes_reject_non_manager`) — parametrize
the Jinxxy GET/POST routes the same way to confirm every new route carries
`Depends(require_manager)`.

---

### DB migration-safety test (new file or appended to an existing db-test file)

**Analog — the EXACT test shape to copy, substituting `jinxxy_sync_status`/its columns**
(`tests/test_db_reminders_crud.py:32-72`,
`test_init_reminders_migrates_paused_version_onto_existing_table`):
```python
# ─── tests/test_db_reminders_crud.py:32-72 ───
def test_init_reminders_migrates_paused_version_onto_existing_table(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path, "migration.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE reminders ( ... )""")   # OLD shape, no paused/version
        conn.execute("""INSERT INTO reminders (...) VALUES (...)""", (...))

    db.init_reminders()

    with db._get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
        row = conn.execute(
            "SELECT name, paused, version FROM reminders WHERE name = ?", ("Existente",),
        ).fetchone()
    assert {"paused", "version"} <= columns
    assert row["name"] == "Existente"
    assert row["paused"] == 0
    assert row["version"] == 1
```
Phase 8's version: manually `CREATE TABLE jinxxy_sync_status` with the OLD 5-column shape,
insert one row, call the (widened) `init_jinxxy_sync_status()`, then assert
`running`/`started_at`/`source`/the three count columns are all queryable via
`PRAGMA table_info` and the pre-existing row is untouched. This is Pitfall 2's own
"warning sign" test, verbatim.

**Existing round-trip usage to extend, not a new pattern** (`tests/test_app_dashboard.py`,
confirmed via grep — the only other test file touching this table):
```python
core_db.init_jinxxy_sync_status()
core_db.set_jinxxy_sync_status(ok=True, product_count=10, error=None)
```
This call site's `set_jinxxy_sync_status(...)` signature will need its new keyword args
(`running`, `started_at`, `source`, counts) added here too once the function signature widens.

---

## Shared Patterns

### Non-blocking overlap guard (D-01/D-02/D-03)
**Source:** `core/github_publish.py:66-70` (lock declaration shape) + `cogs/jinxxy.py`'s
`_run_sync`/`_poll` (the body being wrapped).
**Apply to:** `cogs/jinxxy.py` only — this is the phase's one piece of genuinely new logic;
no other file needs a lock.
```python
_commit_lock = asyncio.Lock()   # shape to copy; add .locked() pre-check for D-01
```

### ADD-COLUMN migration idiom (D-02/D-07/D-09 columns on `jinxxy_sync_status`)
**Source:** `core/db.py:285-292` (`init_reminders`) and `core/db.py:36-40` (`init_db`,
`forum_posts`).
**Apply to:** `core/db.py::init_jinxxy_sync_status` only.
```python
for col, default in [("running", "0"), ("started_at", "NULL"), ...]:
    try:
        conn.execute(f"ALTER TABLE jinxxy_sync_status ADD COLUMN {col} ...")
    except sqlite3.OperationalError:
        pass  # Ya existe
```

### Manager-gated POST-enqueue + JSON status read
**Source:** `app/routers/gallery.py` (full file) + `app/main.py:682-711` (`/api/actions`
family).
**Apply to:** the new `app/routers/jinxxy.py` (or inline `app/main.py` route) — every route
must carry `Depends(require_manager)` (Security Domain V4 note in RESEARCH.md flags this as
a grep-able plan-checker item).

### `actionProofApp`/`queueApp` Alpine state machine (busy/pending/done/failed + moot success)
**Source:** `app/templates/overview.html:137-252` (`actionProofApp`) +
`app/templates/gallery.html` (`queueApp`, `row.already`).
**Apply to:** `app/templates/jinxxy.html`'s own Alpine component — reuse `stateKind`/
`stateMark`/the `already`-flag branch verbatim; add only the D-07 elapsed-time tick and the
D-05 ambient-mirror-poll wiring as genuinely new logic.

### Bilingual, Spanish-first, no-raw-error copy discipline
**Source:** every existing user-facing string in `cogs/jinxxy.py` (`"Sin permisos."`,
`"No pude sincronizar ahora; revisa los logs."`) and `app/templates/*.html`.
**Apply to:** every new string in this phase (D-10's category table, D-15's empty states,
D-07's in-flight labels) — locked verbatim in UI-SPEC.md's Copywriting Contract.

---

## No Analog Found

None. Every file in this phase's scope has at least one exact same-shape precedent already
in the repository — consistent with RESEARCH.md's framing of Phase 8 as a "wrap existing
code" phase rather than a new-architecture phase. The one piece of genuinely new SQL (the
D-04 dedupe pre-insert `SELECT`) still reuses the surrounding transactional/retry scaffolding
of `core/action_queue.py::enqueue` exactly.

## Metadata

**Analog search scope:** `cogs/`, `core/`, `app/` (routers, templates, main.py, auth.py,
deps.py, static/dashboard.css), `tests/` — all read directly, not inferred from RESEARCH.md.
**Files scanned (read in full or targeted sections):** `cogs/jinxxy.py`,
`cogs/action_queue_worker.py`, `core/github_publish.py`, `core/db.py`, `core/action_queue.py`,
`app/routers/gallery.py`, `app/main.py`, `app/auth.py`, `app/deps.py`,
`app/templates/reminders.html`, `app/templates/overview.html`, `app/templates/gallery.html`,
`app/templates/_sidebar.html`, `app/static/dashboard.css`, `tests/test_jinxxy_cog.py`,
`tests/test_app_gallery.py`, `tests/test_db_reminders_crud.py`,
`tests/test_action_queue_concurrency.py`, `tests/test_app_dashboard.py`.
**Pattern extraction date:** 2026-07-24
