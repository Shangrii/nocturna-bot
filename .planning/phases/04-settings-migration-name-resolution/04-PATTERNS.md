# Phase 04: Settings Migration + Name Resolution - Pattern Map

**Mapped:** 2026-07-22
**Files analyzed:** 8 (2 new, 6 modified)
**Analogs found:** 8 / 8 (every file rides an already-shipped in-repo pattern)

> This is a **90% migration / 10% new-cache** phase. Nearly every new file is a
> structural clone of the shipped `bot_heartbeat` triad (`core/db.py` +
> `cogs/heartbeat.py` + `app/main.py` read) or a re-parent of an existing template.
> Copy the named analog verbatim in structure; do not invent new infrastructure.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `core/db.py` (add `discord_names` triad) | model / data-access | event-driven (bot writes) + request-response (app reads) | `core/db.py` `init_heartbeat`/`set_heartbeat`/`get_heartbeat` (lines 569-609) | exact (same file, same idiom) |
| `cogs/discord_names.py` (NEW) | cog / provider | pub-sub push (`@tasks.loop` → sqlite) | `cogs/heartbeat.py` (whole file, 62 lines) | exact |
| `bot.py` (add one `load_extension`) | config / bootstrap | — | `bot.py::setup_hook` line 60 (`load_extension("cogs.heartbeat")`) | exact |
| `app/main.py::settings_page` (read + inject names) | controller / route | request-response (SSR read) | `app/main.py::overview_page` + `_read_overview_status`/`_compute_online` (lines 505-596) | role+flow match |
| `app/main.py::lifespan` (add `init_discord_names`) | config | request-response | `app/main.py::lifespan` init block (lines 284-291) | exact |
| `app/templates/settings.html` (REWRITE to extend base) | component / template | request-response render | `app/templates/module_stub.html` (chrome) + existing `settings.html` (field templates) | exact (re-parent) |
| `app/static/dashboard.css` (add `settings` block) | config / style | — | `dashboard.css` `.card`/`.mod-hdr`/`.empty` + `editor.css` `.field`/`.theme-group`/`.chip` | role match |
| `tests/test_discord_names.py` (NEW) | test | — | `tests/test_settings.py` `_use_tmp_db` + init/round-trip tests (lines 27-45) | exact |
| `tests/test_app_settings.py` (EXTEND) | test | — | existing `tests/test_app_settings.py` `client` fixture (lines 26-43) | exact (same file) |

**403 handler note (`app/main.py` ~line 362):** touch ONLY if the route is renamed off
`/admin/settings`. Recommendation (RESEARCH Open Q1): keep `/admin/settings`, change nothing
about routing — only re-parent the template. If renamed, the sidebar link
(`_sidebar.html` line 12) and the 403 special-case string literal must move together.

---

## Pattern Assignments

### `core/db.py` — add the `discord_names` triad (model, bot-write/app-read)

**Analog:** `core/db.py::init_heartbeat` / `set_heartbeat` / `get_heartbeat` (lines 569-609).
The single-row `bot_heartbeat` is the shape to mirror, but `discord_names` is **multi-row**
(one row per channel/role), so pair it with the **full-snapshot-replace** idiom already used
elsewhere in the file rather than `INSERT OR REPLACE` of one row.

**Module header / connection helper** (lines 1-17) — reuse as-is, add nothing:
```python
import json
import sqlite3
from datetime import datetime, timezone
import config

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # CONC-01: bot writes while app reads
    return conn
```

**`init_*` idiom to copy** (lines 569-585 — `CREATE TABLE IF NOT EXISTS` inside
`with _get_conn() as conn:`; dual-process defensive init, called from BOTH cog `__init__`
and app `lifespan`):
```python
def init_heartbeat():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_heartbeat (
                id                 INTEGER PRIMARY KEY CHECK (id = 1),
                last_beat_utc      TEXT NOT NULL,
                ...
            )
        """)
```

**Full-snapshot-replace writer** — the RESEARCH touch-map calls for `replace_discord_names`.
The closest in-repo write idioms are `set_heartbeat` (INSERT OR REPLACE, single row, lines
588-600) and the `log_activity` DELETE-then-INSERT bound-write (lines 668-683). For a
multi-row snapshot, do `DELETE` + `executemany` in ONE `with conn:` transaction (atomic —
deleted channels/roles fall out for free). Stamp `synced_at` with the repo's canonical
timestamp idiom `datetime.now(timezone.utc).isoformat()` (used in `set_heartbeat` line 599,
`save_post` line 123, `set_presence` line 540). **Store `id` as TEXT** (not INTEGER) — see
Shared Patterns → Snowflake precision.

**Multi-row reader to copy** — `get_store_snapshot` (lines 397-406) returns all rows;
`get_recent_activity` (lines 686-692) is the `.fetchall()` shape. Mirror for
`get_discord_names() -> list[sqlite3.Row]`. Tolerate an empty result (cold cache) — never 500.

---

### `cogs/discord_names.py` (NEW) — push cog (provider, pub-sub → sqlite)

**Analog:** `cogs/heartbeat.py` (entire file, 62 lines). Clone its structure 1:1.

**Full structure to mirror** (`cogs/heartbeat.py` lines 11-61):
```python
import asyncio
import logging
from datetime import datetime, timezone
from discord.ext import commands, tasks
import config
from core import db

log = logging.getLogger(__name__)

class HeartbeatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._started_at = datetime.now(timezone.utc).isoformat()
        db.init_heartbeat()                         # dual-process defensive init (Pitfall 6)
        self._beat.start()

    async def cog_unload(self):
        self._beat.cancel()                          # hot-reload safety

    @tasks.loop(seconds=45)                          # cadence = Claude's Discretion
    async def _beat(self):
        guild = self.bot.get_guild(config.GUILD_ID)  # cold-start race → None, skip
        member_count = guild.member_count if guild is not None else None
        try:
            await asyncio.to_thread(db.set_heartbeat, ...)   # write OFF the event loop
        except Exception:
            log.exception("heartbeat: no pude escribir el latido")

    @_beat.before_loop
    async def _before_beat(self):
        await self.bot.wait_until_ready()            # gateway ready → cache populated

async def setup(bot: commands.Bot):
    await bot.add_cog(HeartbeatCog(bot))
```

**What changes for `discord_names`:**
- `@tasks.loop(minutes=5)` instead of `seconds=45` (D-08 discretion; low-frequency writer
  is safe pre-INFRA-02, RESEARCH Pitfall 5).
- In the loop body, read `guild.channels` and `guild.roles` from the gateway cache (NO REST),
  build the `rows` list, `await asyncio.to_thread(db.replace_discord_names, rows)`.
- Skip `role.is_default()` (@everyone) and map `ChannelType`→subtype / `Colour.value`→
  `f"#{value:06x}"`. **Factor the `ChannelType`/`Colour` mapping into a module-level pure
  helper** so it is unit-testable without a gateway (RESEARCH Wave 0 gap).
- The Spanish `log.exception(...)` idiom is house style — keep it.

**Anti-pattern (RESEARCH Pitfall 1):** the cog is the SOLE writer. The app must never
`import discord` / `fetch_channel`. This cog is byte-identical in trust to `HeartbeatCog`.

---

### `bot.py` — one `load_extension` line (bootstrap)

**Analog:** `bot.py::setup_hook` line 60. Add alongside the always-loaded siblings (NOT in
the optional-deps try/except that wraps `cogs.meeting` at lines 64-67):
```python
# bot.py setup_hook, lines 50-60 — the always-loaded cog block
await self.load_extension("cogs.heartbeat")     # ← existing sibling; add the new line here
await self.load_extension("cogs.discord_names") # ← NEW
```

---

### `app/main.py::settings_page` — read cache + inject map (controller, request-response)

**Analog:** `overview_page` (lines 578-596) + `_read_overview_status` (lines 563-568) +
`_compute_online` (lines 505-516). This is the exact "read tables off the event loop, compute
a freshness bool, seed the template" idiom.

**Off-event-loop read idiom to copy** (lines 563-568):
```python
async def _read_overview_status() -> dict:
    heartbeat = await run_in_threadpool(db.get_heartbeat)
    sync = await run_in_threadpool(db.get_jinxxy_sync_status)
    activity_rows = await run_in_threadpool(db.get_recent_activity, 10)
    return _build_overview_status(heartbeat, sync, activity_rows)
```
→ Write `_read_name_cache()` that does `await run_in_threadpool(db.get_discord_names)`, builds
a **string-keyed** `{id: {name, kind, subtype, color}}` map, and computes `names_fresh`.

**Freshness-bool idiom to copy** (`_compute_online`, lines 505-516 — tz-aware parse of an ISO
timestamp against a staleness window; the exact template for `names_fresh` from
`MAX(synced_at)`):
```python
def _compute_online(heartbeat_row) -> bool:
    if heartbeat_row is None:
        return False
    try:
        last_beat = datetime.fromisoformat(heartbeat_row["last_beat_utc"])
    except (TypeError, ValueError):
        return False
    if last_beat.tzinfo is None:
        last_beat = last_beat.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - last_beat).total_seconds()
    return 0 <= age_seconds <= _HEARTBEAT_STALE_SECONDS
```

**Existing route body to extend** (`settings_page`, lines 650-667 — keep `require_owner`, keep
`settings.all_for_ui()`; add the names map + `names_fresh` + switch `asset_v` to the dashboard
css mtime helper `_dashboard_asset_v()` at line ~499 since the template now uses dashboard.css):
```python
@app.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request, ident: dict = Depends(require_owner)):
    return templates.TemplateResponse(
        request, "settings.html",
        {"groups": settings.all_for_ui(), "asset_v": asset_v},  # ← add: names, names_fresh
    )
```

**`save_settings` (lines 670-708): DO NOT TOUCH.** D-03 non-negotiable. The two-pass
validate-then-write (validate_only all → 422 error map if any invalid → only then `set`) is
the load-bearing atomicity guarantee. Migration is read-side + presentation only.

**`lifespan` defensive init** (lines 284-291) — add `db.init_discord_names()` inside the SAME
try/except:
```python
    try:
        db.init_presence()
        db.init_view_counts()
        db.init_heartbeat()
        db.init_jinxxy_sync_status()
        db.init_activity_log()
        # db.init_discord_names()   ← ADD HERE (dual-process defensive init, Pitfall 6)
    except Exception:
        log.exception("no pude inicializar las tablas de presencia/vistas/dashboard")
```

---

### `app/templates/settings.html` — REWRITE to extend the shell (component, render)

**Analog (chrome):** `app/templates/module_stub.html` (whole file) — shows the exact
`{% extends "_dashboard_base.html" %}` + `.mod-hdr` block shape a settings page should adopt.

**Re-parent pattern to copy** (`module_stub.html` lines 1-10):
```html
{% extends "_dashboard_base.html" %}
{% block title %}{{ section_label | default('Módulo') }}{% endblock %}
{% block content %}
<div class="mod-hdr" style="--acc: {{ accent | default('var(--color-primary)') }}">
  <span class="i">{{ icon | default('•') }}</span>
  <div>
    <div class="t">{{ section_label | default('Módulo') }}</div>
    {% if section_description %}<div class="s">{{ section_description }}</div>{% endif %}
  </div>
</div>
```
→ Settings uses icon `⚙`, title "Ajustes · Settings", `--acc: var(--accent-settings)`
(UI-SPEC). `_dashboard_base.html` (lines 18-23) already provides the topbar with
"Volver al editor" / "Salir" — **DELETE** the bespoke `<header class="topbar">` currently in
`settings.html` (lines 24-32), it duplicates the shell.

**What to PRESERVE verbatim from the current `settings.html`** (D-03 no-loss):
- The single-quoted `x-data='settingsApp({{ groups | tojson }})'` guard (lines 18-22) — the
  comment explains WHY single quotes are load-bearing; keep it.
- The `settingsApp(initial)` Alpine factory (lines 104-170): flatten-to-`values`, `groupLabel`,
  `serialize`, and the `save()` POST-to-`/admin/settings` flow. Unchanged.
- Every field-type `<template x-if>` (lines 44-87): `int_range`, `timezone`, `free_string`,
  `url`, `lang` are unchanged (only re-skinned). Only `snowflake` (44-48) and `role_list`
  (51-54) get extended with the resolved-name preview / chips per UI-SPEC.
- `.field-error` / `.field-hint` bindings (lines 89-90) and the toast (lines 98-99).

**What changes:**
- `<link ... editor.css>` (line 15) → dropped; base template loads `dashboard.css`.
- Each `<fieldset class="theme-group">` (line 36) → `.card` with `.card-hdr h3` (UI-SPEC:
  one card per schema group; `access` group LAST after `forum`).
- Ship the names map into Alpine x-data as a second arg (`{{ names | tojson }}`) for D-09 live
  lookup; add the cache-cold banner (bound to `namesFresh`) above the groups. Template excerpt
  for the resolved snowflake field is in 04-RESEARCH.md "Code Examples" and 04-UI-SPEC.md
  §Resolved Snowflake Field / §Role Chips.

---

### `app/static/dashboard.css` — add a `settings` block (style)

**Analogs:**
- Structure tokens already declared in `dashboard.css`: `--color-warning: #ffb020` (line 24),
  `--accent-settings: #8b93a3` (line 36), `--font-mono` (line 40), `.btn`/`.btn.ghost`
  (lines 91-101), `.card`/`.card-hdr` (lines 149-154), `.empty` (lines 165-168),
  `.mod-hdr` + `.mod-hdr .i/.t/.s` (lines 187-197). Build every new element from these — no
  new token (UI-SPEC hard constraint).
- Port-in-spirit source: `editor.css` `.field` (line 164), `.theme-group` (line 395),
  `.chip` (line 437), `.field--invalid` (line 753), `.field-error` (line 756),
  `.field-hint` (line 448). Re-skin these onto dashboard tokens; do NOT copy their raw
  `--sp-*`/`--red` values (those are the editor's token system).

**New sub-blocks to add** (all from existing tokens): resolved-name preview row, role chip
(rounded rect + 3px left color-bar = the `.mod-hdr`/`.stat` accent-bar mechanism, never a
fill), "name unavailable" marker (muted Label), cache-cold banner (`--color-warning` left
border + `⏳`). Chip color bar consumes the per-role Discord hex as DATA (inline style), not a
design token — see 04-UI-SPEC.md §Color "third accent category".

---

### `tests/test_discord_names.py` (NEW) — db-contract test (Wave 0)

**Analog:** `tests/test_settings.py` `_use_tmp_db` + the init/round-trip tests (lines 27-45).

**tmp-db isolation to copy** (lines 27-29 — every test points `DB_PATH` at a throwaway file so
no test touches real `bot.db`):
```python
def _use_tmp_db(monkeypatch, tmp_path, name="settings.db"):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)
```

**Contract shape to mirror** (lines 33-45):
```python
def test_round_trip_get_set(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    settings.set("PHOTO_CHANNEL_ID", 1416329356426481717)
    assert settings.get("PHOTO_CHANNEL_ID") == 1416329356426481717

def test_init_table_creates_settings(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with db._get_conn() as conn:
        conn.execute("SELECT key, value FROM settings").fetchall()
```
→ Cover: `init_discord_names` creates the table; `replace_discord_names` full-replace (a second
replace with fewer rows DROPS the removed ones — the deleted-channel case); `get_discord_names`
round-trips id/kind/name/subtype/color; empty table returns `[]` (cold-cache tolerance). Plus a
pure-function unit test over the `ChannelType`→subtype / `Colour`→hex helper.

---

### `tests/test_app_settings.py` (EXTEND) — route integration (Wave 0 + regression lock)

**Analog:** the same file's `client` fixture (lines 26-43). Reuse it verbatim.

**Fixture to reuse** (lines 26-43 — dummy OAuth config + `DB_PATH`→tmp + `seed_defaults()` +
`dependency_overrides[require_owner]`):
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

**Regression lock to keep GREEN unchanged** (the two-pass atomicity test, lines 103-116) —
assert D-03 is preserved after the migration:
```python
def test_post_settings_mixed_valid_invalid_returns_422_and_writes_nothing(client):
    default_poll_hours = settings.get("JINXXY_POLL_HOURS")
    resp = client.post("/admin/settings",
                       json={"JINXXY_POLL_HOURS": 12, "PHOTO_CHANNEL_ID": "nope"})
    assert resp.status_code == 422
    assert "PHOTO_CHANNEL_ID" in resp.json()["errors"]
    assert settings.get("JINXXY_POLL_HOURS") == default_poll_hours   # nothing written
```

**New tests to add** (RESEARCH Test Map): in-shell render (extends base / sidebar present /
`.mod-hdr`); a cached ID resolves to name+kind+color in the render; unresolved ID + fresh cache
→ "no encontrado" marker, cold cache → banner + no per-field marker (D-06/D-07); the names map
shipped to Alpine is keyed by STRING id (precision safety). To populate the cache in a test,
call `db.replace_discord_names([...])` against the tmp DB before the GET.

**Cross-file 403 regression** (`tests/test_app_dashboard.py` lines 129-142, 202-205): a Manager
GET on the settings path still 403s and an anonymous caller renders `login.html` not the shell.
Keep green; if the route is renamed, update these assertions + `_sidebar.html` line 12 +
`app/main.py` ~362 together.

---

## Shared Patterns

### Cross-process channel = shared sqlite ONLY (bot writes, app reads)
**Source:** `core/db.py` lines 559-609 (the `bot_heartbeat`/`jinxxy_sync_status`/`activity_log`
header comment + triad); `cogs/heartbeat.py`; `app/main.py::_read_overview_status`.
**Apply to:** `discord_names` table, `cogs/discord_names.py`, `settings_page` read.
The bot is the SOLE writer (it alone has the gateway); the app is the SOLE reader (it alone
renders). No IPC/HTTP — locked project decision. The app process must never `import discord`.

### Dual-process defensive init (never 500 on a cold/missing table)
**Source:** `cogs/heartbeat.py` line 29 (`db.init_heartbeat()` in cog `__init__`) +
`app/main.py::lifespan` lines 284-291 (same `init_*` in the app's try/except).
**Apply to:** call `db.init_discord_names()` in BOTH `DiscordNamesCog.__init__` AND the app
`lifespan` block. `get_discord_names` must tolerate an empty result → cold-cache banner, not 500
(RESEARCH Pitfall 6).

### Canonical UTC timestamp + tz-aware freshness parse
**Source (write):** `datetime.now(timezone.utc).isoformat()` — `core/db.py` `set_heartbeat`
line 599, `save_post` line 123, `set_presence` line 540.
**Source (read/compare):** `app/main.py::_compute_online` lines 505-516 (`fromisoformat` +
`if tzinfo is None: replace(tzinfo=timezone.utc)` + age-vs-window).
**Apply to:** `synced_at` on every `discord_names` row; `names_fresh` from `MAX(synced_at)`.

### Off-event-loop sqlite access in the async app
**Source:** `app/main.py` — `await run_in_threadpool(db.get_heartbeat)` (line 565);
`cogs/heartbeat.py` — `await asyncio.to_thread(db.set_heartbeat, ...)` (line 44).
**Apply to:** app reads `discord_names` via `run_in_threadpool`; cog writes via
`asyncio.to_thread` — never block the event loop on sqlite.

### Snowflake precision safety (TEXT id + string-keyed map)
**Source:** `core/settings.py::all_for_ui` lines 406-425 (snowflakes serialized to `str`;
the CR-01 note that `| tojson` on a bare `int` rounds above 2^53);
`tests/test_app_settings.py::test_post_settings_unchanged_save_preserves_snowflake_precision`
(lines 138-148, the precision regression).
**Apply to:** store `discord_names.id` as TEXT; build the resolution map with STRING keys so the
JSON object shipped to Alpine (D-09) is inherently precision-safe (RESEARCH Pitfall 2).

### Fail-closed owner gate (unchanged)
**Source:** `app/main.py::settings_page`/`save_settings` `Depends(require_owner)` (lines 651,
671); the 403 exception-handler special-case (lines 362-373).
**Apply to:** keep `require_owner` on both settings routes verbatim (D-03, ASVS V4). The
migration must not weaken the owner-only boundary.

### Bilingual (ES·EN) user-facing copy
**Source:** `_sidebar.html` labels; `settings.html` toasts (lines 154-164);
`cogs/heartbeat.py` Spanish `log.exception` (line 52); `module_stub.html` empty-state.
**Apply to:** cog log messages (Spanish), all new UI copy per 04-UI-SPEC.md Copywriting
Contract. NOTE the one locked exception: "Name unavailable · no encontrado" is EN-then-ES by
D-06 — preserve verbatim, do not reorder to house style.

---

## No Analog Found

None. Every file in this phase maps onto an already-shipped in-repo pattern (the `bot_heartbeat`
triad, `overview_page` read/compute, `module_stub.html` re-parent, `test_settings.py` /
`test_app_settings.py` harnesses). The RESEARCH doc's central risk is **over-building** (adding a
REST resolver or a second IPC channel), not under-building — there is no greenfield surface here.

---

## Metadata

**Analog search scope:** `core/`, `cogs/`, `app/` (main.py, templates/, static/), `bot.py`,
`tests/`.
**Files scanned:** `core/db.py`, `core/settings.py`, `cogs/heartbeat.py`, `bot.py`,
`app/main.py`, `app/templates/settings.html`, `app/templates/_dashboard_base.html`,
`app/templates/module_stub.html`, `app/templates/_sidebar.html`, `app/static/dashboard.css`,
`app/static/editor.css`, `tests/test_app_settings.py`, `tests/test_app_dashboard.py`,
`tests/test_settings.py`.
**Pattern extraction date:** 2026-07-22
