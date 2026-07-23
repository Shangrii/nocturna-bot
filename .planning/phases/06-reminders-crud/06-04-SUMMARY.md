---
phase: 06-reminders-crud
plan: 04
subsystem: api
tags: [fastapi, reminders, crud, optimistic-concurrency, tdd]

requires:
  - phase: 06-reminders-crud
    provides: Pure schedule math from Plan 01 and versioned reminder persistence from Plan 02
provides:
  - Manager-gated reminder CRUD, pause/resume, and live-preview routes
  - Server-owned next-fire computation for every create, edit, resume, and preview
  - Distinct 409 conflict responses for stale optimistic writes
  - Dedicated app/routers package seam with reminders mounted from app/main.py
affects: [06-05, 06-06]

tech-stack:
  added: []
  patterns:
    - FastAPI APIRouter modules mounted from the application entry point
    - Shared validate-then-write schedule validation for CRUD and preview
    - Hidden-version echo used only as an optimistic WHERE predicate

key-files:
  created:
    - app/routers/reminders.py
    - tests/test_app_reminders.py
  modified:
    - app/main.py

key-decisions:
  - "The JSON schedule contract uses time as HH:MM plus frequency-specific weekday, day_of_month, or run_date fields."
  - "Client next_fire_utc values are ignored; all write and preview paths derive the cursor from validated schedule fields."
  - "Overdue one-offs resume at now, while recurring reminders always roll to their next future occurrence."

patterns-established:
  - "Every reminders route declares Depends(require_manager) in the router itself."
  - "False version-guarded mutations return a bilingual reload-specific 409, never a validation 422."

requirements-completed: [REM-01, REM-02, REM-03]

duration: 12 min
completed: 2026-07-23
---

# Phase 6 Plan 4: Reminders Backend Summary

**Manager-gated FastAPI reminder CRUD with server-computed schedules, clean-forward resume, live preview, and optimistic 409 conflict handling**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-23T14:37:50Z
- **Completed:** 2026-07-23T14:49:29Z
- **Tasks:** 2
- **Files modified:** 4 including this summary

## Accomplishments

- Added a dedicated `app/routers/reminders.py` with seven Manager-gated routes for the page, create, edit, delete, pause, resume, and preview.
- Centralized schedule validation and server-side next-fire computation across weekly, biweekly, monthly, and one-off reminders.
- Ignored client-provided `next_fire_utc` values and preserved paused state during ordinary edits.
- Added version-guarded edit/delete/pause/resume behavior with a distinct bilingual 409 reload response.
- Implemented clean-forward recurring resume and immediate, once-only scheduling for overdue resumed one-offs.
- Replaced the inline `/reminders` stub in `app/main.py` with `app.include_router(...)`.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED backend route contracts** - `f16dd2b` (test)
2. **Task 2: Manager reminders router and application mount** - `1cebdbc` (feat)

## Files Created/Modified

- `app/routers/reminders.py` - Manager-gated CRUD, pause/resume, page-data, and preview endpoints.
- `app/main.py` - Router mount, clean-install reminders initialization, and removal of the inline stub route.
- `tests/test_app_reminders.py` - Real-SQLite RED/GREEN coverage for authorization, CRUD, validation, concurrency, resume, and preview.
- `.planning/phases/06-reminders-crud/06-04-SUMMARY.md` - Execution and verification record.

## Decisions Made

- Used one shared schedule validator for create/edit/preview so the preview and persisted cursor cannot drift.
- Kept `paused` outside the edit field set; editing a paused reminder therefore remains paused.
- Declared `/reminders/preview` before the dynamic `/{reminder_id}` route to prevent path capture.
- Kept the router independent of `app.main` to avoid circular imports; it owns its Jinja environment rooted at the same templates directory.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Initialize reminders from the FastAPI lifespan**
- **Found during:** Task 2 full-suite verification
- **Issue:** Dashboard access tests used a clean database where the bot had not created the reminders table, causing `GET /reminders` to raise `sqlite3.OperationalError`.
- **Fix:** Added idempotent `db.init_reminders()` to the existing application lifespan initialization block.
- **Files modified:** `app/main.py`
- **Verification:** Dashboard plus reminders suites passed `26 passed`; full suite passed `750 passed`.
- **Committed in:** `1cebdbc`

**2. [Rule 3 - Blocking] Preserve a renderable GET between backend and frontend waves**
- **Found during:** Task 2 full-suite verification
- **Issue:** Plan 05 owns `reminders.html`, so the newly mounted backend route could not render that template yet while existing dashboard tests require every operational module GET to return 200.
- **Fix:** The router selects `reminders.html` when present and otherwise renders the existing module stub template with reminders metadata. Plan 05 activates the real page automatically by creating the template.
- **Files modified:** `app/routers/reminders.py`
- **Verification:** Both owner and Manager dashboard access tests pass, and all reminders backend tests remain green.
- **Committed in:** `1cebdbc`

---

**Total deviations:** 2 auto-fixed (1 missing critical, 1 blocking).
**Impact on plan:** Both changes are idempotent, confined to the authorized files, and preserve the intended Plan 05 handoff without altering route or API contracts.

## Issues Encountered

- FastAPI 0.139 stores mounted routers as deferred `_IncludedRouter` objects rather than cloning their `APIRoute` entries into `app.routes`. The structural gate test was adjusted to inspect the source `APIRouter`, while request tests independently prove the router is mounted.

## User Setup Required

None - no dependencies or external configuration were added.

## Next Phase Readiness

- Plan 06-05 can create `app/templates/reminders.html`; the GET route will select it automatically.
- The frontend has stable JSON contracts for CRUD/pause/resume and `/reminders/preview`.
- No blockers identified.

## Verification

- RED: `18 failed, 1 passed` from missing routes/stub behavior.
- Target GREEN: `19 passed, 3 warnings`.
- Cross-module regression check after clean-install fix: `26 passed, 3 warnings`.
- Full suite: `750 passed, 4 warnings`.
- Structural: seven `Depends(require_manager)` occurrences, zero request-body reads of `next_fire_utc`, four guarded mutations, and no inline reminders route in `app/main.py`.

## Self-Check: PASSED

All task acceptance criteria, plan success criteria, Manager gate requirements, validate-then-write guarantees, stale-edit 409 behavior, and the full suite passed.

---
*Phase: 06-reminders-crud*
*Completed: 2026-07-23*
