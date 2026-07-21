# Phase 3: Dashboard Shell + Tiered Access - Research

**Researched:** 2026-07-21
**Domain:** FastAPI/Starlette session auth extension, Jinja+Alpine.js server-rendered dashboard, sqlite-backed bot↔app data plumbing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Login & tier resolution
- **D-01: Login gate = any mapped tier.** The OAuth callback resolves the user's tier
  from the role→tier mapping (plus the hardcoded owner ID). Anyone resolving to at
  least one tier gets a session; everyone else gets the existing rejection. One gate,
  extending the existing choke-point pattern in `app/auth.py` / `app/deps.py`.
- **D-02: Live re-check per request.** Every protected request re-reads live guild
  roles via the bot token and resolves the tier fresh — preserves the pinned
  `require_editor` stale-session invariant (instant revocation on role removal).
- **D-03: Multi-role users get the union of tier grants.** Tiers are additive grants,
  not exclusive levels: Manager + editor roles ⇒ 6 operational modules AND own editor
  page. (A Manager without the editor role does NOT get an editor page.)
- **D-04: Owner tier = hardcoded `DISCORD_USER_ID` bypass.** The owner resolves to
  owner tier before and independent of any role lookup. The role→tier mapping cannot
  express or remove ownership — this is the concrete "owner can never be locked out"
  guarantee. Fails closed when unset (existing `require_owner` invariant).

#### Role→tier mapping model
- **D-05: Mapping lives in the existing validated settings store** (`core/settings.py`)
  as two role-list keys: `manager_roles` (seeded with `1453560115423875205`) and
  `editor_roles` (seeded from `ROLE_MODERATOR_ID`). Reuses v1 validation, seeding,
  read-at-use, and UI plumbing. Seed must be byte-identical to current behavior until
  the owner edits (v1 compatibility constraint).
- **D-06: Multiple roles per tier.** Each tier holds a role list (settings store
  `role_list` type) — a second qualifying role needs no code change.
- **D-07: Editing UX = raw role-ID input fields** in the Settings section, exactly like
  the v1 settings form handles role lists, server-validated (`^\d{17,20}$`). Readable
  @role names arrive in Phase 4; dropdown pickers stay deferred (FUT-01).
- **D-08: `has_editor_role` unifies onto `editor_roles`.** The editor app gate reads
  the `editor_roles` list from the settings store (seeded from `ROLE_MODERATOR_ID`, so
  behavior is identical until edited). One source of truth for "who is an editor"
  across the editor app and the dashboard tier system.

#### Overview data plumbing
- **D-09: Rich bot status block.** A bot `@tasks.loop` writes a heartbeat (timestamp +
  gateway latency) into the shared sqlite every ~30–60s; the status block also shows
  uptime since start, guild member count, and loaded cogs. Overview shows Online iff
  the heartbeat is fresh. Shared sqlite is the channel (locked project decision — no
  IPC/HTTP).
- **D-10: Jinxxy poll records sync metadata now.** The existing periodic poll writes
  each run's outcome (timestamp, ok/error, product count) into the shared sqlite;
  Overview reads it. Phase 8's manual-sync status display reuses this exact record.
- **D-11: New append-only `activity_log` table** with a tiny helper the bot calls on
  notable events (photo published/removed, review approved, reminder fired, sync ran,
  meeting posted). Phase 3 instruments those existing cog events; Overview shows the
  last ~10. Later phases append panel-side actions to the same log.
- **D-12: Overview freshness = server-render on load + Alpine.js poll.** Status tiles
  re-fetch every ~30s while the tab is open. No websockets (out of scope).

#### Nav visibility & module stubs
- **D-13: The 5 not-yet-built module sections are coming-soon stubs** — real routes in
  the shell with their variant-A header + per-module color accent and a "coming soon"
  body. Satisfies "staff can navigate the 7 sections"; Phases 6–9 fill in the bodies.
- **D-14: Sidebar shows ALL sections, with lock icons on ungranted ones** (user chose
  visible-but-locked over hiding). Staff see the full feature map; server-side 403
  still enforced on every route regardless of nav rendering.
- **D-15: Editors get the shell too in Phase 3** — sidebar with everything locked
  except an "Editor" entry that links out to the existing `/editor` page. The existing
  editor flow itself is untouched; Phase 10 does the real integration.
- **D-16: Forbidden sections return a styled in-shell 403 page** ("This section needs
  Manager access"), bilingual copy in the style of the existing `_FORBIDDEN_COPY`.
  Locked nav items link to the section (and thus to this page) — the dead end is
  graceful. Status code is 403 (ACCESS-02).

### Claude's Discretion
- Heartbeat cadence, staleness threshold, activity-log retention/pruning, and exact
  Overview tile layout within the variant-A visual language.
- Settings form layout for the mapping fields (consistent with the v1 settings panel).
- Landing page per tier after login (Overview for owner/Manager is the natural default).

### Deferred Ideas (OUT OF SCOPE)
- **Short vanity URLs for editor pages** — e.g. `nocturna-avatars.site/shangri`
  instead of the current longer editor-page links. New capability (URL routing /
  domain-level change for the public presentation pages); candidate for Phase 10
  (editors integration) or roadmap backlog. Raised mid-discussion 2026-07-21.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SHELL-01 | Staff can navigate the 7 sections (Overview, Gallery, Reviews, Reminders, Jinxxy Store, Meetings, Settings) via a sidebar with a per-module color accent (sketch 001, variant A). | Architecture Pattern 2 (Jinja `{% extends %}` shell + `_sidebar.html` partial); Standard Stack (Alpine.js/Jinja already vendored); sketch 001 accent colors extracted in Architecture Patterns |
| SHELL-02 | Overview shows bot status (connection, last Jinxxy sync, recent activity). | Architecture Pattern 3 (bot writes / app reads plumbing); Code Examples (`bot_heartbeat`, `jinxxy_sync_status`, `activity_log` schemas + helpers); Pitfall 6 (dual-process table init) |
| ACCESS-01 | The owner can view and use every section, including Settings. | Pattern 1 (`_resolve_roles` / `is_owner`); existing `require_owner` in `app/deps.py` (unchanged, reused) |
| ACCESS-02 | A user with the Manager role (`1453560115423875205`) can view and use the 6 operational modules; Settings responds 403 for them. | Pattern 1 (`require_manager` dependency); Code Examples (`manager_roles` schema entry); Pitfall 2 (in-shell 403 copy) |
| ACCESS-03 | An editor can only access their presentation section. | Pattern 1 (`is_editor` resolution via `editor_roles`); D-08 unification of `has_editor_role`; Pitfall 1 (post-login redirect routing) |
| ACCESS-04 | The owner can edit the role→tier mapping from Settings; a Manager cannot self-elevate and the owner can never be locked out. | Security Domain (self-elevation / lockout STRIDE mapping); existing owner-gated `save_settings` choke point in `app/main.py` requires no new code path for the self-elevation guarantee |
</phase_requirements>

## Summary

Phase 3 extends an **existing, already-hardened** FastAPI admin app (`app/main.py`, `app/auth.py`,
`app/deps.py`) rather than building auth from scratch. The codebase already has: Discord OAuth2 via
Authlib, a live bot-token role-read pattern (`has_editor_role`), a fail-closed owner gate
(`require_owner`), a validated sqlite settings store with a `role_list` type and per-section grouping
(`core/settings.py`), and a proven bot→app sqlite-only data channel (`core/db.py`, WAL mode, used
today for presence/view-counts). Every mechanism this phase needs — tier resolution, mapping storage,
heartbeat/status plumbing, activity logging — is a **direct extension of these existing patterns**,
not a new library or architecture.

The main design work is: (1) generalizing the single-role editor gate into a 3-tier
(owner/manager/editor) union-based resolver that re-reads live Discord roles on every request
(preserving the pinned stale-session invariant), (2) adding two new `role_list` settings keys
(`manager_roles`, `editor_roles`) to the existing schema so the owner-only settings-save choke point
automatically enforces "Manager cannot self-elevate", (3) three new sqlite tables (heartbeat,
Jinxxy sync status, activity log) following the exact `CREATE TABLE IF NOT EXISTS` / dual-process-init
idiom already used for `presence`/`view_counts`, and (4) a Jinja base-layout + partial for the sidebar
shell (variant A from sketch 001) so the 7-section chrome isn't duplicated across every page.

**Primary recommendation:** Do not introduce any new package. Generalize `has_editor_role` /
`require_editor` / `require_owner` into a small tier-resolution layer that shares one live
Discord REST read per request (via FastAPI's built-in dependency caching), gate the new
`manager_roles`/`editor_roles` settings exactly like every other `role_list` tunable already in
`core/settings.py`, and build the shell as a Jinja `{% extends %}` base template + Alpine.js
polling for Overview — identical toolchain to `editor.html`/`settings.html` today.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OAuth identify + tier resolution | API / Backend (`app/auth.py`) | — | Trust boundary must stay server-side; bot token never reaches browser |
| Live role re-check per request | API / Backend (`app/deps.py`) | — | Pinned stale-session invariant (Pitfall 2) requires fresh REST read, not cached session data |
| Role→tier mapping storage | Database / Storage (`core/settings.py` + sqlite `settings` table) | — | Reuses validated, allowlisted config store; no new storage mechanism |
| Role→tier mapping edit UI | API / Backend (`/admin/settings` POST, owner-gated) | Frontend Server (Jinja `settings.html`) | Existing atomic validate-then-write endpoint; owner-only gate is the self-elevation guard |
| Sidebar nav + lock icons | Frontend Server (Jinja SSR) | — | Server computes per-tier lock state at render time; no client-side auth logic (never trust JS for gating) |
| Section route enforcement (403) | API / Backend (`require_manager`/`require_owner` deps) | — | Server-side 403 regardless of what the nav renders (D-14) |
| Overview status data collection | Bot process (`@tasks.loop` heartbeat, Jinxxy poll cog) | Database / Storage (sqlite tables) | Bot is the only process with a live gateway connection; app is read-only consumer |
| Overview status display | Frontend Server (SSR on load) | Browser / Client (Alpine.js 30s poll) | D-12: no websockets; poll is sufficient at this scale |
| Activity log writes | Bot process (cog event hooks) | Database / Storage (`activity_log` table) | Bot observes the Discord-side events (photo published, review approved, etc.) |
| Module stub pages (Gallery/Reviews/Reminders/Jinxxy/Meetings bodies) | Frontend Server (Jinja stub template) | — | D-13: real routes, coming-soon body; real logic is Phases 6-9 |

## Standard Stack

### Core (all already installed — no new dependency this phase)

| Library | Version (verified installed) | Purpose | Why Standard (for this repo) |
|---------|---------|---------|--------------|
| FastAPI | 0.139.0 `[VERIFIED: pip show]` | Route/dependency layer for the shell + tier gates | Already the app framework (`app/main.py`) |
| Starlette | 1.3.1 `[VERIFIED: pip show]` (bundled transitively via FastAPI) | `SessionMiddleware`, `HTTPException` | Already provides the signed session cookie |
| Authlib | 1.7.2 `[VERIFIED: pip show]` | OAuth2 client (state/CSRF handling) | Already wired in `app/auth.py`; never hand-roll OAuth |
| discord.py | 2.5.2 `[VERIFIED: pip show]` | Bot-side `@tasks.loop` heartbeat, gateway data (latency, member count, cogs) | Already the bot framework |
| httpx | (already a transitive dep, used in `app/auth.py`) | Bot-token REST role reads | Existing async client wrapper, timeout-bounded |
| Jinja2 (via `fastapi.templating.Jinja2Templates`) | already used | Server-rendered shell/sidebar/section pages | Existing template engine, no build step (MANIFEST.md constraint) |
| Alpine.js | 3.15.12 vendored `[VERIFIED: app/main.py docstring + app/static/alpine.min.js present]` | Overview 30s status polling, settings form reactivity | Already vendored (not CDN); zero new asset to add |
| sqlite3 (stdlib) | Python 3.12.8 `[VERIFIED: pip show / python --version]` | Heartbeat, sync-status, activity-log tables | Existing `core/db.py` idiom (WAL, `CREATE TABLE IF NOT EXISTS`) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.1.1 `[VERIFIED: pip show]` | Test suite | Already the test runner (`tests/`) |
| `fastapi.testclient.TestClient` | bundled with FastAPI | Route-level 200/403 tests per tier | Already the pattern in `tests/test_app_settings.py` (dependency_overrides) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Live per-request Discord REST role re-check | Cache tier in signed session, re-check less often | Breaks the pinned Pitfall-2 stale-session invariant (instant revocation on role removal) — CONTEXT.md D-02 explicitly locks this in, not a real option |
| FastAPI dependency caching for shared role fetch | Hand-rolled `request.state` memoization | FastAPI's built-in `use_cache=True` (default) already dedupes a dependency called multiple times in one request — no custom code needed `[CITED: fastapi.tiangolo.com/reference/dependencies]` |
| Jinja `{% extends %}` base layout for the shell | Copy-paste the sidebar HTML into every section template | Template inheritance is the standard Jinja pattern for shared chrome; copy-paste would duplicate the 7-item nav + lock-icon logic across 7+ files |
| New `bot_heartbeat`/`jinxxy_sync_status`/`activity_log` sqlite tables | A single combined "overview_state" JSON blob table | Existing schema idiom is one table per concern with typed columns (`gallery_state`, `store_snapshot`, `presence`) — consistent with repo convention, easier to query/index individually |

**Installation:**
```bash
# No install needed — every library above is already in the environment.
pip show fastapi discord.py authlib httpx  # confirms versions in place
```

**Version verification:** All versions above were confirmed with `pip show <pkg>` in the project's
active Python 3.12.8 (miniconda) environment on 2026-07-21 — not training-data guesses.

## Package Legitimacy Audit

**No external packages are introduced by this phase.** Every capability (OAuth, session, sqlite,
Jinja, Alpine.js, discord.py tasks loop) reuses a dependency already installed and already exercised
by the existing codebase (verified via `pip show` above and via direct import/grep of `app/main.py`,
`app/auth.py`, `core/db.py`). The Package Legitimacy Gate protocol (slopcheck + registry check) is
therefore not applicable — there is no `pip install` / `npm install` step for the planner to gate.

`slopcheck` itself was confirmed installed and available in this environment (`pip show slopcheck` →
0.6.1) in case a later plan revision does introduce a new package; run it at that time.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | — | No new packages this phase |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Discord Guild (live roles)                                              │
└───────────────┬─────────────────────────────────┬───────────────────────┘
                │ Bot-token REST read              │ Gateway events
                │ (role membership, per request)   │ (presence, latency,
                ▼                                   │  member count, cog
┌───────────────────────────────┐                  │  events: photo/review/
│ FastAPI app process            │                  │  reminder/sync/meeting)
│ (app/main.py, app/auth.py,     │                  ▼
│  app/deps.py)                  │      ┌───────────────────────────────┐
│                                 │      │ discord.py Bot process        │
│ 1. OAuth callback:              │      │ (bot.py, cogs/*)               │
│    identify → live role read →  │      │                                │
│    resolve tiers → session      │      │ • Heartbeat @tasks.loop        │
│    (discord_id ONLY, D-02)      │      │   (~30-60s) → bot_heartbeat    │
│                                 │      │ • Jinxxy poll cog → writes     │
│ 2. Every dashboard route:       │      │   jinxxy_sync_status each run  │
│    require_manager/require_     │      │ • Gallery/Reviews/Reminders/   │
│    owner dependency → LIVE      │      │   Jinxxy/Meetings cogs →       │
│    re-read roles (fresh, not    │      │   activity_log.append() on     │
│    session-cached) → 200 or     │      │   notable events               │
│    styled in-shell 403          │      └───────────────┬────────────────┘
│                                 │                       │ writes (WAL)
│ 3. Sidebar SSR: compute lock    │                       ▼
│    icons per tier, render       │      ┌───────────────────────────────┐
│    7-section chrome + Editor    │◄─────┤ Shared sqlite (bot.db)        │
│    link                         │ reads│ settings | bot_heartbeat |    │
│                                 │      │ jinxxy_sync_status |           │
│ 4. GET /api/overview/status     │      │ activity_log | presence | ...  │
│    (JSON, Alpine 30s poll)      │      └───────────────────────────────┘
└───────────────┬─────────────────┘
                │ HTML / JSON
                ▼
┌───────────────────────────────┐
│ Browser (staff member)         │
│ Alpine.js: settingsApp-style    │
│ x-data component per section;   │
│ Overview polls the status       │
│ endpoint every ~30s             │
└───────────────────────────────┘
```

The primary use case (a Manager loading Overview) traces: guild role → OAuth callback (live read) →
session with `discord_id` only → GET `/overview` → `require_manager` dependency re-reads roles live →
200 → Jinja renders sidebar (Settings locked) + Overview tiles from `bot_heartbeat` /
`jinxxy_sync_status` / `activity_log` (written by the separate bot process) → Alpine polls
`/api/overview/status` every 30s for the same three reads.

### Recommended Project Structure

```
app/
├── auth.py              # ADD: _fetch_member_roles() (shared REST read),
│                         #      resolve_tiers(discord_id) -> {is_owner, is_manager, is_editor}
│                         #      has_editor_role() → read editor_roles from settings (D-08)
├── deps.py               # ADD: require_manager (403 unless is_owner or is_manager)
│                         #      keep require_owner / require_editor as-is
├── main.py               # ADD: /overview, /gallery, /reviews, /reminders, /jinxxy,
│                         #      /meetings routes (owner+manager gated; stub bodies per D-13)
│                         #      /api/overview/status (JSON, same gate, Alpine poll target)
│                         #      Settings route stays /admin/settings (unchanged this phase)
├── templates/
│   ├── _dashboard_base.html   # NEW: shared topbar + sidebar layout, {% block content %}
│   ├── _sidebar.html          # NEW: 7-section nav partial, lock icons from tiers dict
│   ├── overview.html          # NEW: extends _dashboard_base, Overview tiles + Alpine poll
│   ├── module_stub.html       # NEW: generic "coming soon" body, accent color per module
│   ├── forbidden.html         # NEW: in-shell 403 (D-16), distinct from login.html's 403
│   ├── settings.html          # EXTEND: 2 new role_list fields (manager_roles, editor_roles)
│   ├── editor.html            # unchanged
│   └── login.html             # unchanged (still used for 401/no-tier-at-all)
core/
├── settings.py           # ADD: manager_roles / editor_roles _Setting entries (role_list)
├── db.py                 # ADD: init_heartbeat/get_heartbeat/set_heartbeat
│                         #      init_jinxxy_sync_status/get/set
│                         #      init_activity_log/log_activity/get_recent_activity
cogs/
├── heartbeat.py          # NEW (or fold into an existing always-loaded cog): @tasks.loop
│                         #      writes timestamp+latency+uptime+member_count+loaded_cogs
├── jinxxy.py             # EXTEND: _run_sync() also writes jinxxy_sync_status
├── gallery.py / reviews.py / reminders.py / meeting.py
│                         # EXTEND: call activity_log helper on notable events
```

### Pattern 1: Single live-role-read shared across tier dependencies (FastAPI dependency caching)
**What:** One `async def _resolve_roles(request) -> dict` dependency does the bot-token REST
read exactly once; `require_manager`, `require_owner`-equivalent checks, and the sidebar's
lock-icon computation all `Depends()` on it. FastAPI caches the result for the lifetime of one
request (default `use_cache=True`), so a single page needing "is this the owner AND is Settings
locked AND is Gallery locked" costs exactly one Discord REST call, not three.
**When to use:** Any route/template context that needs more than one tier fact.
**Example:**
```python
# Source: pattern extension of app/deps.py's existing require_editor/require_owner;
# caching behavior confirmed at fastapi.tiangolo.com/reference/dependencies (default use_cache=True)
async def _resolve_roles(request: Request) -> dict:
    discord_id = request.session.get("discord_id")
    if not discord_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    is_owner = bool(config.DISCORD_USER_ID) and str(discord_id) == str(config.DISCORD_USER_ID)
    role_ids = await auth._fetch_member_roles(discord_id)  # one bot-token REST call
    if role_ids is None:  # not a guild member
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)
    manager_ids = {str(r) for r in settings.get("manager_roles")}
    editor_ids = {str(r) for r in settings.get("editor_roles")}
    is_manager = bool(role_ids & manager_ids)
    is_editor = bool(role_ids & editor_ids)
    if not (is_owner or is_manager or is_editor):
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)  # D-01 login gate
    return {"discord_id": discord_id, "is_owner": is_owner,
            "is_manager": is_manager, "is_editor": is_editor}


async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise HTTPException(status_code=403, detail=_MANAGER_FORBIDDEN_COPY)
    return roles
```

### Pattern 2: Jinja `{% extends %}` shell layout, server-computed lock state
**What:** One base template owns the topbar + sidebar; every section extends it and only
supplies `{% block content %}`. Lock icons and the "is this nav item active" state are computed
server-side from the `roles` dict passed into every render — never client-side JS gating.
**When to use:** All 7 section pages + the forbidden page (D-16) + module stubs (D-13).
**Example:**
```html
{# app/templates/_sidebar.html — Source: pattern extension of settings.html/editor.html topbar #}
{% set sections = [
  ('overview', 'Overview', 'var(--color-primary)', roles.is_owner or roles.is_manager),
  ('gallery', 'Galería', 'var(--accent-gallery)', roles.is_owner or roles.is_manager),
  ('reviews', 'Reseñas', 'var(--accent-reviews)', roles.is_owner or roles.is_manager),
  ('reminders', 'Recordatorios', 'var(--accent-reminders)', roles.is_owner or roles.is_manager),
  ('jinxxy', 'Tienda Jinxxy', 'var(--accent-jinxxy)', roles.is_owner or roles.is_manager),
  ('meetings', 'Reuniones', 'var(--accent-meetings)', roles.is_owner or roles.is_manager),
  ('settings', 'Ajustes', 'var(--accent-settings)', roles.is_owner),
] %}
<aside class="side">
  {% for id, label, acc, unlocked in sections %}
  <a href="/{{ id if id != 'settings' else 'admin/settings' }}"
     class="side-item {{ 'active' if id == active_section else '' }}"
     style="--acc: {{ acc }}">
    {{ label }} {% if not unlocked %}<span class="lock">🔒</span>{% endif %}
  </a>
  {% endfor %}
  {% if roles.is_editor %}
  <a href="/editor" class="side-item">Editor</a>
  {% endif %}
</aside>
```

### Pattern 3: Overview data plumbing — bot writes, app reads, Alpine polls
**What:** Bot-side `@tasks.loop` and cog hooks are the ONLY writers of `bot_heartbeat`,
`jinxxy_sync_status`, `activity_log`; the app only ever `SELECT`s. This mirrors the existing
`presence` table exactly (`cogs/presence.py` writes, `/api/presence/<id>` in `app/main.py` reads).
**Example:**
```python
# Source: pattern extension of cogs/presence.py + core/db.py::init_presence idiom
# core/db.py
def init_heartbeat():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_heartbeat (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                last_beat_utc      TEXT NOT NULL,
                latency_ms         REAL,
                started_at_utc     TEXT NOT NULL,
                guild_member_count INTEGER,
                loaded_cogs        TEXT  -- JSON list
            )
        """)

def set_heartbeat(latency_ms, started_at_utc, guild_member_count, loaded_cogs):
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO bot_heartbeat
                (id, last_beat_utc, latency_ms, started_at_utc, guild_member_count, loaded_cogs)
            VALUES (1, ?, ?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), latency_ms, started_at_utc,
              guild_member_count, json.dumps(loaded_cogs)))
```
```python
# cogs/heartbeat.py (new, small, always-loaded cog)
import time
from discord.ext import commands, tasks
from core import db

class HeartbeatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._started_at = datetime.now(timezone.utc).isoformat()
        db.init_heartbeat()
        self._beat.start()

    def cog_unload(self):
        self._beat.cancel()

    @tasks.loop(seconds=45)  # Claude's discretion cadence — see Open Questions
    async def _beat(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        await asyncio.to_thread(
            db.set_heartbeat,
            latency_ms=round(self.bot.latency * 1000, 1),
            started_at_utc=self._started_at,
            guild_member_count=guild.member_count if guild else None,
            loaded_cogs=list(self.bot.cogs.keys()),
        )

    @_beat.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()
```

### Anti-Patterns to Avoid
- **Storing resolved tier in the session cookie:** Breaks D-02's live re-check invariant — a
  role removed mid-session would still show as granted until the cookie expires (up to 6h TTL).
- **Client-side (Alpine/JS) nav gating:** The sidebar must render lock icons from SERVER-computed
  tier facts; a hidden/disabled-only-in-JS nav item is not a security boundary (D-14 explicitly
  requires the 403 to be enforced server-side regardless of nav rendering).
- **Reusing `_FORBIDDEN_COPY`/`login.html`'s 403 for tier denials:** That copy says "this tool is
  for editors only" — wrong message for a Manager hitting Settings. D-16 requires distinct,
  section-aware copy ("This section needs Manager access") rendered in-shell, not the login page.
- **Conflating per-module staff-role lists with dashboard tiers:** `GALLERY_STAFF_ROLE_IDS`,
  `REVIEWS_STAFF_ROLE_IDS`, etc. already exist and gate the Discord-reaction approve/remove flows
  (unrelated to this phase). `manager_roles`/`editor_roles` are a NEW, separate concept gating
  *dashboard visibility*. Do not merge these lists or let one implicitly seed the other — they can
  legitimately hold different role IDs, and Phase 3's mapping editor only ever touches
  `manager_roles`/`editor_roles`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| OAuth2 state/CSRF handling | A custom state-token generator/verifier | Authlib (`oauth.discord.authorize_access_token`) — already wired | Already audited in `app/auth.py`; hand-rolling reintroduces CSRF risk |
| Session signing | A custom cookie signer | Starlette `SessionMiddleware` (itsdangerous) — already wired | Already the app's session mechanism; no reason to add a second one |
| Per-request role fetch de-duplication | A custom `request.state` cache dict | FastAPI's built-in dependency caching (`Depends(..., use_cache=True)` default) | Framework-native, zero extra code, verified via official docs |
| Role-ID list validation | A new regex/parser | `core/settings.py::_validate_role_id_list` — already exists, already tested | Exact same shape as `GALLERY_STAFF_ROLE_IDS` etc.; reuse the schema type |
| 401 vs 403 HTML rendering for browser navigations | A new per-route try/except | Extend the existing `@app.exception_handler(StarletteHTTPException)` in `app/main.py` | Already distinguishes JSON (fetch) vs HTML (navigation) responses; add a tier-aware branch rather than a parallel mechanism |
| Sidebar/nav rendering logic | A JS-side router or SPA framework | Server-rendered Jinja `{% extends %}` + a data-driven `{% for %}` over a small Python list | MANIFEST.md locks "FastAPI + Jinja + Alpine.js (no build step)" — anything SPA-shaped contradicts the stack decision |
| Overview live-status polling | WebSockets / SSE | Alpine.js `setInterval`-style poll against a JSON endpoint (D-12, explicitly out of scope: real-time websockets) | Explicitly locked out of scope by REQUIREMENTS.md |

**Key insight:** Nothing in this phase requires a new library. The single biggest risk is
re-implementing something that already exists one file over (e.g. a second role-list validator,
a second OAuth flow, a second session mechanism) instead of generalizing the existing one.

## Common Pitfalls

### Pitfall 1: `/` root-route collision with the existing editor page
**What goes wrong:** `app/main.py` currently mounts `editor_page` at BOTH `GET /` and `GET /editor`,
and `auth.py::POST_LOGIN_REDIRECT` is a hardcoded `"/"`. Adding a dashboard shell without touching
this means every login — including an owner/Manager — lands back on the editor page.
**Why it happens:** The redirect target was fixed before tiers existed (Phase 2, only editors).
**How to avoid:** Compute the post-login redirect from the resolved tier INSIDE the OAuth callback
(still a fixed, server-chosen internal path per tier — never client input, preserving the existing
open-redirect guard): owner/Manager → `/overview`, editor-only → `/editor` (unchanged). Multi-tier
users (Manager + editor role, D-03) land on `/overview` (the operational default) with the Editor
link available in the sidebar.
**Warning signs:** A Manager login redirecting to the block editor instead of Overview.

### Pitfall 2: Reusing `login.html`'s 403 copy/handler for tier denials
**What goes wrong:** The existing `_auth_html_or_json` exception handler renders `login.html` with
`{"forbidden": exc.status_code == 403}` for ANY 401/403 raised anywhere in the app when the request
accepts HTML. A Manager hitting `/admin/settings` would see "this tool is for editors only" — wrong
and confusing copy (D-16 wants "This section needs Manager access").
**Why it happens:** One handler currently serves one 403 message for one audience (editors).
**How to avoid:** Raise a distinguishable exception (e.g. a `TierForbidden(HTTPException)` subclass
carrying the required tier name) from `require_manager`/settings-section gates, and extend the
handler to render `forbidden.html` with tier-specific bilingual copy for that subclass, falling back
to the existing `login.html` behavior for the plain 401/editor-403 case. Do not replace the existing
handler wholesale — extend it.
**Warning signs:** Wrong 403 copy showing for a Manager; test asserting exact response body text.

### Pitfall 3: Confusing dashboard tiers with existing per-module staff-role lists
**What goes wrong:** `GALLERY_STAFF_ROLE_IDS`, `REVIEWS_STAFF_ROLE_IDS`, `REMINDERS_STAFF_ROLE_IDS`,
`JINXXY_STAFF_ROLE_IDS` already exist in `core/settings.py` and gate today's Discord-reaction
approve/remove flows. It's tempting to reuse one of these as "the Manager role list" or to have
`manager_roles` fall back to `GALLERY_STAFF_ROLE_IDS` the way those four already cascade to each
other (`fallback_key`).
**Why it happens:** They look like the same concept ("who can approve stuff") and the codebase
already has a fallback-cascade mechanism (`CONF-03`) that's easy to copy by habit.
**How to avoid:** Keep `manager_roles`/`editor_roles` as their OWN independent `role_list` entries
with NO `fallback_key` — CONTEXT.md's D-05/D-06 describe them as a new, separate mapping the owner
edits explicitly; they are seeded once (Manager role literal + `ROLE_MODERATOR_ID`) and never
silently inherit from the module-specific lists.
**Warning signs:** Editing `GALLERY_STAFF_ROLE_IDS` unexpectedly changing dashboard access, or vice versa.

### Pitfall 4: N+1 Discord REST calls per page load
**What goes wrong:** If the sidebar partial, the route dependency, and the page body each
independently call `has_editor_role`/a role-fetch function, one page load makes 3+ live Discord API
calls, multiplying latency and rate-limit exposure.
**Why it happens:** `require_editor`/`has_editor_role` today is called exactly once per route by
design (one dependency, one page) — a 3-tier system with sidebar-wide lock-icon rendering naturally
wants the SAME role facts in more than one place.
**How to avoid:** Structure tier resolution as ONE dependency (`_resolve_roles`) that every other
dependency AND the route handler itself depends on via `Depends()` — FastAPI's default
`use_cache=True` collapses repeat calls within one request to a single execution (verified,
see Architecture Pattern 1 / Sources).
**Warning signs:** Discord API rate-limit warnings in logs correlating with dashboard traffic.

### Pitfall 5: Schema key naming inconsistency (`manager_roles`/`editor_roles` vs. existing UPPER_SNAKE_CASE keys)
**What goes wrong:** Every existing `_SCHEMA` key in `core/settings.py` is `UPPER_SNAKE_CASE`
matching a `.env` variable name (`GALLERY_STAFF_ROLE_IDS`, `REVIEWS_CHANNEL_ID`, ...). CONTEXT.md's
D-05 names the two new keys in `lower_snake_case` (`manager_roles`, `editor_roles`) — these have no
corresponding `.env` variable (Manager role is a brand-new concept; editor role reuses
`ROLE_MODERATOR_ID` but under a different key name). If the planner doesn't decide explicitly, an
executor may "auto-correct" to `MANAGER_ROLE_IDS`/`EDITOR_ROLE_IDS` for consistency, silently
diverging from the locked CONTEXT.md decision.
**How to avoid:** The planner should make an explicit, written call: either keep the CONTEXT.md
literal lowercase keys (breaking the naming convention, but matching the locked decision text
verbatim) or get an amendment. This research flags it — see Open Questions.
**Warning signs:** Grep for `manager_roles` and `MANAGER_ROLE_IDS` both appearing in the codebase.

### Pitfall 6: New sqlite tables created by only one process
**What goes wrong:** If `bot_heartbeat`/`jinxxy_sync_status`/`activity_log` init functions are only
ever called from the bot process, the app process 500s reading them whenever it starts before the
bot has run at least once (fresh deploy, bot down for maintenance, etc.).
**Why it happens:** Easy to add the `init_*()` call only where the table is naturally "owned"
(the bot cog's `__init__`).
**How to avoid:** Follow the EXACT precedent already in `app/main.py`'s `lifespan()`: it defensively
calls `db.init_presence()` and `db.init_view_counts()` at app startup specifically so `/api/presence`
never 500s "if the bot ... hasn't started yet." Add the three new `init_*()` calls to that same
`lifespan()` try/except block.
**Warning signs:** 500 errors on Overview immediately after a fresh deploy or app-only restart.

## Code Examples

### Extending the settings schema for the two new tier-mapping keys
```python
# Source: pattern match to core/settings.py's existing role_list entries (e.g. GALLERY_STAFF_ROLE_IDS)
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
Note: `manager_roles`/`editor_roles` are the literal CONTEXT.md D-05 key names (see Pitfall 5 /
Open Questions on the naming-convention mismatch this creates).

### Activity log helper (append-only, bounded)
```python
# Source: pattern extension of core/db.py's existing insert idioms (save_post/add_reminder)
def init_activity_log():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

def log_activity(event_type: str, message: str, keep_last: int = 500):
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO activity_log (event_type, message, created_at) VALUES (?, ?, ?)",
            (event_type, message, datetime.now(timezone.utc).isoformat()),
        )
        # Bounded retention, purge-on-write — same idiom as view_dedup's cutoff delete.
        conn.execute("""
            DELETE FROM activity_log WHERE id NOT IN (
                SELECT id FROM activity_log ORDER BY id DESC LIMIT ?
            )
        """, (keep_last,))

def get_recent_activity(limit: int = 10):
    with _get_conn() as conn:
        return conn.execute(
            "SELECT event_type, message, created_at FROM activity_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
```

### FastAPI TestClient tier-gate test (mirrors existing `tests/test_app_settings.py` exactly)
```python
# Source: tests/test_app_settings.py (existing repo pattern) — confirmed via grep, not assumed
from fastapi.testclient import TestClient
from app.deps import require_manager
from app.main import app

def test_manager_can_view_overview_but_not_settings():
    app.dependency_overrides[require_manager] = lambda: {"discord_id": "1", "is_owner": False,
                                                          "is_manager": True, "is_editor": False}
    with TestClient(app) as c:
        assert c.get("/overview").status_code == 200
        # Settings still uses require_owner — a manager override does not satisfy it.
    app.dependency_overrides.clear()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Single "editor role" boolean gate (`has_editor_role`) | 3-tier union resolver (owner/manager/editor) | This phase | `require_editor` narrows to read `editor_roles` from the settings store instead of the hardcoded `config.ROLE_MODERATOR_ID` constant (D-08); behavior is identical until the owner edits the new setting |
| Fixed `POST_LOGIN_REDIRECT = "/"` | Tier-computed, still-fixed (server-side) redirect | This phase | Owner/Manager land on `/overview`; pure editors keep landing on `/editor` |
| One flat settings panel page | Settings stays a flat page this phase; SETT-01 migration into the shell chrome is Phase 4 | Phase boundary (CONTEXT.md) | Do not attempt to re-skin `settings.html` into the new sidebar layout in Phase 3 — out of this phase's scope per the phase boundary text |

**Deprecated/outdated:** None — this is additive to a young (2026) codebase; nothing here replaces
a legacy pattern outside this repo's own Phase 2 work.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `manager_roles`/`editor_roles` should be added to `core/settings.py`'s `_SCHEMA` dict with group `"access"` and NO `fallback_key` | Code Examples, Pitfall 3 | Low — this is a direct, low-risk extension of an existing, well-tested pattern; group name is cosmetic and easily renamed |
| A2 | A 45-second heartbeat cadence with staleness threshold ≈2x cadence (90s) is a reasonable default | Architecture Pattern 3 | Low — explicitly called out as Claude's Discretion in CONTEXT.md; easy to tune post-hoc, no migration cost |
| A3 | `activity_log` retention of 500 rows (purge-on-write) is sufficient for "recent ~10" display | Code Examples | Low — retention/pruning strategy is explicitly Claude's Discretion in CONTEXT.md |
| A4 | `bot.get_guild(config.GUILD_ID).member_count` is populated and accurate given the already-enabled `members`+`presences` intents | Code Examples | Low-Medium — standard discord.py behavior, not independently verified against a live guild in this research session; if member_count is `None`/stale before full member cache population, Overview should fall back gracefully (e.g. show "—") |

**If this table is empty:** N/A — see rows above. All other factual claims in this document were
verified directly against this repository's source files (`Read`/`Grep`) or via `pip show` /
`python --version`, which are authoritative for this codebase and environment.

## Open Questions

1. **Schema key casing: `manager_roles`/`editor_roles` (CONTEXT.md literal) vs. `MANAGER_ROLE_IDS`/`EDITOR_ROLE_IDS` (repo convention)**
   - What we know: Every existing `_SCHEMA` key is `UPPER_SNAKE_CASE` matching a `.env` name;
     CONTEXT.md's locked D-05 decision spells the two new keys in `lower_snake_case`.
   - What's unclear: Whether CONTEXT.md's casing was a deliberate choice or informal shorthand
     during discussion.
   - Recommendation: Planner should pick ONE explicitly and note it in the plan (recommend keeping
     the CONTEXT.md literal spelling verbatim, since it's a locked decision text and changing it
     is a scope decision, not an implementation detail) — do not leave it to per-task inference.

2. **Does `settings.html`'s new "access"/tier fieldset need bilingual group-label wiring?**
   - What we know: `settings.html`'s client-side `groupNames` JS dict currently hardcodes
     `gallery`/`reviews`/`reminders`/`jinxxy`/`meetings`/`forum` → bilingual legends; an unmapped
     group key falls back to the raw key string (visible but untranslated).
   - What's unclear: Whether the planner wants a polished bilingual legend for the new group in
     Phase 3 or accepts the raw-key fallback until Phase 4's settings migration.
   - Recommendation: Add one `groupNames` entry (~1 line) while touching this file anyway — trivial
     cost, avoids a visibly rough edge in an owner-facing form.

3. **Should `cogs/presence.py`'s `_is_editor` also read from the new `editor_roles` setting?**
   - What we know: D-08 explicitly unifies `has_editor_role` (the app's OAuth/editor-app gate) onto
     `editor_roles`. `presence.py` has its own separate `_is_editor` helper (still hardcoded to
     `config.ROLE_MODERATOR_ID`) used only for the Discord-presence-dot feature on public editor pages.
   - What's unclear: CONTEXT.md's D-08 text only names "the editor app and the dashboard tier
     system" — presence tracking isn't explicitly listed.
   - Recommendation: Leave `presence.py` untouched in Phase 3 (smaller diff, presence is a cosmetic
     feature, not an access-control boundary) unless the planner wants full single-source-of-truth
     consistency now; flag as a possible fast-follow.

4. **Does the Settings sidebar entry get its own styled 403 (`forbidden.html`) or keep the existing `login.html`-based 403?**
   - What we know: D-16 says "Forbidden sections return a styled in-shell 403 page" generally;
     `/admin/settings` today 403s via the existing `require_owner` → `_auth_html_or_json` →
     `login.html` path (a different visual/copy than the new shell chrome).
   - What's unclear: Whether "in-shell" strictly requires the NEW sidebar-wrapped 403 template even
     for the not-yet-migrated Settings page (which itself isn't shell-wrapped this phase per the
     phase boundary).
   - Recommendation: Extend the exception handler so ANY `require_manager`/tier-gated route
     (including `/admin/settings`, whose `require_owner` 403 is effectively "needs owner access")
     renders the new `forbidden.html`, replacing its current `login.html`-403 usage — this keeps
     the 403 experience consistent across all 7 sections without requiring Settings' happy-path
     rendering to be migrated yet.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Whole app/bot | ✓ | 3.12.8 (miniconda) `[VERIFIED]` | — |
| FastAPI | Dashboard routes | ✓ | 0.139.0 `[VERIFIED]` | — |
| discord.py | Bot heartbeat/cogs | ✓ | 2.5.2 `[VERIFIED]` | — |
| Authlib | OAuth | ✓ | 1.7.2 `[VERIFIED]` | — |
| Alpine.js (vendored) | Overview polling | ✓ | 3.15.12 (per `app/main.py` docstring; file present at `app/static/alpine.min.js`) `[VERIFIED]` | — |
| sqlite3 (stdlib) | All new tables | ✓ | bundled with Python 3.12 | — |
| pytest + TestClient | Validation | ✓ | pytest 9.1.1 `[VERIFIED]`, TestClient bundled with FastAPI | — |
| slopcheck (for future package additions) | Package legitimacy gate | ✓ | 0.6.1 `[VERIFIED: pip show]` | Not needed this phase (no new packages) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — everything required is already installed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1, no `pytest.ini`/`pyproject.toml` config found — bare `tests/conftest.py` only adds repo root to `sys.path` |
| Config file | none — see Wave 0 |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_app_auth.py -x` (use the conda Python per project memory — PowerShell's default Python has no pytest installed) |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SHELL-01 | Sidebar renders 7 sections with per-module accent, correct hrefs | integration (TestClient, render + string/DOM assertions on returned HTML) | `pytest tests/test_app_dashboard.py::test_sidebar_renders_seven_sections -x` | ❌ Wave 0 |
| SHELL-02 | Overview shows connection status / last sync / recent activity | integration (TestClient + seeded `bot_heartbeat`/`jinxxy_sync_status`/`activity_log` rows) | `pytest tests/test_app_dashboard.py::test_overview_shows_status_tiles -x` | ❌ Wave 0 |
| ACCESS-01 | Owner sees/uses every section incl. Settings | integration (dependency_overrides owner identity, 200 on all 7 routes) | `pytest tests/test_app_dashboard.py::test_owner_full_access -x` | ❌ Wave 0 |
| ACCESS-02 | Manager: 200 on 6 operational modules, 403 on Settings | integration (dependency_overrides manager identity) | `pytest tests/test_app_dashboard.py::test_manager_operational_access_settings_403 -x` | ❌ Wave 0 |
| ACCESS-03 | Editor-only: 403 on all 7 dashboard sections, 200 on `/editor` | integration (dependency_overrides editor-only identity) | `pytest tests/test_app_dashboard.py::test_editor_only_locked_out_of_dashboard -x` | ❌ Wave 0 |
| ACCESS-04 | Owner edits mapping; Manager POST to `/admin/settings` still 403; owner never locked out even with empty mapping | unit + integration (mirrors `tests/test_app_settings.py`'s existing owner/non-owner pattern) | `pytest tests/test_app_dashboard.py::test_manager_cannot_edit_mapping tests/test_settings.py -x` | ❌ Wave 0 (dashboard-specific cases); `tests/test_settings.py` exists for the generic settings-store behavior |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_app_dashboard.py tests/test_app_auth.py tests/test_settings.py -x` (conda python)
- **Per wave merge:** `python -m pytest` (full suite, conda python)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_app_dashboard.py` — new file covering SHELL-01/02, ACCESS-01/02/03/04
- [ ] `tests/test_settings.py` — extend with `manager_roles`/`editor_roles` schema cases (mirrors existing `GALLERY_STAFF_ROLE_IDS` tests already in this file)
- [ ] `tests/conftest.py` — no new shared fixture strictly required; the existing per-test
      `TestClient` + `app.dependency_overrides` pattern (seen in `tests/test_app_settings.py`)
      is sufficient and should be reused, not reinvented
- [ ] A fake/mock for `_fetch_member_roles` returning a configurable role-id set, for tests that
      exercise the OAuth callback's tier resolution directly (rather than via dependency_overrides)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | yes | Discord OAuth2 via Authlib (already implemented) — no change to the identify step this phase |
| V3 Session Management | yes | Starlette `SessionMiddleware` (itsdangerous signed cookie), `https_only`, `same_site=lax`, 6h TTL — unchanged; session continues to store ONLY `discord_id` (+ `slug` for editors), never a cached tier |
| V4 Access Control | yes | Server-side dependency gates (`require_owner`, new `require_manager`) re-checked on EVERY request against live Discord role data — never trust a client-rendered lock icon or cached session tier |
| V5 Input Validation | yes | `core/settings.py::_validate_role_id_list` (regex-equivalent digit-string parsing) already gates every role-ID list, including the two new keys |
| V6 Cryptography | yes (delegated) | Session signing handled entirely by Starlette/itsdangerous — never hand-rolled |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Manager self-elevation (editing `manager_roles`/`editor_roles` to add their own role) | Elevation of Privilege | `/admin/settings` POST stays gated by the existing `require_owner` dependency — a Manager's session can never satisfy it, regardless of request body content (no new code path is needed; this is inherited "for free" from the existing choke point) |
| Owner lockout via a bad mapping edit | Denial of Service (self-inflicted) | Owner tier resolution (D-04) never consults `manager_roles`/`editor_roles` — it is independent, hardcoded to `config.DISCORD_USER_ID`. An empty/corrupt mapping cannot affect owner access |
| Stale-session privilege retention (role removed but session still valid) | Tampering / Elevation of Privilege | D-02: every protected route re-reads live guild roles per request — no tier fact is ever cached in the session past its resolution moment |
| IDOR via client-supplied identity/tier in a request body | Tampering | Identity (`discord_id`) and every tier fact come from the session + a live server-side Discord REST read — never from request body/query, mirroring the existing `require_editor`/`require_owner` discipline (D-08) |
| Open redirect via post-login target | Tampering | Post-login redirect remains a FIXED, server-computed internal path chosen from the resolved tier — never a client-supplied `?next` (existing guard, extended not replaced) |
| Wrong-audience 403 copy leaking implementation detail | Information Disclosure (minor) | New `forbidden.html` renders only the bilingual "this section needs X access" copy — no stack trace, no role ID, no internal state (same discipline as existing `_FORBIDDEN_COPY`/`_OWNER_FORBIDDEN_COPY`) |

## Sources

### Primary (HIGH confidence — direct codebase inspection)
- `app/auth.py` — OAuth callback, `has_editor_role`, `_FORBIDDEN_COPY`
- `app/deps.py` — `require_editor`, `require_owner` (fail-closed owner gate, D-08 IDOR discipline)
- `app/main.py` — route registry, `_auth_html_or_json` exception handler, lifespan defensive table init, session middleware config
- `core/settings.py` — `_SCHEMA`, validators (`_validate_role_id_list`), `all_for_ui`, `seed_defaults`, `fallback_key` cascade (CONF-03)
- `core/db.py` — `init_presence`/`init_gallery_state`/`init_store_state` idioms, WAL pragma, single-row `CHECK (id = 1)` pattern
- `config.py` — `_SAFE_TUNABLE_KEYS` allowlist, `__getattr__` shim, `ROLE_MODERATOR_ID`/`DISCORD_USER_ID` sourcing
- `cogs/presence.py`, `cogs/jinxxy.py` (`_run_sync`, `@tasks.loop`, `cog_unload`), `bot.py` (intents, `setup_hook`, fail-fast startup)
- `app/templates/settings.html`, `app/templates/editor.html`, `app/templates/login.html`
- `.planning/sketches/001-dashboard-shell/index.html`, `.planning/sketches/001-dashboard-shell/README.md`, `.planning/sketches/themes/default.css`, `.planning/sketches/MANIFEST.md` — variant A accent colors, sidebar shape, "MEE6 puro" reference
- `tests/test_app_settings.py`, `tests/test_app_auth.py`, `tests/conftest.py` — existing `TestClient` + `dependency_overrides` test pattern
- `pip show fastapi discord.py authlib pytest slopcheck` (2026-07-21) — installed versions
- `python --version` (2026-07-21) — 3.12.8

### Secondary (MEDIUM confidence — WebSearch verified against official docs)
- FastAPI dependency caching (`use_cache=True` default, per-request scope) — `[CITED: fastapi.tiangolo.com/reference/dependencies]`

### Tertiary (LOW confidence)
- None — every non-codebase claim above was either cross-checked against FastAPI's own reference
  docs or explicitly logged in the Assumptions table.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library is already installed and version-confirmed via `pip show`; zero new dependencies
- Architecture: HIGH for patterns directly extending existing code (tier dependency, sqlite tables, Jinja inheritance); MEDIUM for the specific heartbeat cadence/threshold numbers (explicitly Claude's Discretion, logged as assumptions)
- Pitfalls: HIGH — all 6 pitfalls are grounded in direct inspection of the current route/template/schema code, not speculation

**Research date:** 2026-07-21
**Valid until:** 2026-08-20 (30 days — stable, in-repo stack; no fast-moving external dependency)
