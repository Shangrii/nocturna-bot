---
phase: 02-owner-settings-panel
plan: 01
subsystem: database
tags: [python, sqlite, dataclasses, zoneinfo, tdd]

# Dependency graph
requires:
  - phase: 01-config-store-and-consolidation
    provides: "core/settings.py's get/set/all_for_ui/SettingRejected/_SCHEMA contract, validated sqlite-backed settings store"
provides:
  - "all_for_ui() emits a bilingual label for every setting, min/max for int_range entries, and sorted timezone options for REMINDERS_TZ (D-09 typed-field render metadata)"
  - "public validate_only(key, value) dry-run that mirrors set()'s validation half without any DB access (D-05 atomic multi-error POST support)"
affects: [02-02, 02-03, 02-04, owner-settings-panel-routes, owner-settings-panel-templates]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive dataclass extension: new frozen-dataclass fields appended after existing ones with defaults so all 19 existing construction sites stay valid without change"
    - "Dry-run validation function (validate_only) that set() delegates to, keeping the _SCHEMA allowlist check in exactly one place"

key-files:
  created: []
  modified:
    - core/settings.py
    - tests/test_settings.py

key-decisions:
  - "set() now delegates its validation to validate_only() rather than duplicating the allowlist check — same behavior, one shared code path (plan allowed this as optional; taken because it stayed byte-behaviorally identical)"
  - "Bilingual ES-EN labels (Spanish first, · separator) added to all 19 _SCHEMA entries per D-13 house style; wording chosen at implementer discretion as the plan allowed"

patterns-established:
  - "New _Setting descriptor fields (label/min/max) are additive and defaulted — future schema extensions should follow the same append-after-hint-with-defaults shape to avoid touching the 19 construction sites' positional args"

requirements-completed: [PANEL-02, PANEL-03]

# Metrics
duration: 8min
completed: 2026-07-21
---

# Phase 2 Plan 1: Settings Store Extension Summary

**Extended `core/settings.py::all_for_ui()` with D-09 render metadata (label/min/max/timezone options) and added a public `validate_only()` dry-run for atomic multi-field POST validation — both additive, zero contract change to `get`/`set`/`seed_defaults`.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-21T06:03:17-06:00 (first RED commit)
- **Completed:** 2026-07-21T06:06:31-06:00
- **Tasks:** 2
- **Files modified:** 2 (`core/settings.py`, `tests/test_settings.py`)

## Accomplishments
- `all_for_ui()` now carries a truthy bilingual `label` for all 19 settings, `min`/`max` for the two `int_range` entries (`JINXXY_POLL_HOURS`, `REMINDERS_CATCHUP_GRACE_HOURS`), and a sorted `options` list (all IANA zones, including `America/Mexico_City`) for `REMINDERS_TZ`
- Added `validate_only(key, value)`: raises `SettingRejected` for an unknown key or invalid value, returns the coerced value on success, never opens a DB connection — lets the (upcoming) panel POST handler validate every field before writing any
- `set()` refactored to delegate to `validate_only`, removing a duplicated allowlist check while staying byte-behaviorally identical
- Full repo test suite: 620 passed (up from 617 baseline), including 6 new/extended assertions in `tests/test_settings.py`

## Task Commits

Each task followed RED → GREEN:

1. **Task 1: Surface D-09 render metadata on all_for_ui()**
   - `0a03540` test(02-01): add failing test for all_for_ui D-09 render metadata
   - `b53f4b7` feat(02-01): surface D-09 render metadata on all_for_ui()
2. **Task 2: Add public validate_only() dry-run**
   - `64b2e97` test(02-01): add failing test for validate_only dry-run
   - `197f678` feat(02-01): add public validate_only() dry-run

**Plan metadata:** (this SUMMARY commit, follows)

_TDD tasks each had test → feat commits (RED → GREEN); no refactor commit was needed beyond the small `set()`→`validate_only()` delegation folded into Task 2's GREEN commit._

## Files Created/Modified
- `core/settings.py` - `_Setting` dataclass gains `label`/`min`/`max` fields; all 19 `_SCHEMA` sites gain bilingual labels, the two `int_range` sites gain `min=1, max=168`; `all_for_ui()` emits the new metadata; new public `validate_only(key, value)`; `set()` delegates to it
- `tests/test_settings.py` - `test_all_for_ui_grouped` extended with label/min-max/options assertions; three new tests for `validate_only` (coerced return, out-of-range rejection with no write, unknown-key rejection)

## Decisions Made
- Delegated `set()`'s validation to `validate_only()` (plan's optional refactor) to keep the `_SCHEMA` allowlist check in one place — verified byte-behaviorally identical by the full existing store suite staying green
- Bilingual label wording (Spanish first, `·` separator, D-13 house style) chosen freely per plan's stated implementer discretion

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`core/settings.py::all_for_ui()` and `validate_only()` are ready for the Phase 2 panel routes:
- `all_for_ui()`'s new `label`/`min`/`max`/`options` fields directly satisfy PANEL-02's typed-field rendering requirement
- `validate_only()` directly satisfies PANEL-03's atomic dry-run-then-commit POST pattern (Pattern 3 in 02-RESEARCH.md)
- No blockers. `core/settings.py` and `tests/test_settings.py` remain byte-compatible with Phase 1's `get`/`set`/`seed_defaults` contract (full 620-test suite green).

## Self-Check: PASSED

- FOUND: core/settings.py (contains `def validate_only`, `label: str = ""`, `min: int | None = None`, `max: int | None = None`, `available_timezones`, `sorted(available_timezones())`, `descriptor.min`, `descriptor.max`)
- FOUND: tests/test_settings.py (contains `validate_only` assertions and extended `test_all_for_ui_grouped`)
- FOUND commit 0a03540, b53f4b7, 64b2e97, 197f678 in `git log --oneline --all`
- `grep -c "min=1, max=168" core/settings.py` → 2 (both int_range sites)
- `pytest tests/test_settings.py -x` → 17 passed
- `pytest` (full repo suite) → 620 passed

---
*Phase: 02-owner-settings-panel*
*Completed: 2026-07-21*
