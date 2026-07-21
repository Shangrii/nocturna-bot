---
phase: 02-owner-settings-panel
plan: 05
subsystem: settings-store
tags: [sqlite, fastapi, snowflake-precision, panel]

# Dependency graph
requires:
  - phase: 02-owner-settings-panel
    provides: core/settings.py all_for_ui()/get()/set() panel-facing API (02-01..02-04)
provides:
  - _get_raw() helper in core/settings.py — fallback-bypassing stored-or-default reader
  - all_for_ui() now string-serializes snowflake/role_list values and sources them from
    the raw store instead of the fallback-resolving get()
  - Unit + integration regression coverage proving the GET-payload -> POST-unchanged
    round trip preserves snowflake precision and the CONF-03 staff-role cascade
affects: [owner-settings-panel verification, any future settings.py panel-facing change]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Raw vs. resolved reader split: get() resolves the CONF-03 fallback for bot read-time
      use; _get_raw() exposes the unresolved stored value for the panel's editable payload —
      keeps the two call sites' semantics from leaking into each other."
    - "String-serialize snowflake/role_list at the API boundary (all_for_ui()) rather than in
      the template — Jinja tojson only needs to quote what it's given; existing string-accepting
      validators absorb the round trip with zero validator changes."

key-files:
  created: []
  modified:
    - core/settings.py
    - tests/test_settings.py
    - tests/test_app_settings.py

key-decisions:
  - "_get_raw() duplicates get()'s SELECT+json.loads+exception-fallback logic rather than
    refactoring get() to take a skip-fallback flag — keeps get() byte-identical (required by
    the plan's success criteria) and avoids adding a parameter to a widely-used public function."
  - "Serialization happens in all_for_ui(), not settings.html — the plan's <interfaces> block
    confirmed the template's x-model text inputs already bind strings, so no template edit
    was needed once the JSON payload carries quoted strings."

requirements-completed: [PANEL-02, PANEL-03]

# Metrics
duration: 25min
completed: 2026-07-21
---

# Phase 2 Plan 05: Raw-value + string serialization in all_for_ui() Summary

**Fixed the panel's snowflake-precision loss and CONF-03 fallback-baking bugs by adding `_get_raw()` (a fallback-bypassing reader) and string-serializing snowflake/role_list values in `core/settings.py::all_for_ui()`, leaving `get()` byte-identical.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-21T00:00:00Z (approx, worktree agent)
- **Completed:** 2026-07-21
- **Tasks:** 2
- **Files modified:** 3 (`core/settings.py`, `tests/test_settings.py`, `tests/test_app_settings.py`)

## Accomplishments

- `all_for_ui()`'s editable payload no longer emits a bare `int`/`list[int]` for Discord
  snowflake / staff-role values — `tojson` now emits quoted strings, so the browser's JS engine
  can never round a 17-20 digit Discord ID to a lossy IEEE-754 double (CR-01 / SC2 / PANEL-02).
- `all_for_ui()`'s editable payload now shows the RAW stored value for staff-role lists
  (bypassing the CONF-03 empty-list fallback), so posting the whole form unchanged no longer
  bakes a resolved gallery fallback into REVIEWS/REMINDERS/JINXXY_STAFF_ROLE_IDS (CR-02 / SC3 /
  PANEL-03).
- `core/settings.py::get()` is untouched — the bot's read-time CONF-03 cascade is byte-identical
  to before this plan.
- Unit tests (A-E) prove the serialization and fallback-bypass in isolation; integration tests
  (F-G) prove the same properties survive a real GET -> flatten -> POST round trip through
  `/admin/settings`, mirroring `settingsApp`'s exact payload-flatten logic from `settings.html`.

## Task Commits

Each task was committed atomically (TDD RED/GREEN, plus a test-only commit for the
integration regression):

1. **Task 1 RED: failing unit tests for raw-value + string serialization** - `7699ccc` (test)
2. **Task 1 GREEN: `_get_raw()` + string serialization in `all_for_ui()`** - `c88c728` (feat)
3. **Task 2: GET-payload -> POST-unchanged integration regression** - `f713571` (test)

_Note: Task 2 adds regression tests only (no new production code) — the fix it verifies was
already implemented in Task 1's GREEN commit, so these integration tests pass immediately
against Task 1's fix rather than following a separate RED step. See "TDD Gate Compliance" below._

## Files Created/Modified

- `core/settings.py` - Added `_get_raw(key)` (stored-or-default resolution, no fallback
  branch); `all_for_ui()` now sources `entry["value"]` from `_get_raw()` and coerces
  `snowflake` -> `str`, `role_list` -> comma-joined `str` (`""` for empty). `get()` unchanged.
- `tests/test_settings.py` - 5 new unit tests (A-E): snowflake-is-string, role_list-is-
  comma-joined-string, no-precision-losing-literal in `json.dumps(all_for_ui())`, raw-value-
  bypasses-fallback while `get()` still cascades, and other type_tags stay native.
- `tests/test_app_settings.py` - `_flatten()` helper mirroring `settingsApp`'s payload build;
  2 new integration tests (F-G): unchanged full-form save preserves `PHOTO_CHANNEL_ID`'s exact
  snowflake, and preserves the CONF-03 cascade through an unchanged save followed by a real
  gallery-only edit that still cascades to all three dependent keys.

## Decisions Made

- `_get_raw()` duplicates `get()`'s resolution logic rather than parameterizing `get()` with a
  skip-fallback flag, to guarantee `get()` stays byte-identical (an explicit success criterion)
  and to avoid widening a public, widely-called function's signature for an internal-only need.
- No change to `app/templates/settings.html` — confirmed via the plan's `<interfaces>` block
  and by reading the template directly that all affected inputs (`snowflake`, `role_list`) are
  `type="text"` bound via plain `x-model`, so they already accept and round-trip strings.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

Task 1 (`type="auto" tdd="true"`) followed the full RED -> GREEN cycle:
- RED gate: `7699ccc` (`test(02-05): add failing tests for raw-value + string serialization...`)
  — 4 of 5 new tests failed against pre-fix `core/settings.py` (verified via `pytest -k`
  before committing); the 5th (Test E, unrelated type_tags) was a baseline-green assertion by
  design, since that behavior was not being changed.
- GREEN gate: `c88c728` (`feat(02-05): serve raw string-serialized values from all_for_ui()...`)
  — all 22 tests in `tests/test_settings.py` pass.
- No REFACTOR commit — the GREEN implementation was already minimal (one helper function, one
  four-line coercion block); no cleanup was warranted.

Task 2 (`type="auto" tdd="true"`) is a regression-coverage task per its own `<action>` (files:
`tests/test_app_settings.py` only, no core-file change listed) — its two new tests (F, G) verify
the round trip through the real HTTP route using the fix Task 1 already implemented, so they
pass on first run rather than following an independent RED step. This is expected given the
plan's task-level file scoping, not a gate violation: Task 2 introduces no new production
behavior to gate.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both FAILED Phase 2 roadmap success criteria (SC2/PANEL-02, SC3/PANEL-03) are restored;
  `core/settings.py::get()` remains byte-identical, so Phase 1's CONF-03 cascade is intact.
- Full settings surface verified: `pytest tests/test_settings.py tests/test_app_settings.py
  tests/test_settings_template.py tests/test_app_auth.py -q` -> 59 passed (baseline 52 + 7 new).
- Manual confirmation: `json.dumps(settings.all_for_ui())` after `seed_defaults()` contains no
  bare numeric literal >= 16 digits (regex-scanned, none found).
- No blockers. Phase 2 gap-closure work for CR-01/CR-02 is complete; ready for phase
  re-verification (`/gsd:verify-work 2`) to confirm SC2/SC3 now PASS.

---
*Phase: 02-owner-settings-panel*
*Completed: 2026-07-21*
