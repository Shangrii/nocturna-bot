# Phase 3: Dashboard Shell + Tiered Access - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 15 (new/modified)
**Analogs found:** 15 / 15

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/auth.py` (extend: `_fetch_member_roles`, `resolve_tiers`, `has_editor_role` rework) | service/auth | request-response | `app/auth.py::has_editor_role` (same file, existing function) | exact |
| `app/deps.py` (extend: `_resolve_roles`, `require_manager`, `TierForbidden`) | middleware/guard | request-response | `app/deps.py::require_editor`/`require_owner` (same file) | exact |
| `app/main.py` (extend: `/overview`, `/gallery`, `/reviews`, `/reminders`, `/jinxxy`, `/meetings`, `/api/overview/status`, exception-handler branch, lifespan additions) | controller/route | request-response | `app/main.py::editor_page`/`settings_page`/`lifespan`/`_auth_html_or_json` (same file) | exact |
| `core/settings.py` (extend: `manager_roles`/`editor_roles` `_Setting` entries) | model/config-schema | CRUD | `core/settings.py::_SCHEMA["GALLERY_STAFF_ROLE_IDS"]` (same file, `role_list` entries) | exact |
| `core/db.py` (extend: `init_heartbeat`/`set_heartbeat`/`get_heartbeat`, `init_jinxxy_sync_status`/`set_/get_`, `init_activity_log`/`log_activity`/`get_recent_activity`) | model/storage | CRUD | `core/db.py::init_presence`/`set_presence`/`get_presence` and `init_store_state`/`upsert_store_snapshot` (same file) | exact |
| `cogs/heartbeat.py` (new) | service/background-task | event-driven | `cogs/presence.py` (`@tasks.loop`-free but `on_ready` snapshot idiom) and `cogs/jinxxy.py`'s `@tasks.loop` poll | role-match |
| `cogs/jinxxy.py` (extend: `_run_sync` writes `jinxxy_sync_status`) | service/background-task | event-driven | `cogs/jinxxy.py::_run_sync`/`_poll` (same file) | exact |
| `cogs/gallery.py`, `cogs/reviews.py`, `cogs/reminders.py`, `cogs/meeting.py` (extend: `activity_log` helper calls on notable events) | service/event-hook | event-driven | `cogs/presence.py::_store` (bot-writes-sqlite-on-event idiom) | role-match |
| `app/templates/_dashboard_base.html` (new) | component/layout | request-response | `app/templates/settings.html` (topbar + Alpine `x-data` root shell) | role-match |
| `app/templates/_sidebar.html` (new) | component/nav-partial | request-response | `app/templates/settings.html` topbar `<header>` block + sketch `.planning/sketches/001-dashboard-shell/index.html` nav data | partial |
| `app/templates/overview.html` (new) | component/page | request-response + polling | `app/templates/settings.html` (Alpine `x-data` + fetch pattern) | role-match |
| `app/templates/module_stub.html` (new) | component/page | request-response | `app/templates/settings.html` (minimal Jinja page shell) | partial |
| `app/templates/forbidden.html` (new) | component/error-page | request-response | `app/templates/login.html` (`{% if forbidden %}` 403 block) | exact |
| `app/templates/settings.html` (extend: 2 new `role_list` fields + `groupNames` entry) | component/form | CRUD | `app/templates/settings.html` (same file, existing `role_list` field block) | exact |
| `tests/test_app_dashboard.py` (new) | test | request-response | `tests/test_app_settings.py` (`dependency_overrides` + `TestClient` tier-gate pattern) | exact |

## Pattern Assignments

### `app/auth.py` (service/auth, request-response)

**Analog:** `app/auth.py` itself (lines 82-99, 1-62)

**Imports pattern** (lines 24-37):
```python
import asyncio
import logging
import secrets

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import HTTPException
from starlette.responses import RedirectResponse

import config
from core import github_publish
from core.editors_model import EditorPage, normalize_slug
```
Add `from core import settings` for the new `manager_roles`/`editor_roles` reads.

**Bot-token role-read pattern to generalize** (lines 82-99):
```python
async def has_editor_role(user_id) -> bool:
    url = f"{DISCORD_API}/guilds/{config.GUILD_ID}/members/{user_id}"
    headers = {"Authorization": f"Bot {config.BOT_TOKEN}"}  # NEVER the OAuth user token
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        return False  # not a member of the guild → not an editor
    resp.raise_for_status()
    member = resp.json()
    role_ids = {str(r) for r in member.get("roles", [])}
    return str(config.ROLE_MODERATOR_ID) in role_ids
```
**Generalize this into two pieces per RESEARCH.md's recommended structure:**
1. `_fetch_member_roles(user_id) -> set[str] | None` — same request, returns the raw role-id
   set (or `None` on 404), so it can be shared by `has_editor_role` AND the new
   `_resolve_roles` dependency (avoids the N+1 Pitfall 4 from RESEARCH.md).
2. `has_editor_role(user_id)` becomes a thin wrapper: fetch roles, check against
   `settings.get("editor_roles")` (D-08) instead of the hardcoded `config.ROLE_MODERATOR_ID`
   constant — identical `404 → False` and bot-token-only discipline preserved verbatim.

**Login gate / redirect pattern to extend** (lines 195-220, `callback`):
```python
    if not await has_editor_role(user_id):
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    entry = await ensure_draft(user_id, username)

    # Session issued last, only on the fully-authorized path.
    request.session["discord_id"] = user_id
    request.session["slug"] = entry["slug"]
    return RedirectResponse(url=POST_LOGIN_REDIRECT, status_code=303)
```
D-01/Pitfall-1: replace the single `has_editor_role` gate with the tier resolver (owner
bypass + manager_roles + editor_roles union); replace fixed `POST_LOGIN_REDIRECT = "/"`
with a per-tier computed (still fixed, still server-side, never client `?next`) redirect:
owner/manager → `/overview`, editor-only → `/editor`. Session still stores ONLY
`discord_id`/`slug` — never a cached tier (D-02 invariant, Security Domain table).

**Error/forbidden copy pattern** (lines 56-62):
```python
_FORBIDDEN_COPY = (
    "This tool is for Nocturna editors only. If you should have access, ask a mod to "
    "check your role. — Esta herramienta es solo para editores de Nocturna. Si "
    "deberías tener acceso, pídele a un mod que revise tu rol."
)
```
Keep as-is for the "no tier at all" login gate; add a SEPARATE `_MANAGER_FORBIDDEN_COPY`
in `app/deps.py` for tier-specific denials (see Pitfall 2 below — do not reuse this string
for a Manager hitting Settings).

---

### `app/deps.py` (middleware/guard, request-response)

**Analog:** `app/deps.py` itself (lines 44-95, full file — 94 lines, read once)

**Existing choke-point pattern to extend** (lines 44-66, `require_editor`):
```python
async def require_editor(request: Request) -> dict:
    discord_id = request.session.get("discord_id")
    if not discord_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not await has_editor_role(discord_id):
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    return {"discord_id": discord_id, "slug": request.session.get("slug")}
```

**Fail-closed owner pattern to preserve exactly** (lines 69-94, `require_owner`):
```python
async def require_owner(request: Request) -> dict:
    discord_id = request.session.get("discord_id")
    owner_id = config.DISCORD_USER_ID
    if not owner_id:  # fail closed: unset/0 owner id must never authorize
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    if not discord_id or str(discord_id) != str(owner_id):
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)

    return {"discord_id": discord_id}
```
`require_owner` stays UNCHANGED (D-04's "owner can never be locked out" guarantee —
`/admin/settings` keeps this exact dependency, no new code path needed per Security
Domain table). Add `require_manager` as a NEW dependency layered on top of the NEW
`_resolve_roles` dependency (RESEARCH.md Pattern 1, Code Examples — copy verbatim):
```python
async def _resolve_roles(request: Request) -> dict:
    discord_id = request.session.get("discord_id")
    if not discord_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    is_owner = bool(config.DISCORD_USER_ID) and str(discord_id) == str(config.DISCORD_USER_ID)
    role_ids = await auth._fetch_member_roles(discord_id)
    if role_ids is None:
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)
    manager_ids = {str(r) for r in settings.get("manager_roles")}
    editor_ids = {str(r) for r in settings.get("editor_roles")}
    is_manager = bool(role_ids & manager_ids)
    is_editor = bool(role_ids & editor_ids)
    if not (is_owner or is_manager or is_editor):
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)
    return {"discord_id": discord_id, "is_owner": is_owner,
            "is_manager": is_manager, "is_editor": is_editor}


async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```
FastAPI's default `Depends(..., use_cache=True)` collapses repeat calls to `_resolve_roles`
within one request to a single Discord REST read (Pitfall 4 / Anti-Pattern guard — do NOT
hand-roll a `request.state` cache).

**Distinguishable-exception pattern for D-16/Pitfall 2** (new, no existing analog — add a
tiny subclass so the exception handler in `app/main.py` can render `forbidden.html`
instead of `login.html` for a tier denial):
```python
class TierForbidden(HTTPException):
    def __init__(self, required_tier: str):
        super().__init__(status_code=403, detail=f"needs {required_tier} access")
        self.required_tier = required_tier
```

---

### `app/main.py` (controller/route, request-response)

**Analog:** `app/main.py` itself (lines 1-59 imports, 270-327 lifespan+handler, 388-441 routes)

**Imports pattern** (lines 42-57):
```python
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import config
from app import auth
from app.deps import require_editor, require_owner
from core import db, github_publish, settings
```
Add `require_manager`, `TierForbidden` to the `app.deps` import; the new routes use
`run_in_threadpool(db.<get_fn>, ...)` for sqlite reads (same idiom as `api_presence`).

**Defensive dual-process table-init pattern (Pitfall 6)** (lines 270-281, `lifespan`):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_config()
    try:
        db.init_presence()
        db.init_view_counts()
    except Exception:
        log.exception("no pude inicializar las tablas de presencia/vistas")
    log.info("editor admin app started")
    yield
```
Add `db.init_heartbeat()`, `db.init_jinxxy_sync_status()`, `db.init_activity_log()` to
this SAME try/except block — do not create a second init path (Pitfall 6 is explicit
about this exact precedent).

**Exception-handler branch pattern to extend** (lines 312-327, `_auth_html_or_json`):
```python
@app.exception_handler(StarletteHTTPException)
async def _auth_html_or_json(request: Request, exc: StarletteHTTPException):
    if exc.status_code in (401, 403) and "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse(
            request, "login.html",
            {"forbidden": exc.status_code == 403},
            status_code=exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
```
Add a branch BEFORE the existing one: `if isinstance(exc, TierForbidden) and "text/html" in
...` → render `forbidden.html` with `{"required_tier": exc.required_tier}`. Keep the
existing `login.html` branch as the fallback for the plain 401/editor-403 case (Pitfall 2 —
extend, don't replace).

**Owner-gated GET+POST route pair pattern to copy for each new section route**
(lines 423-481, `settings_page`/`save_settings`):
```python
@app.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request, ident: dict = Depends(require_owner)):
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "editor.css"))
    except OSError:
        asset_v = 0
    return templates.TemplateResponse(
        request, "settings.html",
        {"groups": settings.all_for_ui(), "asset_v": asset_v},
    )
```
Each new `/overview`, `/gallery`, `/reviews`, `/reminders`, `/jinxxy`, `/meetings` route
follows this exact shape but with `Depends(require_manager)` instead of `require_owner`,
rendering `overview.html` (Overview) or `module_stub.html` (the 5 stubs) with a `roles`
dict (from the dependency return value) passed into every render for sidebar lock-icon
computation (Architecture Pattern 2). `/admin/settings` itself is UNCHANGED this phase
(still `require_owner`, still `settings.html` — Settings shell migration is Phase 4).

**JSON polling-endpoint pattern** (lines 340-352, `api_presence` — same
read-sqlite-return-JSON shape to copy for `/api/overview/status`):
```python
@app.get("/api/presence/{discord_id}")
async def api_presence(discord_id: str):
    row = await run_in_threadpool(db.get_presence, discord_id)
    return JSONResponse({"status": row["status"] if row else None})
```
`/api/overview/status` differs in being AUTH-GATED (`Depends(require_manager)`, not
public) — combine the read-sqlite-return-JSON shape with the route-gating shape above.

---

### `core/settings.py` (model/config-schema, CRUD)

**Analog:** `core/settings.py::_SCHEMA` (same file, lines 163-291, already fully read)

**`role_list` entry pattern to copy verbatim (with the two Pitfall-3/5-flagged deviations)**:
```python
"GALLERY_STAFF_ROLE_IDS": _Setting(
    "GALLERY_STAFF_ROLE_IDS", "gallery", "role_list",
    _env_role_ids("GALLERY_STAFF_ROLE_IDS"),
    _validate_role_id_list,
    label="Roles de staff de galería · Gallery staff roles",
),
```
New entries (RESEARCH.md Code Examples, verbatim key-casing per D-05 — see Pitfall 5,
planner must confirm this literal lowercase casing rather than auto-correcting to
`MANAGER_ROLE_IDS`):
```python
"manager_roles": _Setting(
    "manager_roles", "access", "role_list",
    [int(x) for x in os.getenv("MANAGER_ROLE_IDS", "1453560115423875205").split(",") if x.strip()],
    _validate_role_id_list,
    label="Roles con acceso de Manager · Manager-tier roles",
),
"editor_roles": _Setting(
    "editor_roles", "access", "role_list",
    [int(os.getenv("ROLE_MODERATOR_ID", "1418724526308593834"))],
    _validate_role_id_list,
    label="Roles con acceso de Editor · Editor-tier roles",
),
```
**Deviation from the copied pattern (deliberate, Pitfall 3):** do NOT add `fallback_key=`
to either entry — unlike `REVIEWS_STAFF_ROLE_IDS`/`REMINDERS_STAFF_ROLE_IDS`/
`JINXXY_STAFF_ROLE_IDS` (which cascade to `GALLERY_STAFF_ROLE_IDS`), these two are their
own independent mapping per D-05/D-06.

**Validator already exists, reuse as-is** (lines 71-89, `_validate_role_id_list`) — no
new validator needed; ID-length is intentionally lenient (comment at line 76-78).

---

### `core/db.py` (model/storage, CRUD)

**Analog:** `core/db.py::init_presence`/`set_presence`/`get_presence` (lines 526-555) and
`init_store_state`/`upsert_store_snapshot` (lines 374-424), both already fully read.

**Single-row `CHECK (id=1)` upsert pattern for the heartbeat table** — RESEARCH.md's Code
Examples already give the concrete `init_heartbeat`/`set_heartbeat` bodies (verbatim,
citing this same file's idiom); the key structural precedent to match is:
```python
def init_presence():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS presence (
                discord_id TEXT PRIMARY KEY,
                status     TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


def set_presence(discord_id, status: str):
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO presence (discord_id, status, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(discord_id) DO UPDATE SET status = excluded.status, "
            "updated_at = excluded.updated_at",
            (str(discord_id), status, now),
        )
```
`bot_heartbeat` uses `id INTEGER PRIMARY KEY CHECK (id = 1)` + `INSERT OR REPLACE`
instead (single global row, not per-discord_id) — same `_get_conn()`/`with conn:`/
parameterized-`?` discipline throughout, per `PRAGMA journal_mode=WAL` set in
`_get_conn()` (lines 7-16).

**One-table-per-concern, typed-columns idiom** (`init_store_state`, lines 374-393) is the
precedent for `jinxxy_sync_status` (timestamp, ok/error, product count) — do NOT combine
heartbeat/sync-status/activity-log into one JSON-blob table (RESEARCH.md "Alternatives
Considered" explicitly rejects this).

**Append-only bounded-retention pattern** — RESEARCH.md's Code Examples already give the
concrete `init_activity_log`/`log_activity`/`get_recent_activity` bodies, modeled on this
file's `save_post`/`add_reminder` insert idiom plus a purge-on-write `DELETE ... WHERE id
NOT IN (SELECT ... ORDER BY id DESC LIMIT ?)` (mirrors the existing view_dedup cutoff
delete pattern already in this file).

---

### `cogs/heartbeat.py` (new, service/background-task, event-driven)

**Analog:** `cogs/jinxxy.py`'s `@tasks.loop` shape (lines 125-146, 246-253) for the
loop/cog_unload/before_loop skeleton, plus `cogs/presence.py`'s `on_ready`
guild-resolve-then-write shape (lines 32-59, fully read).

**Cog lifecycle pattern** (`cogs/jinxxy.py` lines 125-146):
```python
class JinxxyCog(
    commands.GroupCog,
    name="Jinxxy",
    ...
):
    async def cog_unload(self):
        # Hot-reload safety — mirrors reminders.cog_unload so a reload doesn't leave a
        # second poll loop ticking.
        self._poll.cancel()
```

**Poll-loop + before_loop pattern** (`cogs/jinxxy.py` lines 246-253):
```python
    @tasks.loop(hours=config.JINXXY_POLL_HOURS)
    async def _poll(self):
        result = await self._run_sync()
        await self._announce(result)

    @_poll.before_loop
    async def _before_poll(self):
        # Wait until the gateway is ready so the announce channel resolves.
```
`cogs/heartbeat.py`'s `_beat` loop follows this exact `@tasks.loop(seconds=45)` +
`@_beat.before_loop` → `await self.bot.wait_until_ready()` shape (RESEARCH.md Code
Examples gives the concrete body — `db.init_heartbeat()` in `__init__`, `cog_unload`
cancels `_beat`, matching `cog_unload`'s cancel-on-unload idiom above).

**Guild-resolve-then-write pattern** (`cogs/presence.py` lines 48-59, `on_ready`):
```python
    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            log.warning("presence: guild %s no resuelto — omito el snapshot inicial", config.GUILD_ID)
            return
```
Reuse `self.bot.get_guild(config.GUILD_ID)` (with the `None`-guard) for the heartbeat's
`guild.member_count` read (Assumption A4 — fall back gracefully, e.g. `None`, if the
member cache isn't populated yet).

---

### `cogs/jinxxy.py` (extend `_run_sync`, event-driven)

**Analog:** `cogs/jinxxy.py::_run_sync` (lines 149+, orchestration entry point) — same
file, add ONE call to `db.set_jinxxy_sync_status(...)` at the end of `_run_sync` (both the
scheduled `_poll` path at line 246-249 and the manual `/tienda sync` command at line
269-285 funnel through this single method, so one instrumentation point covers both per
D-10/Phase 8 reuse note).

---

### `cogs/gallery.py` / `cogs/reviews.py` / `cogs/reminders.py` / `cogs/meeting.py`
### (extend with `activity_log` hook calls, event-driven)

**Analog:** `cogs/presence.py::_store` (lines 39-45) — the "on a Discord-side event,
write one row to shared sqlite, log-only on failure" idiom:
```python
    async def _store(self, member: discord.Member) -> None:
        status = str(getattr(member, "status", "offline"))
        try:
            await asyncio.to_thread(db.set_presence, member.id, status)
        except Exception:
            log.exception("presence: no pude guardar el estado (id=%s)", getattr(member, "id", "?"))
```
Each cog's notable-event handler (photo published/removed in `gallery.py`, review
approved in `reviews.py`, reminder fired in `reminders.py`, meeting posted in
`meeting.py`) adds one `await asyncio.to_thread(db.log_activity, event_type, message)`
call wrapped in the same `try/except Exception: log.exception(...)` shape — never let an
activity-log write failure abort the underlying Discord action (D-11 is additive
instrumentation, not a new failure mode).

---

### `app/templates/_dashboard_base.html` + `_sidebar.html` (component/layout+nav, request-response)

**Analog:** `app/templates/settings.html` (full file, 174 lines, already read) for the
Alpine `x-data` root + topbar shape; `.planning/sketches/001-dashboard-shell/index.html`
(lines 273-278, 303-319, 365-373) for the 7-section id/label/accent-var data and stat-tile
accent-bar markup.

**Topbar + `x-data` root pattern** (`settings.html` lines 22-33):
```html
<div x-data='settingsApp({{ groups | tojson }})' x-cloak>
  <header class="topbar">
    <h1 class="wordmark">Nocturna</h1>
    <span class="spacer"></span>
    <button class="btn btn--accent" type="button" @click="save()" :disabled="saving"
            x-text="saving ? 'Guardando… · Saving…' : 'Guardar ajustes · Save settings'"></button>
    <a class="btn btn--ghost" href="/editor">Volver al editor · Back to editor</a>
    <a class="btn btn--ghost" href="/logout">Salir · Sign out</a>
  </header>
```
Reuse the `<header class="topbar">` wordmark + `/logout` link shape for
`_dashboard_base.html`'s persistent chrome; the sidebar replaces the single-button topbar
action with the 7-section nav.

**Sketch section-data + accent-color pattern** (sketch `index.html` lines 273-278):
```js
{ id:'gallery',   ico:'🖼', name:'Galería',        acc:'var(--accent-gallery)',  toggle:true, on:true,  pend:3 },
{ id:'reviews',   ico:'★', name:'Reseñas',        acc:'var(--accent-reviews)',  toggle:true, on:true,  pend:1 },
{ id:'reminders', ico:'⏰', name:'Recordatorios',  acc:'var(--accent-reminders)',toggle:true, on:true },
{ id:'jinxxy',    ico:'🛍', name:'Tienda Jinxxy',  acc:'var(--accent-jinxxy)',   toggle:true, on:true },
{ id:'meetings',  ico:'🎙', name:'Reuniones',      acc:'var(--accent-meetings)', toggle:true, on:false },
{ id:'settings',  ico:'⚙', name:'Ajustes',        acc:'var(--accent-settings)' },
```
This is the exact id/label/accent-var mapping RESEARCH.md's Architecture Pattern 2
`_sidebar.html` example already codifies server-side (its `{% set sections = [...] %}`
data-driven loop is the correct Jinja translation of this JS array — copy that Jinja
shape, not the JS one, per the "server-computed lock state" anti-pattern guard).

**Stat-tile accent-bar markup** (sketch `index.html` lines 365-367):
```html
<div class="stat" style="--acc:var(--accent-jinxxy)"><div class="k">Última sync Jinxxy</div><div class="v" id="sync-v-${v}">hace 20 min</div><div class="d">${D.products.length} productos</div></div>
```
`overview.html`'s status tiles reuse this `class="stat"` + `style="--acc: ..."` + `.k`/`.v`/`.d`
(key/value/detail) shape for the bot-status/last-sync/activity tiles.

---

### `app/templates/overview.html` (component/page, request-response + polling)

**Analog:** `app/templates/settings.html`'s `save()`/`fetch()` Alpine method shape (lines
142-167) for the 30s poll-against-JSON-endpoint pattern:
```js
async save() {
  this.saving = true;
  try {
    const r = await fetch('/admin/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.serialize()),
    });
    const data = await r.json().catch(() => ({}));
    ...
  } catch (e) { ... } finally { this.saving = false; }
},
```
`overview.html`'s Alpine component does a `GET fetch('/api/overview/status')` on
`setInterval(..., 30000)` (D-12) instead of a POST-on-click, reusing the same
`fetch` → `.json()` → assign-to-reactive-state → `catch` shape.

---

### `app/templates/module_stub.html` (component/page, request-response)

**Analog:** `app/templates/settings.html`'s minimal-body-inside-chrome shape (no direct
"coming soon" analog exists in the repo — this is a NEW small template). Extends
`_dashboard_base.html` and supplies only a centered "coming soon" `{% block content %}`
with the section's accent color as a border/heading color (D-13) — structurally the
simplest possible child of the new base template, no interactive Alpine component
required (static page).

---

### `app/templates/forbidden.html` (component/error-page, request-response)

**Analog:** `app/templates/login.html`'s `{% if forbidden %}` 403 block (lines 19-28,
fully read):
```html
{% if forbidden %}
<p class="label">403 — Sin acceso · No access</p>
<p class="forbidden">
  Esta herramienta es solo para editores de Nocturna. Si deberías tener acceso,
  pídele a un mod que revise tu rol.
  <br /><br />
  This tool is for Nocturna editors only. If you should have access, ask a mod to
  check your role.
</p>
<a class="btn btn--ghost" href="/login">Reintentar · Try again</a>
{% endif %}
```
`forbidden.html` reuses this exact `.label` + `.forbidden` bilingual-paragraph + retry-link
shape, but (a) extends `_dashboard_base.html` (in-shell, per D-16) instead of standing
alone like `login.html`, and (b) parametrizes the copy on `required_tier` ("This section
needs Manager access" / "Esta sección requiere acceso de Manager") instead of the fixed
editor-only string — this is the whole point of Pitfall 2's "don't reuse `_FORBIDDEN_COPY`"
guidance.

---

### `app/templates/settings.html` (extend, component/form, CRUD)

**Analog:** `app/templates/settings.html` itself — the existing `role_list` field-type
branch (lines 50-54):
```html
<!-- role_list: comma-separated Discord IDs -->
<template x-if="setting.type === 'role_list'">
  <input type="text" placeholder="123, 456"
         x-model="values[setting.key]" />
</template>
```
No new field-type branch needed — `manager_roles`/`editor_roles` render through this
EXISTING `role_list` template branch automatically once `core/settings.py::all_for_ui()`
includes them in a group (D-07: raw role-ID input, server-validated, no dropdown picker).
Only change: add one `groupNames` entry (client-side JS dict, lines 118-125) so the new
`"access"` group shows a bilingual legend instead of falling back to the raw key string
(Open Question 2 in RESEARCH.md — trivial, ~1 line):
```js
const groupNames = {
  gallery: 'Galería · Gallery',
  reviews: 'Reseñas · Reviews',
  reminders: 'Recordatorios · Reminders',
  jinxxy: 'Tienda Jinxxy · Jinxxy store',
  meetings: 'Reuniones · Meetings',
  forum: 'Foro · Forum',
  // ADD: access: 'Acceso · Access',
};
```

---

### `tests/test_app_dashboard.py` (new, test)

**Analog:** `tests/test_app_settings.py` (full file, 194 lines, already read) — the
`client` fixture + `dependency_overrides` + `TestClient` tier-gate pattern:
```python
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "settings.db"), raising=False)
    settings.seed_defaults()

    app.dependency_overrides[require_owner] = lambda: _IDENT
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_owner, None)
```
```python
def test_manager_can_view_overview_but_not_settings():
    app.dependency_overrides[require_manager] = lambda: {"discord_id": "1", "is_owner": False,
                                                          "is_manager": True, "is_editor": False}
    with TestClient(app) as c:
        assert c.get("/overview").status_code == 200
    app.dependency_overrides.clear()
```
(RESEARCH.md's own Code Examples section already gives this exact `require_manager`
override snippet — copy verbatim as the seed test, then extend per the Phase Requirements
→ Test Map: `test_owner_full_access`, `test_manager_operational_access_settings_403`,
`test_editor_only_locked_out_of_dashboard`, `test_manager_cannot_edit_mapping`.)

**`tests/test_app_auth.py`'s fake-httpx pattern** (lines 43-100, already read) is the
analog for any NEW test exercising the OAuth callback's tier resolution directly (rather
than via `dependency_overrides`) — the `_FakeAsyncClient`/`_make_fake_client` shape mocks
`auth.httpx.AsyncClient` to record the `Authorization: Bot ...` header and return a
configurable `{"roles": [...]}` payload.

---

## Shared Patterns

### Live bot-token role read (single source of truth)
**Source:** `app/auth.py::has_editor_role` (lines 82-99)
**Apply to:** `app/auth.py` (generalized `_fetch_member_roles`), `app/deps.py`
(`_resolve_roles`)
```python
url = f"{DISCORD_API}/guilds/{config.GUILD_ID}/members/{user_id}"
headers = {"Authorization": f"Bot {config.BOT_TOKEN}"}  # NEVER the OAuth user token
async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
    resp = await client.get(url, headers=headers)
if resp.status_code == 404:
    return None  # not a guild member
resp.raise_for_status()
```
Never cache this in the session (D-02); never call it more than once per request
(Pitfall 4 — rely on FastAPI's `Depends(..., use_cache=True)` default).

### Fail-closed owner gate
**Source:** `app/deps.py::require_owner` (lines 69-94)
**Apply to:** Owner-tier resolution inside `_resolve_roles`/`app/auth.py::callback` — the
falsy-`DISCORD_USER_ID` guard MUST run before any identity comparison, and both operands
are `str()`-normalized before comparing (int config vs. str session value).

### Validated settings store (`role_list` type)
**Source:** `core/settings.py::_SCHEMA` + `_validate_role_id_list` (lines 71-89, 163-291)
**Apply to:** `manager_roles`/`editor_roles` schema entries, `settings.html`'s existing
`role_list` field-type template branch (no new UI code needed).

### Dual-process defensive table init
**Source:** `app/main.py::lifespan` (lines 270-281)
**Apply to:** `db.init_heartbeat()`, `db.init_jinxxy_sync_status()`,
`db.init_activity_log()` — add to the SAME `try/except Exception: log.exception(...)`
block, never a separate init path (Pitfall 6).

### Bot-writes / app-reads sqlite channel
**Source:** `cogs/presence.py` (writer) + `app/main.py::api_presence` (reader), `core/db.py`
`_get_conn()` WAL pragma (lines 7-16)
**Apply to:** heartbeat, jinxxy_sync_status, activity_log — the app process NEVER writes
these three tables, only `SELECT`s (Architecture Pattern 3).

### Distinguishable-exception → tier-aware 403 render
**Source:** `app/main.py::_auth_html_or_json` (lines 312-327), extended per Pitfall 2
**Apply to:** every `require_manager`-gated route; renders `forbidden.html` with
tier-specific bilingual copy instead of reusing `login.html`'s editor-only `_FORBIDDEN_COPY`.

### Server-computed lock state (no client-side gating)
**Source:** RESEARCH.md Architecture Pattern 2 (Jinja `{% set sections = [...] %}` loop),
Anti-Patterns section
**Apply to:** `_sidebar.html` — lock icons and nav-active state are computed from the
`roles` dict passed server-side into every render; NEVER from Alpine/JS-only logic (D-14).

## No Analog Found

None — every file in scope has at least a role-match analog already in the codebase
(RESEARCH.md's central finding: this phase is a direct extension of existing,
already-hardened patterns, not new architecture). The two genuinely new templates
(`module_stub.html`, `forbidden.html`) still borrow structurally from `settings.html`/
`login.html` respectively, as detailed above.

## Metadata

**Analog search scope:** `app/`, `core/`, `cogs/`, `app/templates/`, `tests/`,
`.planning/sketches/001-dashboard-shell/`
**Files scanned:** `app/auth.py`, `app/deps.py`, `app/main.py`, `core/settings.py`,
`core/db.py`, `cogs/presence.py`, `cogs/jinxxy.py`, `app/templates/settings.html`,
`app/templates/editor.html`, `app/templates/login.html`, `tests/conftest.py`,
`tests/test_app_settings.py`, `tests/test_app_auth.py`,
`.planning/sketches/001-dashboard-shell/index.html`,
`.planning/sketches/001-dashboard-shell/README.md`, `config.py`
**Pattern extraction date:** 2026-07-21
