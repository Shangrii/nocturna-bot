---
phase: 04-settings-migration-name-resolution
plan: 03
subsystem: ui
tags: [fastapi, jinja2, alpinejs, sqlite, discord-snowflakes]

requires:
  - phase: 04-settings-migration-name-resolution
    plan: 01
    provides: discord_names sqlite cache triad and Wave-0 app tests
  - phase: 04-settings-migration-name-resolution
    plan: 02
    provides: periodic bot-side Discord channel and role snapshots
provides:
  - Owner settings page rendered inside the shared dashboard shell
  - String-keyed sqlite name-cache resolution with freshness handling
  - Resolved channel previews, color-barred role chips, and one cold-cache banner
affects: [settings-dashboard, name-resolution, phase-04-verification]

tech-stack:
  added: []
  patterns: [off-event-loop sqlite reads, server-seeded Alpine lookup maps, owner-known shell roles]

key-files:
  created:
    - .planning/phases/04-settings-migration-name-resolution/04-03-SUMMARY.md
  modified:
    - app/main.py
    - app/templates/settings.html
    - app/static/dashboard.css

key-decisions:
  - "The owner-only route supplies a hardcoded owner roles dict instead of performing a second live role lookup."
  - "Discord name-cache IDs remain strings from sqlite through Jinja/Alpine serialization."
  - "Cold or stale caches show one section banner and suppress per-field unavailable markers."

patterns-established:
  - "Settings shell context matches other dashboard routes: roles, active_section, asset_v, and bot_online."
  - "Discord entity names are display-only sqlite data; raw IDs remain the editable and persisted values."

requirements-completed: [SETT-01, SETT-02]
duration: 20min
completed: 2026-07-22
---

# Phase 4 Plan 03: In-Shell Settings and Name Resolution Summary

**The owner settings panel now uses the dashboard shell and resolves cached Discord channels and roles without importing Discord into the app.**

## Accomplishments

- Added defensive app-side `discord_names` initialization and an off-event-loop `_read_name_cache()` that preserves TEXT snowflake IDs and computes cache freshness.
- Supplied the owner-known sidebar roles, active Settings section, dashboard asset version, bot status, name map, and freshness flag to `/admin/settings` without changing its owner gate or POST route.
- Migrated `settings.html` to `_dashboard_base.html`, retained one save action and every field/edit flow, and added live resolved channel previews, color-barred role chips, raw IDs, and cold-cache messaging.
- Added settings styles using the existing dashboard tokens, including warning and per-role left accent bars.

## Task Commits

No commits were created, per the explicit instruction to leave changes for review.

## Files Created/Modified

- `app/main.py` - Reads the shared name cache, computes freshness, initializes its table defensively, and supplies complete shell context.
- `app/templates/settings.html` - Renders the existing settings workflow inside the dashboard shell with readable channel and role metadata.
- `app/static/dashboard.css` - Styles settings fields, resolved IDs, role chips, cache banner, validation state, and toast.
- `.planning/phases/04-settings-migration-name-resolution/04-03-SUMMARY.md` - Records plan outcome and verification evidence.

## Decisions Made

- Kept `require_owner`, `save_settings`, the `/admin/settings` paths, and the settings-specific 403 handler byte-unchanged.
- Used a hardcoded owner-tier roles mapping because the GET route has already proved the owner identity; no live Discord role resolution was added.
- Kept arbitrary role colors confined to a 3px chip border, never a chip fill or text color.

## Deviations from Plan

None in product behavior. The target files already contained an uncommitted implementation when this run began; the full acceptance and regression audit found no additional production patch necessary. The user instruction not to commit overrides the GSD commit steps.

## Issues Encountered

- The sandbox denied pytest access to the default user-profile temp and cache directories. Verification used unique workspace-local `--basetemp` directories and disabled pytest's cache provider; the requested conda interpreter and test targets were unchanged.

## Verification

- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py -x`: **16 passed** with workspace-local pytest temp/cache options.
- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_dashboard.py -k settings -x`: **2 passed, 5 deselected** with workspace-local pytest temp/cache options.
- Full suite: **685 passed**, with three dependency deprecation warnings.
- `git diff --check`: **passed**.
- App credential-boundary scan: **no `import discord`, `fetch_channel`, or `fetch_guild` matches under `app/`**.

## User Setup Required

None. No dependencies, credentials, intents, scopes, or environment values changed.

## Next Phase Readiness

- Phase 4 settings migration and name resolution are ready for review and phase-level verification.
- No known blockers remain.

## Self-Check: PASSED

Both task acceptance-criteria sets, both requested targeted suites, the full regression suite, and the app credential-boundary scan pass.

---
*Phase: 04-settings-migration-name-resolution*
*Completed: 2026-07-22*
