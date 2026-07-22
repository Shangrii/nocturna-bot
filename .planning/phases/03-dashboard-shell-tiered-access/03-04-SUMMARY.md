---
phase: 03-dashboard-shell-tiered-access
plan: 04
subsystem: bot-side activity instrumentation
tags: [discord.py, sqlite, activity-log, dashboard-shell]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access (plan 03)
    provides: "core/db.py::set_jinxxy_sync_status, log_activity, get_recent_activity + activity_log/jinxxy_sync_status tables"
provides:
  - "cogs/jinxxy.py::_run_sync writes jinxxy_sync_status AND a jinxxy_sync activity_log row on every run (success or failure)"
  - "cogs/gallery.py logs gallery_published / gallery_removed on successful publish/remove"
  - "cogs/reviews.py logs review_published / review_removed on successful publish/remove"
  - "cogs/meeting.py logs meeting_posted on successful forum thread creation"
affects: [03-05, 03-06, 03-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "bot-writes-sqlite-on-event idiom (cogs/presence.py::_store) reused for D-11 activity_log hooks: every write wrapped in try/except Exception: log.exception(...), never aborts the underlying Discord action"
    - "single instrumentation point wrapping a whole orchestration method's try/except (cogs/jinxxy.py::_run_sync) so both success and failure paths record status/activity, then re-raise unchanged"

key-files:
  created: []
  modified:
    - cogs/jinxxy.py
    - cogs/gallery.py
    - cogs/reviews.py
    - cogs/meeting.py

key-decisions:
  - "cogs/jinxxy.py::_run_sync wraps its entire body in try/except rather than only instrumenting the tail, because _run_sync raises (never returns an error dict) on transient API failures — this is the only way to record ok=False + error on a failed run while still funneling both _poll and /tienda sync through one instrumentation point (D-10/D-11)"
  - "Extracted a _record_sync_status(ok, product_count, error) helper on JinxxyCog so both the success and failure branches share one write of set_jinxxy_sync_status + log_activity, wrapped in the same try/except, per the plan's explicit D-11 requirement"
  - "meeting.py instruments only the forum.create_thread success path (not the text-channel fallback) — matches the plan's explicit read_first pointer to line ~278; the fallback send is a degraded-mode path, not the primary 'meeting posted' event"

requirements-completed: [SHELL-02]

# Metrics
duration: 8min
completed: 2026-07-21
---

# Phase 3 Plan 4: Bot-side Activity Instrumentation Summary

Instrumented `cogs/jinxxy.py::_run_sync` to record every sync run's outcome (success or
failure) to both `jinxxy_sync_status` (D-10 tile) and `activity_log` (D-11 "sync ran"
row), and added `activity_log` hooks to `cogs/gallery.py`, `cogs/reviews.py`, and
`cogs/meeting.py` on their notable publish/remove/post events — all writes reuse the
Plan 03 `core/db.py` helpers and are wrapped in the `cogs/presence.py::_store`
try/except idiom so a logging failure never aborts the underlying Discord action.

## Performance

- **Duration:** ~8 min
- **Started:** 2026-07-21T19:23:50-06:00
- **Completed:** 2026-07-21T19:31:33-06:00
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Every Jinxxy sync run (scheduled poll or manual `/tienda sync`), success or failure,
  now leaves a `jinxxy_sync_status` row AND a `jinxxy_sync` `activity_log` row.
- Gallery photo publish/remove, review publish/remove, and meeting forum-post events
  each append one `activity_log` row for the Overview "recent activity" list.
- The full D-11 activity event set for this phase is now instrumented: `jinxxy_sync`,
  `gallery_published`, `gallery_removed`, `review_published`, `review_removed`,
  `meeting_posted`. "Reminder fired" remains deferred to Phase 6 (no fire path exists
  yet) — `cogs/reminders.py` is untouched.

## Task Commits

Each task was committed atomically:

1. **Task 1: Record sync status + 'sync ran' activity in cogs/jinxxy.py::_run_sync** - `4676b74` (feat)
2. **Task 2: Add activity_log hooks to gallery, reviews, and meeting cogs** - `1a2e693` (feat)

## Files Created/Modified
- `cogs/jinxxy.py` - Added `_record_sync_status` helper; wrapped `_run_sync`'s body in
  try/except so both success and failure record `jinxxy_sync_status` + a `jinxxy_sync`
  activity row, then re-raise unchanged on failure.
- `cogs/gallery.py` - Added `log_activity("gallery_published", ...)` after a successful
  `publish_message` commit and `log_activity("gallery_removed", ...)` after a successful
  `remove_message` commit.
- `cogs/reviews.py` - Added `from core import db`; `log_activity("review_published", ...)`
  after a successful `publish_review` commit and `log_activity("review_removed", ...)`
  after a successful `remove_review` commit.
- `cogs/meeting.py` - Added `from core import db`; `log_activity("meeting_posted", ...)`
  after a successful `forum.create_thread` call in `_publish`.

## Decisions Made
- `_run_sync` is wrapped in a single try/except around its entire existing body (steps
  1-7 unchanged internally) rather than only instrumenting the tail, because several
  steps can raise (`jinxxy_api.get_me`/`list_all_products` on outage, `github_publish`
  transport errors) and the plan requires the failure path to ALSO record
  `ok=False` + an error string — this was the only way to satisfy that while keeping
  `_run_sync`'s ordering, logic, and return value byte-identical for both `_poll` and
  `/tienda sync`.
- A `_record_sync_status` helper centralizes the D-10 (`set_jinxxy_sync_status`) and
  D-11 (`log_activity("jinxxy_sync", ...)`) writes into one call, wrapped in one
  try/except, called from both the success and failure branches — satisfies the locked
  D-11 requirement that both writes happen "at the same instrumentation point, wrapped
  in the same try/except."
- `product_count` on success is `len(result["products"])` (the full reconciled catalog
  count); on failure it is `None` (no live count could be established).

## Deviations from Plan

None - plan executed exactly as written. `_run_sync`'s internal restructuring (wrapping
existing steps 1-7 in a single try/except) is additive instrumentation only — no
sync logic, ordering, or return value was changed, and every existing docstring comment
was preserved verbatim in place.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. All instrumentation reuses the
existing shared-sqlite `core/db.py` helpers from Plan 03; no new tables, migrations, or
environment variables.

## Next Phase Readiness

The bot-side data plumbing for SHELL-02's Overview "last Jinxxy sync" tile and "recent
activity" list is now fully populated for every module except reminders (deferred to
Phase 6). Ready for the Overview page (Plan 03-07) to read `get_jinxxy_sync_status()`
and `get_recent_activity()` and render real data instead of stubs.

---
*Phase: 03-dashboard-shell-tiered-access*
*Completed: 2026-07-21*
