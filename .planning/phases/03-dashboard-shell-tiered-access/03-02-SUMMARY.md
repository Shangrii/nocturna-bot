---
phase: 03-dashboard-shell-tiered-access
plan: 02
subsystem: auth
tags: [settings-store, role-mapping, fastapi, alpine, sqlite]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access (plan 01)
    provides: test_settings.py schema test cases for manager_roles/editor_roles
provides:
  - manager_roles / editor_roles role_list keys in core/settings.py (_SCHEMA), group "access", no fallback_key
  - bilingual "Acceso · Access" group legend in app/templates/settings.html
affects: [03-dashboard-shell-tiered-access plan 05 (tier resolution reads these keys), 03-dashboard-shell-tiered-access plan 07 (integration test verifying the rendered group)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "role_list _Setting entry with no fallback_key for an independent (non-cascading) mapping"
    - "literal lowercase _SCHEMA key (deliberate deviation from UPPER_SNAKE convention, D-05)"

key-files:
  created: []
  modified:
    - core/settings.py
    - app/templates/settings.html

key-decisions:
  - "manager_roles/editor_roles use literal lowercase keys per CONTEXT.md D-05, not auto-corrected to MANAGER_ROLE_IDS/EDITOR_ROLE_IDS"
  - "Neither entry sets fallback_key — deliberate deviation from the GALLERY_STAFF_ROLE_IDS cascade so the mapping never silently inherits staff-role lists"
  - "editor_roles seeds from ROLE_MODERATOR_ID so has_editor_role's future migration (D-08, later plan) is behavior-preserving"

patterns-established:
  - "New settings 'group' values only need one groupNames JS dict entry — the existing role_list field-type template branch renders any role_list key automatically, no new UI code"

requirements-completed: [ACCESS-04]

# Metrics
duration: 12min
completed: 2026-07-22
---

# Phase 3 Plan 02: Role-to-Tier Mapping Storage Summary

**Two new independent role_list settings keys (`manager_roles`, `editor_roles`) added to the validated settings store with a bilingual "Acceso · Access" form group, reusing v1's role-list validation/seeding/UI plumbing with no new write path.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-22T01:04:00Z
- **Completed:** 2026-07-22T01:16:58Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- `core/settings.py::_SCHEMA` gained `manager_roles` (seeded `1453560115423875205`) and `editor_roles` (seeded from `ROLE_MODERATOR_ID`), both `role_list` type, group `"access"`, validated by the existing `_validate_role_id_list`, with no `fallback_key` — an independent mapping that can never inherit the gallery staff-role cascade
- `app/templates/settings.html`'s `groupNames` dict gained `access: 'Acceso · Access'`, so the owner-facing form renders a bilingual legend for the new group instead of the raw key string, reusing the existing `role_list` input branch with zero new template code
- Confirmed via `settings.seed_defaults()` that both keys seed byte-identical to today's `.env`-derived behavior (`ROLE_MODERATOR_ID` default `1418724526308593834`) until an owner edits them

## Task Commits

Each task was committed atomically:

1. **Task 1: Add manager_roles and editor_roles role_list entries to core/settings.py** - `916fc4f` (feat)
2. **Task 2: Add the bilingual "Acceso · Access" group legend to settings.html** - `ff90322` (feat)

_Note: no TDD tasks in this plan — Plan 01 pre-supplied the failing schema test cases in `tests/test_settings.py`, which this plan's Task 1 turned green._

## Files Created/Modified
- `core/settings.py` - Added `manager_roles`/`editor_roles` `_Setting` entries to `_SCHEMA` (group `access`, `role_list`, no `fallback_key`)
- `app/templates/settings.html` - Added `access: 'Acceso · Access'` to the `groupNames` JS dict

## Decisions Made
- Kept the literal lowercase `"manager_roles"`/`"editor_roles"` key casing exactly as specified in CONTEXT.md D-05, even though every other `_SCHEMA` key is `UPPER_SNAKE_CASE` — this is a locked project decision, not a style inconsistency to fix.
- Deliberately omitted `fallback_key` on both new entries, unlike the `REVIEWS_STAFF_ROLE_IDS`/`REMINDERS_STAFF_ROLE_IDS`/`JINXXY_STAFF_ROLE_IDS` cascade pattern — these two keys are their own independent role→tier mapping (D-06) and must resolve to `[]` when empty, never silently fall back to `GALLERY_STAFF_ROLE_IDS`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. `tests/test_settings.py` already contained the schema test cases for these two keys (added in Plan 01, per the plan's stated intent "the Plan 01 schema cases now pass") — Task 1's implementation turned them from failing to passing, confirmed by a full local run (`22 passed`).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- The settings store now exposes `manager_roles`/`editor_roles` for Plan 05 (tier resolution) to read via `settings.get("manager_roles")` / `settings.get("editor_roles")`.
- The owner-facing form renders both keys under "Acceso · Access"; full end-to-end route verification (visiting `/admin/settings` and confirming the rendered group) is deferred to Plan 07 per the plan's own `<verification>` note, since it depends on routes/fixtures introduced in other Wave-1 plans.
- No blockers. Full local test suite: 645 passed (same count as v1.0's baseline — the new schema test cases were already counted in that total from Plan 01).

---
*Phase: 03-dashboard-shell-tiered-access*
*Completed: 2026-07-22*

## Self-Check: PASSED

- FOUND: core/settings.py
- FOUND: app/templates/settings.html
- FOUND: .planning/phases/03-dashboard-shell-tiered-access/03-02-SUMMARY.md
- FOUND: 916fc4f (Task 1 commit)
- FOUND: ff90322 (Task 2 commit)
- FOUND: 00ab330 (SUMMARY.md commit)
