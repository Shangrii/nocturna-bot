---
phase: 06-reminders-crud
plan: 01
subsystem: reminders
tags: [python, zoneinfo, scheduling, tdd, discord]

requires: []
provides:
  - Discord-free reminder schedule math importable by bot and FastAPI processes
  - Biweekly anchor cadence with DST-correct local wall time
  - Symmetric imminent-fire threshold helper
affects: [06-02, 06-03, 06-04, 06-05]

tech-stack:
  added: []
  patterns:
    - Pure framework-agnostic schedule module under core/
    - Compatibility re-export shim from the Discord cog

key-files:
  created:
    - core/reminder_schedule.py
    - tests/test_reminder_schedule.py
  modified:
    - cogs/reminders.py

key-decisions:
  - "Past biweekly anchors are valid cadence markers and roll forward using local-date 14-day parity."
  - "The cog re-exports every extracted helper so existing call sites remain compatible."

patterns-established:
  - "Shared schedule logic belongs in core/reminder_schedule.py and must not import discord."
  - "Framework adapters import and re-export pure helpers instead of duplicating schedule math."

requirements-completed: [REM-01, REM-03]

duration: 12 min
completed: 2026-07-23
---

# Phase 6 Plan 1: Reminder Schedule Extraction Summary

**Discord-free schedule math with anchored biweekly recurrence, DST-stable wall time, imminent-fire detection, and a compatibility-preserving cog shim**

## Performance

- **Duration:** 12 min from the first task commit
- **Started:** 2026-07-23T13:50:18Z
- **Completed:** 2026-07-23T14:02:00Z
- **Tasks:** 2
- **Files modified:** 4 including this summary

## Accomplishments

- Extracted the existing reminder math and validators verbatim into a pure module without a Discord dependency.
- Added `next_biweekly_fire` with past-anchor parity and DST-correct wall-clock behavior.
- Added `is_imminent` with an inclusive, symmetric 90-second default threshold.
- Preserved all cog call sites through explicit re-exports and added the locked biweekly summary format.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED test scaffold for biweekly + is_imminent** - `a1970c8` (test)
2. **Task 2: Pure schedule module + re-export shim** - `8fa95c3` (feat)

## Files Created/Modified

- `core/reminder_schedule.py` - Pure schedule math, validators, biweekly cadence, and imminent-fire helper.
- `cogs/reminders.py` - Imports and re-exports the pure helpers while retaining Discord-only behavior.
- `tests/test_reminder_schedule.py` - RED-first coverage for biweekly parity/DST behavior and imminent thresholds.
- `.planning/phases/06-reminders-crud/06-01-SUMMARY.md` - Execution record and verification evidence.

## Decisions Made

- Reused `run_date` as the biweekly anchor input, matching the plan and downstream phase design.
- Kept all existing helper source text verbatim; only `schedule_summary` gained the required biweekly branch.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The literal Task 1 verification pipeline uses Bash `&&`/`||`, which Windows PowerShell 5 rejects before pytest starts. The same pytest command was run with an equivalent PowerShell result check and produced the expected `ModuleNotFoundError`.
- The first sandboxed Task 2 verify could not create pytest's `%TEMP%` directory. Re-running the exact command outside the sandbox passed all 78 targeted tests.

## User Setup Required

None - no external service configuration or dependencies were added.

## Next Phase Readiness

- The pure schedule seam is ready for app-side validation/preview and Discord biweekly parity.
- Ready for `06-02-PLAN.md`; no blockers identified.

## Verification

- Targeted: `78 passed, 1 warning`
- Full suite: `717 passed, 4 warnings`
- Import boundary: `core.reminder_schedule` imports without loading `discord`
- Verbatim source comparison: all moved unchanged helpers and `_WEEKDAYS_ES` matched `HEAD` textually

## Self-Check: PASSED

All task acceptance criteria, plan success criteria, targeted tests, and the full suite passed.

---
*Phase: 06-reminders-crud*
*Completed: 2026-07-23*
