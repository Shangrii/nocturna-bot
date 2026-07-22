# Phase 4: Settings Migration + Name Resolution - Research

**Researched:** 2026-07-22
**Domain:** FastAPI/Jinja/Alpine settings-panel migration + a bot→app Discord name cache over shared sqlite
**Confidence:** HIGH (grounded in the real codebase; the one external fact — discord.py cache/intent model — is verified)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**Settings page composition (SETT-01 migration)**
- **D-01: One scrolling Settings page, feature groups.** The v1 tunables and the Phase-3 role→tier mapping live on a single Settings-section page. The mapping (`manager_roles` / `editor_roles`) becomes one more fieldset **"Access" group** alongside the existing feature groups. One Save action for the whole page.
- **D-02: Retire the standalone `/admin/settings` route.** The in-shell Settings section route becomes the *only* Settings URL. Remove the Phase-2 standalone page route rather than redirecting or keeping both. The existing 403-exception-handler special-case keyed on `request.url.path == "/admin/settings"` (app/main.py ~line 362) must be updated to the new section path so the styled in-shell 403 still fires.
- **D-03: No loss of functionality (SETT-01, non-negotiable).** The migrated form keeps the exact Phase-2 contract: two-pass atomic validate-then-write (`settings.validate_only` all keys → 422 with error map if any invalid → only then `settings.set`), per-field inline errors, `require_owner` fail-closed gate, no secret ever rendered.

**Name display treatment (SETT-02)**
- **D-04: Rich single-field display.** A resolved `snowflake` field shows the name (`#gallery`, `@Staff`) prominently, a type/color cue (channel-type icon for text/forum/voice; the role's Discord color as a swatch/tint), and the raw ID in small muted text beneath.
- **D-05: Role lists = one colored chip per role.** `role_list` fields render each ID as its own readable `@role` chip tinted with the role color, ID available beneath/on the chip. The edit control stays the same comma-separated raw-ID input; chips are the read-side rendering.

**Unresolved / stale ID handling (SETT-02 robustness)**
- **D-06: Per-field fallback, never blocks save.** When an entered ID has no cache entry, the field falls back to the raw ID with a muted bilingual "name unavailable · no encontrado" marker. Resolution failure never prevents saving a valid ID.
- **D-07: Distinguish "cache not ready" from "genuinely gone."** Use a cache freshness signal. When the cache is empty/stale, show a section-level "names loading — bot syncing" hint instead of flagging every field as broken.

**Bot-pushed name cache**
- **D-08: Cache carries id → name + kind + type/color + freshness, pushed via the established `@tasks.loop`→sqlite pattern.** The shared sqlite is the only bot↔app channel. Each row resolves a snowflake to: display name, kind (`channel` vs `role`), channel-type (text/forum/voice) or role color. A freshness marker drives D-07's decision.

**Resolution timing (edit-form UX)**
- **D-09: Live client-side lookup.** Ship the id→{name, kind, color} cache into the Settings page as Alpine data so the readable name updates the instant the owner types/pastes a valid ID — before saving. Server-side render still resolves the initial paint from the same cache.

### Claude's Discretion
- Exact `name_cache` (or similar) table schema and column names.
- Bot-side push cadence and triggers (startup snapshot, periodic refresh loop, and/or guild create-update-delete events) — must land through the shared-sqlite pattern only.
- Whether the cache reuses the existing heartbeat freshness row or adds its own push-timestamp.
- Exact chip / swatch / icon styling within the variant-A dark-SaaS visual language.
- Precise placement of the "Access" group among the feature groups on the page.

### Deferred Ideas (OUT OF SCOPE)
- **Guild-populated channel/role dropdown pickers (FUT-01)** — full picker UI that replaces raw-ID entry. This phase ships readable names on the existing ID inputs only.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SETT-01 | Migrate the v1 settings panel into the shell with no loss of functionality | Migration is a template re-parent + route consolidation. The load-bearing store (`core/settings.py`) and the two-pass POST handler (`app/main.py::save_settings`) are UNCHANGED — see "Architecture Patterns" and "Runtime State Inventory". No data migration; the `settings` sqlite table already exists and is untouched. |
| SETT-02 | Channel/role fields show readable `#channel`/`@role` + ID beneath, resolved via a bot-pushed shared-sqlite cache | Resolved by the new `discord_names` table + a `cogs/heartbeat.py`-shaped push loop + an `app/main.py` read at render. The **credential boundary research gap is closed**: the data is already in the bot's non-privileged GUILDS-intent gateway cache — zero REST, zero new scope, zero bot credentials in the app. See "Common Pitfalls → Pitfall 1 (Credential boundary)". |
</phase_requirements>

## Summary

This phase is **90% a migration and 10% a new cache**, and every piece rides on a pattern already shipped in this codebase. SETT-01 is almost entirely a *presentation* change: `app/templates/settings.html` is rewritten to `{% extends "_dashboard_base.html" %}` (dropping its bespoke topbar), the field templates keep their exact type behaviors, and the server-side store (`core/settings.py`) and the atomic two-pass POST (`app/main.py::save_settings`) are **not touched**. There is no data migration — the `settings` table already holds every tunable including the Phase-3 `manager_roles`/`editor_roles` mapping (already in `_SCHEMA` under group `access`).

SETT-02's new machinery is a **carbon copy of the Phase-3 `bot_heartbeat` pattern**: a new single-purpose sqlite table (`discord_names`), a `db.init_*`/`db.upsert_*`/`db.get_*` helper trio in `core/db.py`, a bot-side `@tasks.loop` cog (structurally identical to `cogs/heartbeat.py`) that snapshots the guild's channels+roles into that table, and an app-side read at render (identical to `db.get_heartbeat`). The FastAPI app never imports discord.py and never makes a Discord call.

**The STATE.md Phase-4 credential-boundary research gap is definitively resolved.** discord.py's non-privileged **GUILDS intent** (part of `Intents.default()`, already active in `bot.py`) populates `Guild.channels` and `Guild.roles` in the bot's in-memory gateway cache. Reading `self.bot.get_guild(config.GUILD_ID).channels` / `.roles` costs **zero REST calls and needs zero additional scope, token, or privileged intent**. The bot is the only writer of `discord_names`; the app is the only reader. This is byte-identical, credential-wise, to the already-shipped `PresenceCog`/`HeartbeatCog` model — no new trust surface is introduced.

**Primary recommendation:** Mirror the `bot_heartbeat` triad exactly. New table `discord_names(id TEXT PK, kind, name, subtype, color, synced_at)`; new cog `cogs/discord_names.py` (an `@tasks.loop` doing a full-snapshot replace of the guild's channels+roles); read it in the settings route, resolve server-side, and ship the small `{id: {...}}` map to Alpine for D-09 live lookup. Do **not** rename the `/admin/settings` route unless the planner deliberately opts into route-family consistency (see Open Questions).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reading live channel/role names+colors from Discord | Bot process (discord.py gateway cache) | — | Only the bot holds a gateway connection + the GUILDS intent cache. The app has no Discord credentials by locked project decision. |
| Persisting the name cache | Database (shared sqlite `discord_names`) | Bot (writer) | Shared sqlite is the ONLY cross-process channel (locked). Bot writes, app reads. |
| Resolving IDs → names at page render (SSR first paint) | API/Backend (FastAPI settings route) | Database | The route reads `discord_names` read-only and injects the resolution map. |
| Live id→name lookup while typing (D-09) | Browser/Client (Alpine) | — | The whole (small, single-guild) cache is shipped to the browser so a paste resolves instantly before save. |
| Settings validate-then-write (SETT-01) | API/Backend (`save_settings` + `core/settings.py`) | Database | UNCHANGED from Phase 2 — server-side allowlist validation is the security boundary. |
| Owner-only gate | API/Backend (`require_owner`) | — | Fail-closed session-identity check, unchanged. |
| Cache freshness / cold-start banner (D-07) | API/Backend (compute) + Browser (react) | Database | App computes `names_fresh` from `MAX(synced_at)`; Alpine re-renders the banner reactively. |

## Standard Stack

**No new packages.** Every dependency this phase needs is already installed and pinned. The phase adds *code*, not dependencies.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | 2.7.1 | Bot-side guild channel/role read from the gateway cache (`Guild.channels`, `Guild.roles`, `Role.colour`, `ChannelType`) | Already the bot framework; the GUILDS intent cache is exactly the read-only, no-REST source this phase needs `[VERIFIED: requirements.txt pin + discordpy.readthedocs.io]` |
| fastapi | 0.139.0 | Settings route (GET render + existing POST) | Already the app framework `[VERIFIED: requirements.txt]` |
| jinja2 | 3.1.6 | `settings.html` server-render + `_dashboard_base.html` inheritance | Already in use `[VERIFIED: requirements.txt]` |
| sqlite3 (stdlib) | — | `discord_names` table via `core/db.py` helpers | Shared sqlite is the locked cross-process channel `[VERIFIED: core/db.py]` |
| Alpine.js | 3.15.12 (vendored, `app/static/alpine.min.js`) | D-09 live client-side lookup; existing form reactivity | Already vendored, no build step `[VERIFIED: app/static/, app/templates/settings.html]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| discord.ext.tasks | (ships with discord.py) | The `@tasks.loop` cadence for the cache push | The push cog — mirror `cogs/heartbeat.py` `[VERIFIED: cogs/heartbeat.py]` |
| starlette.concurrency.run_in_threadpool | (ships with FastAPI) | Read `discord_names` off the event loop in the async route | Already the idiom for every `core.db` read in `app/main.py` `[VERIFIED: app/main.py]` |
| pytest | >=8.0.0 (env: conda python) | Wave-0 + regression tests | Existing suite `[VERIFIED: requirements.txt, tests/]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| A dedicated `discord_names` table | Fold names into an existing table | Violates the codebase's explicit "one-table-per-concern" idiom (see `init_jinxxy_sync_status` docstring); rejected. |
| `@tasks.loop` periodic snapshot | Pure event-listener push (`on_guild_channel_update`, etc.) | Events give lower latency but miss the cold-start snapshot and can drop during downtime. Recommend loop as the baseline; events optional (D-08 discretion). |
| Storing `id` as INTEGER | Storing `id` as TEXT | TEXT avoids any JS `2^53` precision risk when the map is serialized to the browser, and matches how `all_for_ui()` already stringifies snowflakes. Recommend TEXT. |

**Installation:** none — no `pip install` this phase. (If a plan proposes one, it is out of scope and needs its own checkpoint.)

## Package Legitimacy Audit

**No external packages are installed in this phase.** Every library used is already present and pinned in `requirements.txt` (discord.py 2.7.1, fastapi 0.139.0, jinja2 3.1.6) or is the Python stdlib (sqlite3, datetime, json). slopcheck / registry verification is **not applicable** — there is nothing to install.

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none — no new installs) | — | N/A |

## Architecture Patterns

### System Architecture Diagram

```
   DISCORD GATEWAY (bot process only, GUILDS intent — non-privileged, already active)
            │  channels + roles pushed to in-memory cache on connect + on change
            ▼
   ┌─────────────────────────────┐
   │  cogs/discord_names.py       │   @tasks.loop(minutes=~5) + before_loop wait_until_ready
   │  (NEW — mirror heartbeat.py) │   guild = bot.get_guild(GUILD_ID)
   │                              │   snapshot = guild.channels + guild.roles  (NO REST)
   └──────────────┬──────────────┘
                  │ asyncio.to_thread(db.replace_discord_names, rows)
                  ▼
   ┌─────────────────────────────────────────────────────────┐
   │  SHARED SQLITE  (bot.db, WAL)  — the ONLY bot↔app channel │
   │  TABLE discord_names(id TEXT PK, kind, name, subtype,     │
   │                      color, synced_at)                    │
   └──────────────┬──────────────────────────────────────────┘
                  │ db.get_discord_names()  (read-only, run_in_threadpool)
                  ▼
   ┌─────────────────────────────┐        ┌──────────────────────────────┐
   │  FastAPI: settings route     │        │  app NEVER imports discord.   │
   │  GET /admin/settings         │        │  No token, no REST, no scope. │
   │  - require_owner (unchanged) │        └──────────────────────────────┘
   │  - settings.all_for_ui()     │
   │  - db.get_discord_names()    │──┐ builds {id: {name,kind,subtype,color}} map
   │  - names_fresh = MAX(synced) │  │ + names_fresh bool (D-07)
   └──────────────┬──────────────┘  │
                  ▼                  ▼
   ┌───────────────────────────────────────────────┐
   │  settings.html (extends _dashboard_base.html)  │
   │  - SSR first paint resolves each field          │
   │  - ships names map into Alpine x-data (D-09)    │
   │  - live lookup on every keystroke               │
   │  - cache-cold banner when !names_fresh (D-07)   │
   └───────────────────────────────────────────────┘
                  │ POST /admin/settings (UNCHANGED two-pass validate-then-write)
                  ▼
   core/settings.py  validate_only() → set()   (allowlist, no secrets, atomic)
```

### Recommended File Touch-Map

```
core/db.py                     # ADD: init_discord_names(), replace_discord_names(rows),
                               #      get_discord_names()  (mirror the bot_heartbeat trio)
cogs/discord_names.py          # NEW: @tasks.loop snapshot cog (mirror cogs/heartbeat.py)
bot.py                         # ADD one line: await self.load_extension("cogs.discord_names")
app/main.py                    # EDIT settings_page(): read + inject names map + names_fresh.
                               #   save_settings() and require_owner: UNCHANGED (D-03).
                               #   403 handler special-case (~line 362): touch ONLY if route renamed.
app/templates/settings.html    # REWRITE: extend _dashboard_base.html; extend snowflake/role_list
                               #   templates with resolved-name preview, chips, fallback markers,
                               #   cache-cold banner. Other field types unchanged (re-skinned).
app/static/dashboard.css       # ADD a `settings` block (fields/groups/chips/banner) on Phase-3 tokens
tests/test_discord_names.py    # NEW (Wave 0): db helper contract
tests/test_app_settings.py     # EXTEND: in-shell render, name resolution, cold-cache banner,
                               #   no-loss-of-functionality regression (POST flow unchanged)
```

### Pattern 1: The `bot_heartbeat` triad — copy it exactly for `discord_names`
**What:** A single-purpose table + `init_*`/writer/reader helpers in `core/db.py`, written only by a bot cog and read only by the app, both calling `init_*` defensively (dual-process init).
**When to use:** This is THE established shared-sqlite bot→app pattern in this repo (`bot_heartbeat`, `jinxxy_sync_status`, `presence`). D-08 explicitly names it.
**Example:**
```python
# core/db.py — mirror init_heartbeat / set_heartbeat / get_heartbeat
def init_discord_names():
    """Create the discord_names cache table if absent (dual-process defensive init)."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discord_names (
                id        TEXT PRIMARY KEY,   -- snowflake as TEXT (JS 2**53-safe in transit)
                kind      TEXT NOT NULL,      -- 'channel' | 'role'
                name      TEXT NOT NULL,      -- raw Discord name, WITHOUT #/@ (template adds prefix)
                subtype   TEXT,              -- channel: 'text'|'forum'|'voice'|...  role: NULL
                color     TEXT,              -- role: '#rrggbb' (NULL if no color)   channel: NULL
                synced_at TEXT NOT NULL       -- ISO 8601 UTC; freshness = MAX(synced_at)
            )
        """)

def replace_discord_names(rows: list[tuple]):
    """Full-snapshot replace in ONE transaction — inherently handles deleted channels/roles."""
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:                # `with conn:` = one atomic transaction
        conn.execute("DELETE FROM discord_names")
        conn.executemany(
            "INSERT INTO discord_names (id, kind, name, subtype, color, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(str(i), k, n, st, c, now) for (i, k, n, st, c) in rows],
        )

def get_discord_names() -> list[sqlite3.Row]:
    with _get_conn() as conn:
        return conn.execute(
            "SELECT id, kind, name, subtype, color, synced_at FROM discord_names"
        ).fetchall()
```
`[VERIFIED: core/db.py — this is the exact shape of init_heartbeat/set_heartbeat/get_heartbeat]`

### Pattern 2: The push cog — mirror `cogs/heartbeat.py`
**What:** A minimal always-loaded cog whose `@tasks.loop` snapshots guild state off the event loop into sqlite, with `wait_until_ready` before-loop and `cog_unload` cancel.
**Example:**
```python
# cogs/discord_names.py  (structure mirrors cogs/heartbeat.py 1:1)
_CHANNEL_KINDS = {                                    # discord.ChannelType -> our subtype string
    discord.ChannelType.text: "text",
    discord.ChannelType.forum: "forum",
    discord.ChannelType.voice: "voice",
    discord.ChannelType.news: "text",
    discord.ChannelType.stage_voice: "voice",
}

class DiscordNamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        db.init_discord_names()                       # dual-process defensive init (Pitfall 6)
        self._push.start()

    async def cog_unload(self):
        self._push.cancel()                            # hot-reload safety

    @tasks.loop(minutes=5)                             # cadence = Claude's Discretion (D-08)
    async def _push(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:                              # cold-start race — skip, try next tick
            return
        rows = []
        for ch in guild.channels:                      # gateway cache, NO REST, GUILDS intent
            rows.append((ch.id, "channel", ch.name,
                         _CHANNEL_KINDS.get(ch.type, "other"), None))
        for role in guild.roles:
            if role.is_default():                      # skip @everyone (never a settings target)
                continue
            colour = role.colour                        # discord.Colour; .value == 0 => no colour
            hex_ = f"#{colour.value:06x}" if colour.value else None
            rows.append((role.id, "role", role.name, None, hex_))
        try:
            await asyncio.to_thread(db.replace_discord_names, rows)
        except Exception:
            log.exception("discord_names: no pude escribir la caché de nombres")

    @_push.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(DiscordNamesCog(bot))
```
`[VERIFIED: cogs/heartbeat.py structure]` `[CITED: discordpy.readthedocs.io — Guild.channels/roles, Role.colour, ChannelType]`

### Pattern 3: App-side resolution + freshness (mirror `_compute_online`)
**What:** In `settings_page`, read the cache, build a JSON-serializable map keyed by **string** id, and compute a `names_fresh` bool from `MAX(synced_at)` against a staleness window.
**Example:**
```python
_NAMES_STALE_SECONDS = 15 * 60   # ~3x a 5-min push loop; empty table => cold

async def _read_name_cache() -> tuple[dict, bool]:
    rows = await run_in_threadpool(db.get_discord_names)
    names = {r["id"]: {"name": r["name"], "kind": r["kind"],
                       "subtype": r["subtype"], "color": r["color"]} for r in rows}
    fresh = False
    if rows:
        newest = max(r["synced_at"] for r in rows)
        try:
            ts = datetime.fromisoformat(newest)
            if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
            fresh = (datetime.now(timezone.utc) - ts).total_seconds() <= _NAMES_STALE_SECONDS
        except (TypeError, ValueError):
            fresh = False
    return names, fresh
```
Then pass `names` (as `| tojson` into Alpine x-data) and `names_fresh` into the template. Map keys are strings, so JSON object keys are inherently precision-safe. `[VERIFIED: app/main.py::_compute_online idiom]`

### Anti-Patterns to Avoid
- **Adding discord.py or a bot token to the FastAPI app.** Forbidden by locked project decision. The app resolves names ONLY from sqlite. (This is the whole point of the research gap.)
- **A cold Discord REST call (`fetch_channel`/`fetch_guild`) from the app at render.** Named explicitly as the wrong approach in the phase brief. Never do it.
- **Serializing snowflake IDs as JS numbers.** Jinja `| tojson` on a Python `int` emits a bare number the browser rounds above `2^53`, corrupting 17-20-digit snowflakes. Keys must be strings (see `all_for_ui()`'s CR-01 note). Store `id` as TEXT and key the map by string.
- **Touching `core/settings.py` or `save_settings`'s two-pass logic.** D-03 is non-negotiable; the store and POST flow carry over unchanged. Migration is presentation + a read-side cache only.
- **Flagging every field "unavailable" on a cold cache.** D-07: an empty/stale cache shows ONE section-level banner, not per-field broken markers.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-process bot→app messaging | A socket/HTTP/IPC bridge | The shared sqlite `discord_names` table | Locked project decision; WAL already handles concurrent read/write |
| Reading channel/role names | A REST poller / Discord API client in the app | `Guild.channels` / `Guild.roles` from the bot's gateway cache | Already cached in-memory by the non-privileged GUILDS intent — free, no rate limit, no credential in the app |
| Settings validation | New per-field JS/HTML validators | The existing `core/settings.py` `_SCHEMA` + `validate_only`/`set` | Already the load-bearing allowlist; re-validating client-side would drift from the server contract |
| Atomic multi-field save | Custom transaction/rollback logic | The existing two-pass `save_settings` (validate-all → 422-or-write-all) | Already implements the atomicity guarantee (D-04) |
| Session/CSRF | A CSRF token | Existing SameSite=Lax signed session cookie | Already the app-wide mechanism (see `save_settings` docstring) |
| Role color hex | Manual int→hex string juggling everywhere | `discord.Colour.value` → `f"#{value:06x}"` once in the cog | Single conversion point; template just consumes the hex string |

**Key insight:** This phase should introduce almost no novel infrastructure. Nearly every requirement maps onto an already-proven helper (`bot_heartbeat`, `all_for_ui`, `save_settings`, `_compute_online`). The research risk is *over-building* (a REST resolver, a second IPC channel), not under-building.

## Runtime State Inventory

> This is a migration phase. A grep audit finds files, not runtime state — this table answers what persists beyond a code change.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | The `settings` sqlite table already holds ALL tunables, including the Phase-3 `manager_roles`/`editor_roles` mapping (already in `_SCHEMA`, group `access`). SETT-01 migration adds **no** new settings keys and requires **no** data migration — the same table + `get`/`set` contract carries over. The NEW `discord_names` table is a derived cache (rebuilt from Discord each push), so it needs no seeding/migration — an empty table on first run is the correct cold-start state (D-07). | **None** — no data migration. Verified against `core/settings.py::_SCHEMA` and `core/db.py`. |
| **Live service config** | None. No external UI/dashboard state (n8n, Datadog, etc.) is touched. The Discord guild's channels/roles ARE the upstream source, but they are read live into the cache, never mutated by this phase. | None — verified: this phase performs no Discord writes. |
| **OS-registered state** | None. No new systemd unit, scheduled task, or process-name change. The push cog loads inside the EXISTING bot process (one `load_extension` line in `bot.py`); the app is the EXISTING FastAPI unit. | None — verified against `bot.py::setup_hook` (cogs load in-process). |
| **Secrets/env vars** | None added or renamed. `config.GUILD_ID` / `config.DB_PATH` / `config.DISCORD_USER_ID` already exist and are reused as-is. No new `.env` key. | None — verified against `config.py`. |
| **Build artifacts / installed packages** | None. No `pip install`, no package rename, no egg-info churn. `app/static/alpine.min.js` is already vendored. | None — verified: no dependency changes. |

**The canonical question — "after every file is updated, what runtime systems still have old state?"** Answer for this phase: **nothing that requires migration.** SETT-01 is a UI re-parent over an unchanged store; SETT-02 adds a *derived, self-rebuilding* cache. The only "state" that must exist for SETT-02 to display names is a fresh `discord_names` push, which the bot produces automatically within one loop interval of startup (and until then, D-07's cold-cache banner covers the gap by design).

## Common Pitfalls

### Pitfall 1: The credential boundary (the STATE.md Phase-4 research gap — RESOLVED)
**What goes wrong:** A naive implementation adds a Discord API client (or bot token) to the FastAPI app to resolve names, breaking the locked "no bot credentials in the app" boundary and adding a REST rate-limit surface.
**Why it happens:** "Resolve a Discord name" *sounds* like it needs a Discord call. It does not — the name is already cached.
**How to avoid — the explicit sign-off content:**
- The bot runs `Intents.default()` (bot.py line 28), which includes the **non-privileged GUILDS intent**. That intent populates `Guild.channels` and `Guild.roles` in the bot's in-memory gateway cache on connect and keeps them current via CHANNEL_/GUILD_ROLE_ create/update/delete events. `[VERIFIED: web search — GUILDS intent is non-privileged and drives channel/role cache]`
- Reading `self.bot.get_guild(config.GUILD_ID).channels` / `.roles` is a **pure in-memory read: zero REST calls, zero rate limit, zero additional scope, zero new privileged intent.** (Contrast: `fetch_channel` IS a REST call — do not use it here.)
- **Direction of trust:** bot = sole WRITER of `discord_names` (it alone has the gateway); app = sole READER (it alone renders). This is identical to the already-approved `PresenceCog`→`get_presence` and `HeartbeatCog`→`get_heartbeat` flows. No new credential, token, or trust surface enters the app process. The app must not `import discord`.
**Warning signs:** any `import discord`, `fetch_channel`, `bot`, `BOT_TOKEN`, or `discord` HTTP client appearing under `app/`. Grep for these before merge.

### Pitfall 2: Snowflake precision loss when shipping the map to the browser (D-09)
**What goes wrong:** IDs above `2^53` silently round to a wrong integer in JS, so the live lookup misses valid IDs.
**Why it happens:** Jinja `| tojson` emits a Python `int` as a bare JS number literal (the exact bug `all_for_ui()`'s CR-01 note documents).
**How to avoid:** Store `id` as TEXT; build the resolution map with string keys; a JSON object's keys are always strings, so the shipped map is precision-safe. Compare against the raw-ID input value as a string.
**Warning signs:** a resolved name that flickers or fails only for large IDs; numeric `id` columns.

### Pitfall 3: Cold cache mistaken for deleted IDs (D-07)
**What goes wrong:** On first boot (or bot offline), the empty `discord_names` table makes every field show "name unavailable," alarming the owner.
**Why it happens:** Per-field fallback (D-06) can't tell "cache never populated" from "this specific ID is gone."
**How to avoid:** Compute one `names_fresh` signal (`MAX(synced_at)` within a staleness window; empty table = not fresh). When `!names_fresh`, render the single section-level "Sincronizando nombres · Names syncing" banner and suppress the per-field "no encontrado" marker (show raw ID only). When fresh, an unresolved ID legitimately shows the D-06 marker.
**Warning signs:** every field flagged simultaneously; markers appearing right after a deploy.

### Pitfall 4: Route/handler drift when consolidating the settings URL (D-02)
**What goes wrong:** The sidebar nav link and the 403 exception-handler special-case reference the settings path in TWO places (`_sidebar.html` line 12 → `/admin/settings`; `app/main.py` ~line 362 → `request.url.path == "/admin/settings"`). Change one without the other and either the nav 404s or a non-owner's styled in-shell 403 silently falls back to the wrong `login.html`.
**Why it happens:** The path is duplicated across a template and a Python string literal.
**How to avoid:** If the route path is kept as `/admin/settings` (recommended — least churn, both references already point there), change nothing about routing and only re-parent the template. If renamed to `/settings` for route-family consistency, update **both** `_sidebar.html` line 12 and `app/main.py` ~362 in the same change, and add a test asserting a Manager GET on the settings path renders `forbidden.html` (not `login.html`).
**Warning signs:** `test_app_dashboard.py`'s sidebar/settings 403 assertions failing after the change.

### Pitfall 5: WAL concurrency without `busy_timeout` (INFRA-02 not yet done)
**What goes wrong:** The new push writer + app reader add contention on `bot.db`. INFRA-02 (`busy_timeout` + retry) is Phase 5 — not yet in place.
**Why it happens:** WAL allows concurrent readers with one writer, but a writer-writer collision can still raise "database is locked."
**How to avoid:** This is acceptable pre-INFRA-02 because the name cache is a *low-frequency* writer (one snapshot every ~5 min) — the same risk profile the already-shipped 45s `bot_heartbeat` writer runs under without issue. Keep the push cadence generous (minutes, not seconds), keep the replace in a single short transaction, and wrap the write in the existing `try/except log` idiom (as `heartbeat.py` does) so a transient lock never crashes the loop. Do not attempt to pre-implement INFRA-02 here.
**Warning signs:** intermittent "database is locked" in bot logs correlated with a settings save.

### Pitfall 6: Dual-process init race
**What goes wrong:** The app reads `discord_names` before the bot has created the table → `no such table` → 500.
**Why it happens:** Two processes, either can start first.
**How to avoid:** Follow the codebase idiom exactly: call `db.init_discord_names()` in BOTH the cog `__init__` (bot side) AND the app `lifespan` (alongside the existing `init_heartbeat()` etc.). `get_discord_names` should also tolerate an empty result (cold cache) → the app degrades to raw IDs + cold banner, never a 500.
**Warning signs:** a 500 on `/admin/settings` only on a fresh DB / first boot.

## Code Examples

### Wiring the cog (one line in `bot.py::setup_hook`)
```python
# bot.py — alongside the other always-loaded cogs (heartbeat is the sibling to copy)
await self.load_extension("cogs.discord_names")
```
`[VERIFIED: bot.py::setup_hook lines 49-60]`

### App-side defensive init (extend the existing lifespan try-block)
```python
# app/main.py::lifespan — add to the SAME try/except that already inits heartbeat etc.
db.init_discord_names()
```
`[VERIFIED: app/main.py lifespan lines 284-291]`

### Template: resolved snowflake field (Alpine, mirrors UI-SPEC §Resolved Snowflake Field)
```html
<!-- inside the snowflake field template; `names` is the shipped id->{...} map -->
<div class="resolved" x-show="names[values[setting.key]]">
  <span class="cue" x-text="cueIcon(names[values[setting.key]])"></span>
  <span class="rname" x-text="names[values[setting.key]]?.name"></span>
</div>
<div class="resolved muted" x-show="!names[values[setting.key]] && values[setting.key]">
  <span class="raw-id" x-text="values[setting.key]"></span>
  <span class="unavailable" x-show="namesFresh">Name unavailable · no encontrado</span>
</div>
<div class="raw-id-line mono" x-text="values[setting.key]"></div>
<input type="text" inputmode="numeric" pattern="\d{17,20}" x-model="values[setting.key]" />
```
`[CITED: 04-UI-SPEC.md §Resolved Snowflake Field; existing settings.html snowflake template]`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Standalone `/admin/settings` page with its own `editor.css` chrome/topbar | In-shell Settings section extending `_dashboard_base.html` on `dashboard.css` tokens | Phase 4 (this phase) | Drops the bespoke topbar (duplicated by the shell); one nav + one save action |
| Raw-ID-only channel/role fields | Readable `#channel`/`@role` + ID beneath, bot-cache resolved | Phase 4 | New `discord_names` cache + template extension |

**Deprecated/outdated:** nothing removed at the store layer. The only retirement is the standalone settings *page chrome* (its bespoke `<header>`/topbar), superseded by the shared `_dashboard_base.html` topbar.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `discord.Role.colour.value == 0` reliably means "no custom color" and `f"#{value:06x}"` is the correct hex for a set color in discord.py 2.7.1 | Pattern 2 | LOW — worst case a role renders with a default/near-black bar; cosmetic only, never blocks save. Verify against discord.py 2.7.x `Colour` docs during planning. |
| A2 | `ChannelType.news`/`stage_voice` should map to `text`/`voice` cues respectively; unmapped types fall to `"other"` | Pattern 2 | LOW — the 6 `snowflake` settings fields are all normal text/forum/voice channels (per UI-SPEC Component Notes); exotic types never appear as a settings value. |
| A3 | Keeping the route at `/admin/settings` (vs renaming to `/settings`) satisfies D-02's "only Settings URL" intent | Pitfall 4, Open Q1 | MEDIUM — D-02's impl note mentions a "new section path," which could mean a deliberate rename. Needs a planner/owner decision. |
| A4 | A ~5-min push cadence is fresh enough for owner-facing name display, and safe pre-INFRA-02 | Pattern 2, Pitfall 5 | LOW — cadence is D-08 discretion; if too slow for perceived freshness, tighten to 1-2 min (still far below the 45s heartbeat writer's frequency). |
| A5 | No data migration is needed because `access`-group keys already live in `settings` | Runtime State Inventory | LOW — verified directly in `core/settings.py::_SCHEMA` (`manager_roles`/`editor_roles` present). |

## Open Questions (RESOLVED)

1. **Route path: keep `/admin/settings` or rename to `/settings`?**
   - **RESOLVED (planning):** KEEP `/admin/settings` — least churn; the sidebar link and 403 special-case already point there and need no change. Locked in Plan 04-03 Task 1.
   - What we know: D-02 says the in-shell section becomes the *only* Settings URL and mentions updating the 403 handler "to the new section path." The sidebar (line 12) and the 403 special-case (main.py ~362) currently both reference `/admin/settings`. The other 6 modules use un-prefixed paths (`/overview`, `/gallery`…).
   - What's unclear: whether "new section path" mandates a rename to `/settings` for route-family consistency, or is just describing "the section route."
   - Recommendation: **Keep `/admin/settings`** to minimize churn (both references already point there; retiring the "standalone" page means changing what it *renders*, not its URL). If the planner/owner prefers `/settings` for consistency, update `_sidebar.html` line 12 AND `app/main.py` ~362 together and add the forbidden-page regression test. Surface this to the owner in discuss/plan.

2. **Freshness signal: dedicated `synced_at` vs reuse `bot_heartbeat`?**
   - **RESOLVED (planning):** use the cache's OWN `synced_at` (`MAX(synced_at)` on `discord_names`) — reports "cache not yet populated" independently of bot liveness. Implemented in Plan 04-01 (schema) + Plan 04-03 Task 1 (`_read_name_cache` freshness).
   - What we know: D-08 leaves this to discretion. `MAX(synced_at)` on `discord_names` is self-contained; reusing `bot_heartbeat.last_beat_utc` couples cache-freshness to bot-liveness.
   - Recommendation: use the cache's own `synced_at` (per Pattern 3). It correctly reports "cache not yet populated" even while the bot is online but hasn't run its first push — which `bot_heartbeat` cannot distinguish.

3. **Push triggers: loop-only, or loop + guild event listeners?**
   - **RESOLVED (planning):** loop-only periodic full-snapshot (`@tasks.loop(minutes=5)`) — covers cold start + drift; guild event listeners deferred within D-08 discretion. Implemented in Plan 04-02.
   - What we know: D-08 discretion; events (`on_guild_channel_update`, `on_guild_role_update`, create/delete) give near-instant updates.
   - Recommendation: ship the periodic full-snapshot loop as the MVP (covers cold start + drift). Event listeners are a low-risk enhancement; include only if the plan has budget, otherwise defer within discretion.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py (gateway + GUILDS intent) | Bot cache push | ✓ | 2.7.1 (pinned) | — |
| GUILDS intent enabled | `Guild.channels`/`Guild.roles` cache | ✓ (non-privileged, part of `Intents.default()`, bot.py:28) | — | — |
| FastAPI / Jinja2 / Alpine (vendored) | App render + live lookup | ✓ | 0.139.0 / 3.1.6 / 3.15.12 | — |
| sqlite3 (WAL) | `discord_names` cache | ✓ | stdlib | — |
| pytest (conda python) | Wave 0 + regression | ✓ | >=8.0.0 | run via `C:\Users\Shangri\miniconda3\python.exe -m pytest` (per project memory) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. This phase installs nothing.

## Validation Architecture

> nyquist_validation key absent from `.planning/config.json` → treated as ENABLED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0.0 + `fastapi.testclient.TestClient` |
| Config file | none — `tests/conftest.py` puts repo root on `sys.path`; no `pytest.ini` |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py -x` |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |

**Env note:** Use the conda python for pytest (project memory — PowerShell's `Python314` has no pytest). Existing settings-relevant tests: `tests/test_settings.py` (store), `tests/test_app_settings.py` (route + two-pass POST), `tests/test_settings_template.py` (template render), `tests/test_app_dashboard.py` (shell/sidebar/403). The `client` fixture pattern (dummy OAuth config + `DB_PATH`→tmp + `settings.seed_defaults()` + `dependency_overrides[require_owner]`) is the exact harness to reuse.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SETT-01 | In-shell settings page renders (extends base, sidebar present, one save) | integration | `pytest tests/test_app_settings.py -k in_shell -x` | ❌ Wave 0 (extend existing) |
| SETT-01 | No loss of functionality: two-pass validate-then-write still atomic (mixed valid/invalid writes NOTHING) | integration | `pytest tests/test_app_settings.py -k two_pass -x` | ✅ (exists — assert unchanged) |
| SETT-01 | Non-owner GET/POST on settings path still 403 (fail-closed) | integration | `pytest tests/test_app_dashboard.py -k settings_403 -x` | ✅ (exists — assert unchanged after any route change) |
| SETT-02 | `db.replace_discord_names` full-replace + `get_discord_names` round-trip | unit | `pytest tests/test_discord_names.py -x` | ❌ Wave 0 (new) |
| SETT-02 | Resolved name + kind/color injected into render for a cached ID | integration | `pytest tests/test_app_settings.py -k resolves_name -x` | ❌ Wave 0 |
| SETT-02 | Unresolved ID + fresh cache → "no encontrado" marker; cold cache → banner, no per-field marker (D-06/D-07) | integration | `pytest tests/test_app_settings.py -k cold_cache -x` | ❌ Wave 0 |
| SETT-02 | Names map shipped to Alpine is keyed by STRING id (precision safety) | integration | `pytest tests/test_app_settings.py -k id_is_string -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `... -m pytest tests/test_app_settings.py tests/test_discord_names.py -x`
- **Per wave merge:** `... -m pytest -q` (full suite)
- **Phase gate:** full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_discord_names.py` — `db.init/replace/get_discord_names` contract (covers SETT-02 cache layer)
- [ ] `tests/test_app_settings.py` (extend) — in-shell render, name resolution, cold-cache banner, string-keyed map, plus a regression lock on the unchanged two-pass POST
- [ ] Bot cog test: a light unit over the `ChannelType`→subtype / `Colour`→hex mapping in `cogs/discord_names.py` (pure function, no gateway needed — factor the mapping into a testable helper)
- [ ] No framework install needed — pytest + TestClient already present.

## Security Domain

> security_enforcement key absent from `.planning/config.json` → treated as ENABLED.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Existing OAuth session cookie (itsdangerous-signed, `SessionMiddleware`) — unchanged |
| V3 Session Management | yes | Short-TTL signed session cookie (`https_only`, `same_site=lax`, 6h) — unchanged |
| V4 Access Control | yes (critical) | `require_owner` fail-closed gate on the settings route — **must stay unchanged** (D-03). The migration must not weaken the owner-only boundary. |
| V5 Input Validation | yes | Server-side allowlist validation via `core/settings.py::_SCHEMA` (`validate_only`/`set`) — unchanged. The name cache is read-only display; it never influences what is written. |
| V6 Cryptography | no | No new crypto. |
| V1 Data Protection / secret exposure | yes | `all_for_ui()` allowlist guarantees no secret reaches the panel; the `discord_names` cache contains only public guild channel/role names+colors — no secret, no PII. |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Snowflake precision corruption altering which ID is displayed/edited | Tampering (integrity) | String-keyed map + TEXT id column (Pitfall 2) |
| Privilege escalation via the retired route / 403 handler drift | Elevation of Privilege | Keep `require_owner` unchanged; move sidebar + 403 special-case together if renamed; regression test the Manager-403 path (Pitfall 4) |
| Credential-boundary breach (bot token / Discord client leaking into the app) | Spoofing / EoP | App never imports discord; resolution is sqlite-only; grep-gate for `import discord`/`fetch_channel` under `app/` (Pitfall 1) |
| Cache poisoning of displayed names | Tampering | Bot is the sole writer (gateway-sourced); app never writes `discord_names`; names are display-only and never fed back into `settings.set` |
| Cold-DB 500 (availability) | Denial of Service | Dual-process defensive `init_discord_names()` + empty-result tolerance (Pitfall 6) |

**Note:** The name cache stores only *public* guild metadata (channel names, role names, role colors) that any guild member can already see. It contains no secret, token, or personal data — so the new table does not expand the app's sensitive-data footprint.

## Sources

### Primary (HIGH confidence)
- `core/db.py`, `cogs/heartbeat.py`, `cogs/presence.py` — the exact bot→app shared-sqlite pattern to mirror (`bot_heartbeat` triad, dual-process init, WAL, `to_thread` writes)
- `core/settings.py` — the unchanged store (`_SCHEMA`, `validate_only`, `set`, `all_for_ui`, the CR-01 snowflake-stringification note)
- `app/main.py` — `settings_page`/`save_settings` (unchanged POST flow), the 403 exception handler special-case (~line 362), `_compute_online`/`_read_overview_status` (the read-and-render idiom to copy), lifespan defensive init
- `app/templates/settings.html`, `_dashboard_base.html`, `_sidebar.html`, `module_stub.html` — the migration source + target chrome
- `bot.py` — `Intents.default()` + `intents.members`/`intents.presences` (line 28-42), cog loading (`setup_hook`), `GUILD_ID` usage
- `config.py` — `GUILD_ID`, `DB_PATH`, `DISCORD_USER_ID`, `ROLE_MODERATOR_ID` (all reused, none added)
- `.planning/phases/04-settings-migration-name-resolution/04-CONTEXT.md` and `04-UI-SPEC.md` — locked decisions D-01..D-09 and the component/copy contract
- `tests/conftest.py`, `tests/test_app_settings.py`, `tests/test_app_dashboard.py` — the reusable TestClient harness

### Secondary (MEDIUM confidence)
- discordpy.readthedocs.io (API reference / changelog) — `Guild.channels`, `Guild.roles`, `Role.colour`, `ChannelType` semantics `[CITED]`
- Web search (Discord gateway intents) — confirmation that the **GUILDS intent is non-privileged** and drives the channel/role cache (CHANNEL_* and GUILD_ROLE_* events) `[VERIFIED cross-source]`

### Tertiary (LOW confidence)
- Training-knowledge details of `discord.Colour.value`/`is_default()` exact behavior in 2.7.1 (see Assumptions A1) — verify against pinned-version docs during planning.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every dependency is already pinned and in use.
- Architecture: HIGH — the SETT-02 cache is a structural clone of the shipped `bot_heartbeat` pattern; SETT-01 is a template re-parent over an unchanged store.
- Credential boundary (the STATE.md research gap): HIGH — resolved by the non-privileged GUILDS-intent gateway cache (verified) + the existing bot-writes/app-reads sqlite discipline.
- Pitfalls: HIGH for codebase-grounded ones (route drift, precision, dual-init, cold cache); MEDIUM for the discord.py Colour/ChannelType edge details (Assumptions log).

**Research date:** 2026-07-22
**Valid until:** ~2026-08-21 (30 days — stable stack; the only external surface, discord.py 2.7.1, is version-pinned)
