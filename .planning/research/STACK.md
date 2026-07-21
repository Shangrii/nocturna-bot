# Stack Research

**Domain:** Staff admin dashboard (MEE6-style) on an existing FastAPI + discord.py bot, sharing sqlite
**Researched:** 2026-07-21
**Confidence:** HIGH (all recommendations verified against the existing codebase's own established patterns; no unverified new libraries proposed)

## Headline Recommendation

**Add zero new pip dependencies for this milestone.** Every capability the v2.0 dashboard needs
(Discord name resolution, triggering bot-side actions, the MEE6-style shell, table+modal CRUD) is
achievable by *extending patterns the codebase already uses* — `httpx` for Discord REST (already a
pin, already used for the bot-token role check in `app/auth.py`), the shared sqlite WAL file as the
only cross-process channel (already the `settings`/`presence` precedent), and vendored Alpine.js
(already shipped in `app/static/alpine.min.js`, already used in `editor.html`). This mirrors the
project's own documented discipline in `app/main.py` (rejecting `slowapi` in favor of proxy-level
rate limiting specifically to avoid "a fresh package install... would need its own legitimacy
checkpoint"). The same bar applies here.

## Recommended Stack

### Core Technologies (all already installed — no version change needed)

| Technology | Version (pinned in `requirements.txt`) | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `httpx` (async client) | 0.28.1 | Discord REST calls for channel/role name resolution + bot-triggered forum posts | Already the exact tool `app/auth.py::has_editor_role` uses for a bot-token REST call (`GET /guilds/{id}/members/{id}`). Extending it to `GET /guilds/{id}/channels` and `GET /guilds/{id}/roles` is zero new surface area, zero new dependency, and keeps one HTTP client in the whole admin app. |
| `sqlite3` (stdlib) + existing WAL pragma | stdlib | The ONLY cross-process channel between the bot and the admin app (unchanged from v1.0) | `core/db.py` already runs `PRAGMA journal_mode=WAL` on every connection specifically so the bot (reader/writer) and the panel (writer) don't collide. v2.0 adds tables to this same file (`bot_commands`/`meetings`) rather than introducing IPC, a socket, or a message broker. |
| `discord.ext.tasks` (via discord.py, bot side only) | 2.7.1 (existing pin) | Short-interval poll loop that turns a sqlite row into a real Discord action | Already the idiom for every periodic job in this codebase (`cogs/jinxxy.py::_poll`, `cogs/reminders.py::_scheduler` at `minutes=1`). A new `@tasks.loop(seconds=10)` "command poller" cog is the smallest possible addition, using a mechanism the bot process already trusts. |
| Jinja2 (via FastAPI's `Jinja2Templates`) | 3.1.6 (existing pin) | Server-rendered dashboard shell + all 7 module pages | Already the app's only templating layer (`editor.html`, `settings.html`). The sidebar shell (sketch 001 variant A) is a `base.html` layout with a `{% block %}` per module — no new templating tech. |
| Alpine.js (vendored, not CDN) | 3.15.12 (already in `app/static/alpine.min.js`) | Client-side reactivity for toggles, tabs, and the table+modal CRUD pattern | Already vendored and already used in `editor.html` for `x-data`. It is the *only* client-side framework this project has ever adopted — reusing it for reminders/gallery/reviews modals is consistent, not a new decision. |

### Supporting Techniques (not libraries — codified patterns to extend)

| Pattern | Purpose | When to Use |
|---------|---------|-------------|
| In-process TTL dict cache (10-15 lines of stdlib, no library) | Cache resolved `#channel`/`@role` names between requests | Every settings-page render and every dashboard page that shows a channel/role name (POLISH-01). Guild channel/role lists change rarely; a 5-10 min TTL keyed by guild ID is enough to keep this well under Discord's per-route rate limit even under heavy staff traffic. |
| `bot_commands` sqlite table + short-poll `tasks.loop` cog (mirrors the existing `presence` table, reversed direction) | Trigger bot-side actions (manual Jinxxy sync, meeting re-publish) from the FastAPI process | Any action that must run INSIDE the bot process — either because it needs the bot's live Discord context (forum thread edit, channel post) or because it must never run concurrently with the bot's own scheduled job for the same resource (Jinxxy's 6-12h `_poll` and a manual "sync now" must never race). |
| New sqlite tables via `CREATE TABLE IF NOT EXISTS` in `core/db.py` (same idiom as `forum_posts`/`reminders`/`store_snapshot`) | Persist meeting transcripts/summaries for browse+edit+republish; persist role→tier assignment | No new storage technology — meetings currently generate transcript+summary in-memory and post directly to Discord with **no persistence** (`cogs/meeting.py::_publish`); v2.0 needs a durable copy to browse/edit, which is a new table, not a new database. |
| `Depends(require_tier(...))` — a thin generalization of the existing `require_editor`/`require_owner` dependency chain | Tiered access (owner > Manager role > editor) | `app/deps.py` is already the single documented auth choke point; add one more tier check function following the exact same shape (session identity in, live role re-check, fail closed on unset config) rather than a new authz library. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest` (existing pin, 8.0.0+) | Unit tests for the new command-queue poller, tier resolution, and Discord-name-cache TTL logic | Run via `C:\Users\Shangri\miniconda3\python.exe -m pytest` per this machine's test-run note — the same discipline as every other phase in this repo (mock `httpx`/`requests`, never hit the live Discord API in tests, mirroring `has_editor_role`'s existing test doubles). |
| `respx` or plain `unittest.mock` for `httpx` mocking | Test the new channel/role-resolution REST calls without live Discord calls | The codebase currently mocks `httpx`/`requests` calls with plain `unittest.mock` (no `respx` dependency exists yet); stay consistent — do not add `respx` for this alone unless the mocking becomes unwieldy. |

## Installation

```bash
# No new packages required for this milestone.
# Every capability is built from what's already in requirements.txt:
#   fastapi==0.139.0, uvicorn[standard]==0.51.0, authlib==1.7.2,
#   python-multipart==0.0.32, jinja2==3.1.6, httpx==0.28.1,
#   discord.py[voice]==2.7.1, requests>=2.31.0
#
# If a channel/role cache ever needs to survive process restarts (it does not — a cold
# cache just refetches on first use), do NOT add a cache library; a one-row sqlite table
# following the `presence` idiom is enough.
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| Raw `httpx.AsyncClient` + Bot-token header for channel/role resolution | `discord.py`'s own REST layer (`discord.http.HTTPClient`) or a dedicated third-party wrapper (e.g. `pycord`, `hikari`'s REST-only client) | Only if the admin app grows into needing a wide swath of the Discord REST surface (dozens of endpoints, retries, typed models). For 2 read-only list endpoints (`/guilds/{id}/channels`, `/guilds/{id}/roles`), pulling in a second Discord client library (or instantiating `discord.py`'s internal, semi-private `HTTPClient` outside a `Client`/gateway context) is strictly more code and more surface than 2 `httpx.get()` calls the app already knows how to make. |
| In-process TTL dict cache (stdlib) | `cachetools` (`TTLCache`), `functools.lru_cache` with manual invalidation, or Redis | `cachetools` (latest 7.1.4) is a fine, tiny library — reasonable if the team later wants a documented cache API instead of a hand-rolled dict. Redis is the wrong scale entirely: single guild, single host, a cache that only needs to survive a few minutes and can always be recomputed from a cheap REST call. |
| sqlite `bot_commands` table + `tasks.loop` short-poll cog | A message broker (Redis pub/sub, RabbitMQ, Celery) | Only if the bot and admin app move to genuinely separate hosts, or the action volume grows to many jobs/second. At "a handful of manual syncs and re-publishes per day," a broker is a new service to provision, secure, and keep alive on the same "cinema" host for a problem sqlite already solves — and it would contradict the locked v1.0 decision ("no IPC/socket/signal is built — sqlite is the channel"). |
| sqlite `bot_commands` table (bot polls and executes) | Direct execution of `core.jinxxy_api`/`core.store_sync`/`core.github_publish` logic **inside the FastAPI process** (these modules are discord-free and technically importable there) | Tempting because it's fewer moving parts, but it reintroduces a real race: the bot's own `@tasks.loop(hours=JINXXY_POLL_HOURS)` and a FastAPI-triggered run would be two OS processes calling the same non-idempotent sync-and-commit logic concurrently, with no shared lock. Routing every trigger through the bot's single event loop (whether via Discord slash command or the new command-queue poll) preserves the existing single-writer guarantee for free. |
| Alpine.js (already vendored) for the table+modal CRUD pattern | `htmx` | `htmx` is a legitimate, similarly small stdlib-friendly choice for exactly this pattern (server returns HTML fragments, swap into the DOM) — but it would be a **second** client-side library alongside Alpine for the same job (interactivity without a build step). Since Alpine is already vendored, already used in `editor.html`, and already proven for this team's exact use case (`x-data`/`x-show` modals), adding `htmx` duplicates capability without displacing anything. |
| Alpine.js + `fetch()` JSON round-trips (matches `/editor/save`, `/admin/settings` POST shape) | A full SPA framework (React/Vue/Svelte) with a build pipeline | Only justified if the dashboard needed client-side routing, complex shared state across modules, or a component ecosystem — none of which sketch 001 (server-rendered pages per module, sidebar navigation via normal links) calls for. A build step (webpack/vite/npm toolchain) would be a first for this Python-stdlib-lean project and buys nothing sketch 001 needs. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| Discord Gateway connection (a second `discord.Client`) inside the FastAPI process | Heavyweight (persistent WebSocket, sharding concerns, presence/intents config) just to read a channel/role list or post one message; also duplicates the bot's own gateway identity, risking Discord flagging two sessions under one token in edge cases | REST-only calls with the existing Bot token via `httpx` (stateless, request-scoped, matches `has_editor_role`) for reads; the sqlite command-queue pattern for anything that must originate the actual Discord write from the bot's existing single gateway session |
| A message broker / task queue library (Celery, RQ, Dramatiq, Redis Streams) | New infrastructure service on the same "cinema" host, new failure mode to monitor, directly contradicts the locked v1.0 decision that sqlite is the ONLY inter-process channel | The `bot_commands` sqlite table + short `tasks.loop` poll — same durability (a pending row survives a bot restart) at zero new ops burden |
| `slowapi` or any new rate-limiting library for the Discord REST calls this milestone adds | The codebase already explicitly rejected adding a rate-limiting pip dependency mid-project (`app/main.py`'s documented Caddy-level choice); the new calls here are 2 cacheable, low-frequency GETs — nowhere near needing a rate-limiter | Respect `X-RateLimit-Remaining`/`Retry-After` on the (rare) 429 with a simple bounded backoff, mirroring the pattern already proven in `core/jinxxy_api.py`'s 429 handling |
| A second HTTP client library (`aiohttp` client session, `requests` for the new async paths) | `httpx.AsyncClient` is already the app's async HTTP client (`app/auth.py`); `aiohttp` is already a dependency but only for discord.py's own transport, and `requests` is sync-only (wrong for FastAPI's async handlers) | `httpx.AsyncClient`, exactly as `has_editor_role` already does |
| Client-side framework + build tooling (webpack/vite/npm) for the dashboard shell | No part of this project currently has a JS build step; introducing one is a standing maintenance cost (lockfiles, Node version on "cinema", CI changes) for a UI sketch 001 shows is achievable with server-rendered pages + Alpine | Jinja2 layout inheritance (`base.html` + per-module `{% block %}`) + vendored Alpine.js, exactly as `editor.html` already does |

## Stack Patterns by Variant

**Discord name resolution (channel/role, POLISH-01):**
- Use two cached `httpx.AsyncClient` GET calls per guild: `/guilds/{GUILD_ID}/channels` (all channels in one call) and `/guilds/{GUILD_ID}/roles` (all roles in one call) — NOT a call per individual ID.
- Because these are the only two guild-scoped lookups needed and the guild never changes, cache the two lists (id → name maps) in a module-level dict with a timestamp, refetch when older than ~5-10 minutes.
- Render as `#{name}` / `@{name}` with the raw snowflake shown beneath (sketch 001 confirms this exact shape) — fall back to the bare ID if the cache miss can't be resolved (deleted channel/role, API hiccup): never block the page render on a Discord outage.

**Triggering a bot-side action from the panel (Jinxxy sync-now, meeting re-publish):**
- Panel writes one row to a new `bot_commands` table: `(id, kind, payload_json, requested_by, requested_at, status, result, completed_at)`.
- A new bot-side cog runs `@tasks.loop(seconds=10)` (or similar short interval — NOT the 6-12h Jinxxy cadence), polls `WHERE status = 'pending'`, dispatches by `kind` to the SAME core function the existing slash command already calls (`JinxxyCog._run_sync` for "sync now"; the meeting cog's forum-publish path for "re-publish"), then writes `status='done'|'error'` + `result` back.
- The panel polls the same row (or a `GET /admin/jinxxy/status` endpoint backed by it) with a short client-side `setInterval`/Alpine `x-init` poll to show "Syncing…" → "Last sync: just now" — no WebSocket needed at this volume.
- This is the exact same shared-sqlite discipline as the existing `presence` table, just with the write/read roles swapped (panel writes the request, bot writes the result).

**MEE6-style shell + table/modal CRUD (reminders, gallery queue, reviews queue):**
- One `base.html` with the sketch-001-variant-A sidebar (per-module color accent, icon, optional pending-count badge) and a `{% block content %}` each module page fills.
- Tables (reminders, meeting list, product list) are plain server-rendered `<table>` rows from Jinja loops — no client-side table library needed at this row count (tens, not thousands).
- Modals (create/edit reminder, edit meeting summary) use Alpine `x-data="{ open: false, item: null }"` + `x-show="open"` + a `fetch()` GET to hydrate the form when opening an existing row and a `fetch()` POST to save — identical shape to the already-proven `/editor/save` and `/admin/settings` JSON round-trip.
- Approval queues (gallery, reviews) render pending items as cards/rows with Approve/Remove buttons; each button does a `fetch()` POST to a per-item endpoint and then either removes the DOM node (Alpine local list state) or does a full-page reload — favor the reload for the first pass (simpler, fewer client-side edge cases), following the project's low-JS-complexity default until proven insufficient.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `httpx==0.28.1` | `fastapi==0.139.0`, `authlib==1.7.2` | Already co-installed and exercised together in `app/auth.py`/`app/main.py`; no change needed for the new channel/role calls. |
| `discord.py[voice]==2.7.1` | `discord.ext.tasks` (bundled) | The new command-poller cog uses the exact same `@tasks.loop` API already used at `hours=` (Jinxxy) and `minutes=1` (reminders) cadences — just a shorter `seconds=` interval; no version bump required. |
| `jinja2==3.1.6` | `fastapi==0.139.0`'s `Jinja2Templates` | Already the templating engine for `editor.html`/`settings.html`/`login.html`; `base.html` layout inheritance for the 7-module shell needs nothing beyond what 3.1.6 already supports. |
| Alpine.js 3.15.12 (vendored) | No build step, loaded via `<script defer src="/static/alpine.min.js">` | Confirmed already deployed this way in `editor.html` ("editorApp defined BEFORE Alpine parses x-data" — keep that same ordering discipline for any new `x-data` object the dashboard defines). |
| sqlite WAL (`PRAGMA journal_mode=WAL`, `core/db.py::_get_conn`) | Both the bot process and the FastAPI process, on the same host ("cinema") | WAL requires a LOCAL filesystem (already documented in `core/db.py`) — this remains true for the new `bot_commands`/`meetings` tables; no change to the connection idiom (fresh connection per call, `CREATE TABLE IF NOT EXISTS` from each consumer's init). |

## Sources

- `app/auth.py`, `app/deps.py`, `app/main.py`, `core/db.py`, `core/settings.py`, `core/jinxxy_api.py`, `core/store_sync.py`, `core/github_publish.py`, `cogs/jinxxy.py`, `cogs/meeting.py`, `cogs/gallery.py`, `cogs/reminders.py`, `requirements.txt` — read directly from this repository (HIGH confidence: these are the actual shipped patterns, not inferred).
- `.planning/PROJECT.md` — v2.0 scope, constraints, and the "pending" v2.0 key decision on Discord-API credential scope this research resolves.
- `.planning/sketches/001-dashboard-shell/index.html` / `README.md` — visual contract (variant A), confirmed the sketch itself is a throwaway vanilla-JS mock (no framework signal to follow), so the production frontend choice is drawn from `editor.html`'s real, already-shipped Alpine.js usage instead.
- Discord Developer Docs — [Rate Limits](https://docs.discord.com/developers/topics/rate-limits) — verified current rate-limit header names (`X-RateLimit-Limit/Remaining/Reset/Reset-After/Bucket`) and the guidance to read headers rather than hardcode limits (MEDIUM confidence via WebSearch, cross-checked against the header names already handled in `core/jinxxy_api.py`'s existing 429 logic — consistent).
- `pip index versions httpx` / `cachetools` (run locally) — confirmed `httpx==0.28.1` is current-latest (matches the existing pin, no bump needed) and `cachetools` latest is `7.1.4` (HIGH confidence, direct PyPI index query; recommended against adding it regardless, per the "what not to use" rationale above).

---
*Stack research for: Staff dashboard additions on an existing FastAPI + discord.py + sqlite bot admin app*
*Researched: 2026-07-21*
