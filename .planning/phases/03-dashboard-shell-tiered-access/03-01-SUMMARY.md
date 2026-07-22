---
phase: 03-dashboard-shell-tiered-access
plan: 01
subsystem: testing
tags: [pytest, fastapi-testclient, dependency-overrides, tdd-wave-0]

# Dependency graph
requires:
  - phase: 02-owner-settings-panel
    provides: "app/deps.py::require_owner, core/settings.py's role_list schema/validator, tests/test_app_settings.py's client fixture pattern"
provides:
  - "tests/test_app_dashboard.py — 6 named RED tests pinning SHELL-01/02, ACCESS-01..04 for Plans 05/07"
  - "8 new manager_roles/editor_roles schema-case tests in tests/test_settings.py pinning D-05/D-06 for Plan 02"
affects: [03-02, 03-05, 03-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-first Wave 0 test scaffolding: local (in-body) imports of not-yet-existing symbols so pytest --collect-only succeeds while pytest execution fails for the right reason (ImportError/AttributeError/KeyError, not a collection error)"

key-files:
  created: [tests/test_app_dashboard.py]
  modified: [tests/test_settings.py]

key-decisions:
  - "require_manager/require_owner imported locally inside each test body (not at module top) so the file collects before Plan 05 lands require_manager, per the plan's explicit constraint"
  - "core.db heartbeat/sync-status/activity-log helper calls (init_heartbeat, set_heartbeat, etc.) also written as local in-body calls in test_overview_shows_status_tiles since Plan 07 has not created them yet — they raise AttributeError today, which is the correct Wave 0 signal"
  - "Skipped asserting a length-based role-id rejection in the manager_roles/editor_roles invalid-id tests: core/settings.py::_validate_role_id_list is deliberately lenient on ID width (comment at core/settings.py:76-78), so only non-digit values are asserted as rejected — an assertion on ID length would be a false claim about the validator's actual (and intentional) behavior"

patterns-established: []

requirements-completed: [SHELL-01, SHELL-02, ACCESS-01, ACCESS-02, ACCESS-03, ACCESS-04]

# Metrics
duration: 25min
completed: 2026-07-22
---

# Phase 3 Plan 1: Wave-0 RED Test Scaffolding Summary

**Six named `tests/test_app_dashboard.py` behavioral tests plus eight `manager_roles`/`editor_roles` schema-case tests in `tests/test_settings.py`, all collecting cleanly and RED for the correct reason (missing `require_manager`, missing dashboard routes, missing `core.db` status helpers, and missing `_SCHEMA` entries) ahead of Plans 02/05/07.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-22T01:10:21Z
- **Completed:** 2026-07-22T01:17:57Z
- **Tasks:** 2 completed
- **Files modified:** 2 (1 created, 1 extended)

## Accomplishments
- `tests/test_app_dashboard.py` created with the exact six named tests from the RESEARCH.md
  Phase Requirements → Test Map (SHELL-01, SHELL-02, ACCESS-01..04), modeled on
  `tests/test_app_settings.py`'s `client` fixture (dummy OAuth/session config + tmp-path
  sqlite DB + `settings.seed_defaults()`), each test scoping and clearing its own
  `app.dependency_overrides` entries in a `finally` block.
- `tests/test_settings.py` extended with 8 tests covering `manager_roles`/`editor_roles`:
  seeded-default inclusion of the Manager role (`1453560115423875205`) and the moderator
  role (`config.ROLE_MODERATOR_ID`), set/get round-trip, invalid-role-id rejection, and the
  no-fallback-to-`GALLERY_STAFF_ROLE_IDS` guarantee (D-06/Pitfall 3) for both keys.
- Verified the whole suite: 659 tests collect with zero collection errors; `pytest -q`
  shows exactly the 14 new tests RED (6 dashboard + 8 settings) and the pre-existing 645
  tests still green — confirming the new scaffolding didn't disturb anything else.

## Task Commits

Each task was committed atomically:

1. **Task 1: Scaffold tests/test_app_dashboard.py with the six Phase-3 behavioral tests (RED)** - `76b0687` (test)
2. **Task 2: Extend tests/test_settings.py with manager_roles / editor_roles schema cases** - `f490808` (test)

**Plan metadata:** (this commit) `docs(03-01): complete Wave-0 RED test scaffolding plan`

_Note: this is a Wave-0 test-scaffolding plan — no TDD RED/GREEN/REFACTOR cycle applies here;
both commits are `test(...)` commits by design, and staying RED is the correct, expected
end state for this plan._

## Files Created/Modified
- `tests/test_app_dashboard.py` - new file: 6 named tests (`test_sidebar_renders_seven_sections`,
  `test_overview_shows_status_tiles`, `test_owner_full_access`,
  `test_manager_operational_access_settings_403`, `test_editor_only_locked_out_of_dashboard`,
  `test_manager_cannot_edit_mapping`) plus a `client` fixture mirroring
  `tests/test_app_settings.py`.
- `tests/test_settings.py` - extended with 8 tests for the `manager_roles`/`editor_roles`
  tier-mapping schema keys (seed inclusion, round-trip, invalid-id rejection, no-fallback
  guarantee), inserted just before the existing `CONC-01` WAL section.

## Decisions Made
- Local (in-test-body) imports for `require_manager`/`require_owner` in
  `tests/test_app_dashboard.py`, and for the not-yet-existing `core.db` heartbeat/sync-status/
  activity-log helpers in `test_overview_shows_status_tiles` — required by the plan so
  `pytest --collect-only` succeeds today while the test bodies still fail for the right reason
  once executed.
- The "invalid role id (non-digit or wrong length)" acceptance wording in the plan does not
  match `core/settings.py::_validate_role_id_list`'s actual (intentionally lenient-on-length)
  behavior — only non-digit values are asserted as rejected, so these tests will be
  genuinely correct once Plan 02 wires the schema, rather than encoding a false constraint
  that Plan 02 would then have to either violate or over-implement.

## Deviations from Plan

None - plan executed exactly as written. The "invalid role id ... or wrong length" phrasing
note above is a documentation clarification of test intent, not a deviation from any task
action, verification, or acceptance criterion in the plan (both `grep -c` acceptance checks
and the six-name/eight-case content checks are satisfied exactly as specified).

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 02 (settings schema) has a concrete, already-failing regression target: the 8
  `manager_roles`/`editor_roles` tests in `tests/test_settings.py` will flip GREEN once the
  two `_Setting` entries land in `core/settings.py::_SCHEMA`.
- Plan 05 (tier dependency) and Plan 07 (dashboard routes + `core.db` status helpers) have
  a concrete, already-failing regression target: the 6 tests in `tests/test_app_dashboard.py`
  will flip GREEN incrementally as `require_manager`, the six module routes, `/api/overview/status`,
  and `core.db`'s `init_heartbeat`/`set_heartbeat`/`init_jinxxy_sync_status`/
  `set_jinxxy_sync_status`/`init_activity_log`/`log_activity` land.
- No blockers. Full suite (`pytest -q`) is green except for exactly the 14 intentionally-RED
  tests documented above (645 passed, 14 failed, 659 collected, 0 collection errors).

---
*Phase: 03-dashboard-shell-tiered-access*
*Completed: 2026-07-22*
