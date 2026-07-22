---
phase: 04-settings-migration-name-resolution
plan: 02
subsystem: bot
tags: [discord, gateway-cache, sqlite, tasks-loop, pytest]

requires:
  - phase: 04-settings-migration-name-resolution
    plan: 01
    provides: discord_names shared-sqlite helper triad
provides:
  - Always-loaded DiscordNamesCog that snapshots cached guild channels and roles
  - Channel-kind and role-colour mapping helpers
  - Unit coverage for mappings and @everyone exclusion
affects: [04-03-app-settings-migration]

tech-stack:
  added: []
  patterns: [gateway-cache-only reads, periodic full-snapshot sqlite push]

key-files:
  created:
    - cogs/discord_names.py
    - tests/test_discord_names_cog.py
  modified:
    - bot.py

requirements-completed: [SETT-02]
completed: 2026-07-22
---

# Phase 4 Plan 02: Bot-Side Discord Name Cache Summary

The bot now snapshots channel and role metadata from its in-memory guild cache into the shared `discord_names` sqlite table every five minutes.

## Accomplishments

- Added `DiscordNamesCog` using the established heartbeat `@tasks.loop` lifecycle, including readiness wait, cold-start guard, hot-reload cancellation, and logged write failures.
- Read only `guild.channels` and `guild.roles`; no Discord REST calls, new intents, credentials, or scopes were added.
- Mapped text/forum/voice/news/stage channel types, converted custom role colours to lowercase hex, and excluded the default `@everyone` role.
- Moved the sqlite snapshot write off the event loop with `asyncio.to_thread(db.replace_discord_names, rows)`.
- Registered `cogs.discord_names` in the unconditional cog-loading block immediately after `cogs.heartbeat`.

## Task Commits

No commits were created, per the explicit instruction to leave changes for review.

## Files Created/Modified

- `cogs/discord_names.py` - Gateway-cache snapshot cog and pure mapping helpers.
- `bot.py` - Always-loaded cog registration.
- `tests/test_discord_names_cog.py` - Mapping and `@everyone` exclusion unit tests.
- `.planning/phases/04-settings-migration-name-resolution/04-02-SUMMARY.md` - Plan outcome and verification evidence.

## Deviations from Plan

None. App-side settings files and Plan-04-03 RED tests were left unchanged.

## Verification

- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_discord_names_cog.py -x`: **9 passed**.
- `C:\Users\Shangri\miniconda3\python.exe -c "import cogs.discord_names"`: **passed**.
- REST-call scan of `cogs/discord_names.py`: **no matches**.
- `git diff --check`: **passed**.

## User Setup Required

None. No dependency, intent, credential, or environment changes were introduced.

---
*Phase: 04-settings-migration-name-resolution*
*Completed: 2026-07-22*
