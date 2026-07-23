---
phase: 06-reminders-crud
plan: 03
subsystem: discord-reminders
tags: [discord, biweekly, optimistic-concurrency, scheduler, tdd]

requires:
  - 06-01
  - 06-02
provides:
  - Biweekly reminder creation and editing through Discord commands
  - Past-anchor biweekly scheduling through next_biweekly_fire
  - Version-guarded scheduler write-back with stale-row preservation
  - Paused-row and per-reminder isolation regression coverage
affects: [06-04, 06-05]

tech-stack:
  added: []
  patterns:
    - Cog-local schedule adapter for frequencies not dispatched by the shared core helper
    - Optimistic scheduler writes using the version read at tick start

key-files:
  created: []
  modified:
    - cogs/reminders.py
    - tests/test_reminders_cog.py

key-decisions:
  - "Biweekly anchors are validated for syntax only; past dates remain valid cadence anchors."
  - "A stale scheduler write logs at info level and is not retried, preserving the newer row."
  - "Because the user restricted implementation changes to the cog and its tests, biweekly compute_next dispatch is adapted locally while every other frequency delegates to core.reminder_schedule."

patterns-established:
  - "Both recurring and one-off scheduler write-backs carry expected_version from the due-row snapshot."
  - "Advance-after-send and the per-row try/except remain the scheduler's lifecycle and crash-isolation boundaries."

requirements-completed: [REM-01, REM-02, REM-03]

duration: 5 min
completed: 2026-07-23
---

# Phase 6 Plan 3: Discord Reminder Parity and Scheduler Guard Summary

**Discord biweekly parity with past anchors plus optimistic, non-clobbering scheduler write-back**

## Performance

- **Duration:** 5 min from the first RED run
- **Started:** 2026-07-23T14:20:49Z
- **Completed:** 2026-07-23T14:25:53Z
- **Tasks:** 2
- **Files modified:** 3 including this summary

## Accomplishments

- Added `biweekly` to both `/recordatorio crear` and `/recordatorio editar`, including persistence, transitions to and from biweekly, and schedule dispatch.
- Accepted historical biweekly anchors and computed their next occurrence with `next_biweekly_fire` without applying one-off past-date rejection.
- Passed each due row's `version` into recurring and one-off scheduler write-backs.
- Logged and continued after stale write rejection while preserving advance-after-send and per-row crash isolation.
- Added paused-row regression coverage at the `due_reminders` boundary.

## Task Commits

Each task was committed atomically:

1. **Task 1: Biweekly Discord command parity** - `ba43568` (feat)
2. **Task 2: Version-guarded scheduler write-back** - `fb11613` (fix)

## Files Created/Modified

- `cogs/reminders.py` - Biweekly choices, validation/dispatch, and guarded scheduler writes.
- `tests/test_reminders_cog.py` - Strict RED/GREEN coverage for biweekly commands and scheduler concurrency.
- `.planning/phases/06-reminders-crud/06-03-SUMMARY.md` - Execution and verification record.

## Decisions Made

- Biweekly uses the existing `fecha` input as `run_date` anchor plus the existing `hora` input.
- Biweekly date validation calls `parse_date` but deliberately never compares the resulting instant with now.
- False mutation outcomes are treated as lost optimistic races: the scheduler logs once, does not raise, does not retry, and proceeds to the next row.

## Deviations from Plan

- `core.reminder_schedule.compute_next` did not yet dispatch `biweekly`. The plan allowed changing it if needed, but the user's stricter file boundary allowed only `cogs/reminders.py` and `tests/test_reminders_cog.py`. A cog-local `compute_next` adapter therefore handles `biweekly` and delegates all other frequencies to the core helper.

## Issues Encountered

None.

## User Setup Required

None - no dependencies or external configuration were added.

## Next Phase Readiness

- Discord and panel scheduling surfaces now expose the same biweekly cadence.
- Scheduler write-back safely cooperates with concurrent panel edits through Plan 06-02's DB guards.
- Ready for Plan 06-04; no blockers identified.

## Verification

- Task 1 RED: `4 failed, 1 passed` in the `biweekly` filter.
- Task 1 GREEN: `5 passed, 71 deselected, 1 warning`.
- Task 2 RED: `4 failed, 75 passed, 1 warning`.
- Task 2 GREEN: `79 passed, 1 warning`.
- Full suite: `731 passed, 4 warnings`.
- Structural checks: two `biweekly` command choices, two `expected_version=r["version"]` write-backs, and the per-row `except Exception` remain present.

## Self-Check: PASSED

All task acceptance criteria, plan success criteria, and the full suite passed with zero regressions.

---
*Phase: 06-reminders-crud*
*Completed: 2026-07-23*
