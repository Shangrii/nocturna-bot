---
phase: 04-settings-migration-name-resolution
plan: 01
subsystem: database
tags: [sqlite, discord, snowflakes, pytest, wave-0]

requires:
  - phase: 03-dashboard-shell-tiered-access
    provides: Dashboard shell, owner-only settings route, and Overview sqlite triad patterns
provides:
  - discord_names shared-sqlite contract with TEXT snowflake IDs
  - Atomic full-snapshot replacement that removes deleted Discord entities
  - Wave-0 RED app scaffolds for shell migration and name resolution
affects: [04-02-bot-name-cache, 04-03-app-settings-migration]

tech-stack:
  added: []
  patterns: [dual-process sqlite cache triad, atomic DELETE-plus-executemany snapshot]

key-files:
  created:
    - tests/test_discord_names.py
  modified:
    - core/db.py
    - tests/test_app_settings.py

key-decisions:
  - "Discord snowflake IDs are coerced to str and stored in a TEXT primary-key column."
  - "Cache refreshes replace the complete snapshot in one sqlite transaction."

patterns-established:
  - "discord_names triad: init defensively, replace from the bot, read from the app."
  - "Forward-referenced Wave-0 app symbols are imported inside test bodies to keep collection clean."

requirements-completed: [SETT-01, SETT-02]

duration: 15min
completed: 2026-07-22
---

# Phase 4 Plan 01: Discord Names Contract and Wave-0 Scaffolds Summary

**A TEXT-safe Discord name cache contract with atomic snapshot replacement and collection-safe RED app migration tests**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-22T11:37:00Z
- **Completed:** 2026-07-22T11:52:11Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added `init_discord_names`, `replace_discord_names`, and `get_discord_names` using the established `core/db.py` sqlite triad idiom.
- Covered idempotent initialization, TEXT snowflake round-trip, deleted-row removal, and an empty-cache `[]` result with four green tests.
- Added six Plan-04-03-facing tests for shell rendering, cached name display, cold-cache copy, precision-safe Alpine data, and cache-reader freshness.
- Preserved the existing owner settings save behavior and its mixed-valid/invalid and snowflake-precision regressions.

## Task Commits

No commits were created, per the explicit run instruction to leave all changes staged/unstaged for review.

## Files Created/Modified

- `core/db.py` - Adds the Discord names sqlite helper triad.
- `tests/test_discord_names.py` - Defines and verifies the database-layer contract.
- `tests/test_app_settings.py` - Adds the collection-safe Wave-0 RED app scaffolds.
- `.planning/phases/04-settings-migration-name-resolution/04-01-SUMMARY.md` - Records plan outcome and verification evidence.

## Decisions Made

- Stored every snowflake as TEXT and coerced IDs with `str()` at the write boundary so browser serialization cannot round values above `2**53`.
- Used one timestamp for every row in a snapshot and one transaction for `DELETE` followed by `executemany`.
- Kept `_read_name_cache` imports local to their tests because the helper intentionally does not exist until Plan 04-03.

## Deviations from Plan

None - plan executed exactly as written. The user instruction not to commit overrides the GSD commit steps.

## Issues Encountered

- The sandbox denied pytest access to the user-profile temp/cache directories. Verification used workspace-local `TEMP`/`TMP` and disabled pytest's cache provider; the requested conda interpreter and test targets were unchanged.

## Verification

- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_discord_names.py -x`: **4 passed**.
- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py --collect-only -q`: **16 collected**, no import/collection errors.
- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py -k "two_pass or mixed_valid or precision" -x`: **2 passed**, covering the locked mixed-valid/invalid save and snowflake-precision regressions.
- Full app-settings classification run: **10 passed, 6 intentionally failed** pending Plan 04-03.
- Required `tests/test_app_settings.py -x` run: 10 pre-existing tests passed, then pytest stopped at the intentional `test_settings_page_renders_in_shell` RED assertion.

## User Setup Required

None - no external service configuration or dependency installation is required.

## Next Phase Readiness

- Plan 04-02 can write bot-side guild snapshots through `replace_discord_names`.
- Plan 04-03 can implement `_read_name_cache` and the shell/name-resolution UI against the locked RED tests.

## Self-Check: PASSED

The database acceptance criteria are green, the app test module collects cleanly, all pre-existing tests in it remain green, and the six planned Wave-0 assertions are RED only for functionality assigned to Plan 04-03.

---
*Phase: 04-settings-migration-name-resolution*
*Completed: 2026-07-22*
