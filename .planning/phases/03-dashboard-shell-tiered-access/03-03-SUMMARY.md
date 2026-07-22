---
phase: 03-dashboard-shell-tiered-access
plan: 03
subsystem: bot-side Overview data plumbing
tags: [sqlite, discord.py, tasks-loop, dashboard-shell]
dependency-graph:
  requires: []
  provides:
    - core/db.py::init_heartbeat/set_heartbeat/get_heartbeat
    - core/db.py::init_jinxxy_sync_status/set_jinxxy_sync_status/get_jinxxy_sync_status
    - core/db.py::init_activity_log/log_activity/get_recent_activity
    - cogs/heartbeat.py::HeartbeatCog
  affects:
    - bot.py (setup_hook load_extension list)
tech-stack:
  added: []
  patterns:
    - "single-row CHECK (id = 1) + INSERT OR REPLACE (bot_heartbeat, jinxxy_sync_status)"
    - "append-only AUTOINCREMENT + purge-on-write bounded retention (activity_log)"
    - "always-loaded @tasks.loop cog with before_loop wait_until_ready + cog_unload cancel"
key-files:
  created:
    - cogs/heartbeat.py
  modified:
    - core/db.py
    - bot.py
decisions:
  - "Wrapped db.set_heartbeat write in try/except Exception: log.exception (Rule 2), matching cogs/presence.py's _store idiom — one failed write must never kill the 45s loop."
  - "Heartbeat cadence 45s / activity_log retention 500 rows, both explicitly Claude's Discretion per RESEARCH.md A2/A3."
metrics:
  duration: "~15 min"
  completed: 2026-07-21
---

# Phase 3 Plan 3: Bot-side Overview Data Plumbing Summary

Added three new shared-sqlite tables (`bot_heartbeat`, `jinxxy_sync_status`, `activity_log`)
with 9 init/get/set helpers in `core/db.py`, plus a new always-loaded `cogs/heartbeat.py`
`@tasks.loop(seconds=45)` cog that writes the heartbeat row — the bot-side data source for
SHELL-02's Overview status tiles, following the exact `presence`/`store_snapshot` writer
precedent already in the repo.

## What Was Built

**Task 1 — `core/db.py`:**
- `bot_heartbeat`: single-row (`id INTEGER PRIMARY KEY CHECK (id = 1)`) table with
  `last_beat_utc`, `latency_ms`, `started_at_utc`, `guild_member_count`, `loaded_cogs`
  (JSON list). `init_heartbeat()` / `set_heartbeat(latency_ms, started_at_utc,
  guild_member_count, loaded_cogs)` (upsert, stamps `last_beat_utc` fresh) /
  `get_heartbeat()` (row or `None`).
- `jinxxy_sync_status`: single-row table with `last_run_utc`, `ok`, `product_count`,
  `error` — kept as its OWN table (not merged into `bot_heartbeat`), per RESEARCH.md's
  one-table-per-concern precedent and D-10 (Phase 8's manual-sync display reuses this
  exact record). `init_jinxxy_sync_status()` / `set_jinxxy_sync_status(ok, product_count,
  error)` / `get_jinxxy_sync_status()`.
- `activity_log`: append-only (`id INTEGER PRIMARY KEY AUTOINCREMENT`) table with
  `event_type`, `message`, `created_at`. `init_activity_log()` / `log_activity(event_type,
  message, keep_last=500)` (insert then purge via `DELETE ... WHERE id NOT IN (SELECT id
  ... ORDER BY id DESC LIMIT ?)`, mirroring `view_dedup`'s cutoff-delete idiom) /
  `get_recent_activity(limit=10)`.
- All new code follows the file's existing `_get_conn()` (WAL pragma set per-connection,
  never re-set)/`with conn:`/parameterized-`?` discipline verbatim.

**Task 2 — `cogs/heartbeat.py` + `bot.py`:**
- New `HeartbeatCog(commands.Cog)`: `__init__` records `started_at` (ISO UTC), calls
  `db.init_heartbeat()` defensively, starts `@tasks.loop(seconds=45)` named `_beat`.
  `cog_unload` cancels `_beat` (hot-reload safety, mirrors `jinxxy`/`reminders`).
  `_beat` resolves `guild = self.bot.get_guild(config.GUILD_ID)` with a `None`-guard
  (falls back to `guild_member_count=None` per A4) and writes via
  `asyncio.to_thread(db.set_heartbeat, ...)`. `@_beat.before_loop` awaits
  `self.bot.wait_until_ready()`. Module-level `async def setup(bot)` adds the cog.
- `bot.py::setup_hook` gained `await self.load_extension("cogs.heartbeat")` in the
  always-loaded block (before the meeting cog's optional-deps try/except) — heartbeat has
  no heavy dependencies and must always load.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - missing error handling] Wrapped the heartbeat write in try/except**
- **Found during:** Task 2
- **Issue:** The plan's `<action>` text specifies the bare
  `await asyncio.to_thread(db.set_heartbeat, ...)` call with no error handling. Every
  other bot-writes-sqlite-on-event cog in this codebase (`cogs/presence.py::_store`)
  wraps its write in `try/except Exception: log.exception(...)` so a transient sqlite
  write failure (e.g. a lock contention edge case) never propagates and kills the
  `@tasks.loop`. Without this guard, one bad write would silently stop future heartbeats
  from ever being written again (the loop errors out; `@_poll.error`-style auto-restart
  was not specified for this loop by the plan).
- **Fix:** Wrapped the `asyncio.to_thread(db.set_heartbeat, ...)` call in
  `try/except Exception: log.exception("heartbeat: no pude escribir el latido")`,
  matching `cogs/presence.py::_store`'s exact idiom.
- **Files modified:** `cogs/heartbeat.py`
- **Commit:** `6e4dec7`

No other deviations — the rest of the plan executed as written.

## Known Stubs

None. All three tables and the heartbeat cog are fully functional; no placeholder/empty
data paths were introduced. The app-side read path (Overview page consuming these tables)
is explicitly out of this plan's scope (Plan 03-07).

## Threat Flags

None. This plan's new surface (three sqlite tables, one always-loaded cog) was fully
covered by the plan's own `<threat_model>` (T-03-07 activity_log DoS via unbounded growth
— mitigated by purge-on-write; T-03-08 tampering via app-side writes — no app-side write
helper exists for these tables; T-03-09 heartbeat info disclosure — accepted, no
secrets/PII stored).

## Verification

- `core/db.py` round-trip verify command (from the plan): initialises all three tables,
  logs one activity row, reads it back — passed (`1`).
- Purge-on-write bound verified manually: inserting 600 rows with `keep_last=500` leaves
  exactly 500 rows — passed.
- `grep -c` for the 9 helper function definitions in `core/db.py` — returns 9.
- `core/db.py` contains `CHECK (id = 1)` (bot_heartbeat + jinxxy_sync_status, 5 total
  occurrences across the file including pre-existing tables) and `AUTOINCREMENT`
  (activity_log + 3 pre-existing tables, 4 total).
- `cogs/heartbeat.py` parses cleanly via `ast.parse` — printed `ok`.
- `grep -c 'load_extension("cogs.heartbeat")' bot.py` — returns 1, placed before the
  meeting cog's try/except block.
- `python -m pytest --collect-only -x` — 645 tests collected, no new import error
  (matches the pre-plan baseline from the v1.0 archive).

## Self-Check: PASSED

- FOUND: `core/db.py` (modified, contains all 9 new helper functions)
- FOUND: `cogs/heartbeat.py` (created)
- FOUND: `bot.py` (modified, load_extension line present)
- FOUND commit `9120797` (core/db.py tables + helpers)
- FOUND commit `6e4dec7` (HeartbeatCog + bot.py registration)
