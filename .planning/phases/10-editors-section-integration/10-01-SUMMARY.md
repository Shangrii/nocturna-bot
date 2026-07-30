---
phase: 10-editors-section-integration
plan: 01
subsystem: testing
tags: [pytest, fastapi, tdd-red, session-security, slug-validation]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access
    provides: "_resolve_roles/require_manager 3-tier owner/Manager/editor union resolver, TierForbidden/forbidden.html rendering"
  - phase: 10-editors-section-integration (10-RESEARCH/10-PATTERNS)
    provides: "collision surface analysis (en/es/gallery/store/fonts/build) and Pitfall-1 session-clear bug identification"
provides:
  - "RED regression test proving GET /editor must deny a non-editor via forbidden.html (required_tier=editor) with the session intact, never login.html with the session cleared"
  - "RED test proving GET /editor must render inside the dashboard shell (sidebar + topbar)"
  - "RED tests proving resolve_slug rejects the six widened public-site reserved words (en/es/gallery/store/fonts/build)"
  - "Forward-compatible _resolve_roles overrides on the two pre-existing GET /editor tests so 10-02's gate switch (require_editor -> _resolve_roles) doesn't silently break them"
affects: [10-02-PLAN, 10-05-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Signed session cookie construction in tests via itsdangerous.TimestampSigner pulled from the live SessionMiddleware secret (mirrors tests/test_app_actions.py's _set_session helper)"
    - "Structural class/route token assertions (class=\"side\", nav-item, /logout) instead of copy/color assertions, so a later CSS retint can't break shell-wrap tests"

key-files:
  created: []
  modified:
    - tests/test_app_dashboard.py
    - tests/test_app_editor.py
    - tests/test_editors_model.py

key-decisions:
  - "Task 1's _resolve_roles override is deliberately inert today (GET /editor still gates on require_editor) — the RED signal instead comes from monkeypatching app.auth._fetch_member_roles so require_editor's live has_editor_role() check resolves deterministically without a network call"
  - "Task 4's _resolve_roles overrides added to both pre-existing GET /editor tests do not change any existing assertion — verified GREEN against the current pre-10-02 main.py before finishing"

patterns-established:
  - "Pattern: RED tests that pin a future gate switch use a dependency override that is a no-op today and load-bearing after the switch (used for both Task 1's regression test and Task 4's forward-compat edits)"

requirements-completed: [EDIT-01, EDIT-02]

# Metrics
duration: 25min
completed: 2026-07-30
---

# Phase 10 Plan 01: RED-first tests for editor gate security, shell wrap, and reserved slugs Summary

**Four RED/forward-compat test edits across tests/test_app_dashboard.py, tests/test_app_editor.py, and tests/test_editors_model.py pin the Pitfall-1 session-clear bug, the missing dashboard-shell wrap, and the widened reserved-slug set — plus keep two pre-existing GET /editor tests green across 10-02's upcoming gate switch.**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-07-30T16:58:45Z
- **Tasks:** 4/4 completed
- **Files modified:** 3

## Accomplishments
- Pinned the Pitfall-1 regression (locked "Editor" nav click must 403 via forbidden.html with the session intact, never login.html with the session cleared) as a parametrized RED test covering both an owner-only and a manager-only non-editor viewer.
- Pinned the "GET /editor renders inside the dashboard shell" contract as a RED test asserting `_sidebar.html`'s rail marker and the shell topbar's `/logout` link, using structural tokens immune to the later CSS retint.
- Pinned the widened `RESERVED_SLUGS` set (en/es/gallery/store/fonts/build) as six new RED parametrized cases on `resolve_slug`.
- Forward-compatibility edit: both pre-existing GET `/editor` tests now also override `app.deps._resolve_roles` so they will not silently start 401'ing once 10-02 switches that route's gate — verified GREEN against the current `main.py` before finishing.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED regression test — locked Editor nav click never clears the session** - `284090f` (test)
2. **Task 2: RED test — GET /editor renders inside the dashboard shell** - `444dbb8` (test)
3. **Task 3: RED test — resolve_slug rejects the widened reserved public-site words** - `196dae5` (test)
4. **Task 4: Forward-compat the two pre-existing GET /editor tests for 10-02's gate switch** - `9742cf3` (fix)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `tests/test_app_dashboard.py` - Added `_set_session` helper (signed session cookie via the live SessionMiddleware secret, mirroring `test_app_actions.py`); added `test_locked_editor_nav_click_keeps_session` (parametrized RED, Pitfall-1); added a `_resolve_roles` override to `test_editor_only_locked_out_of_dashboard` (forward-compat, Task 4)
- `tests/test_app_editor.py` - Added `test_editor_page_renders_in_shell` (RED, shell-wrap contract); added `_resolve_roles` override + `_ROLES_IDENT` to the module `client` fixture (forward-compat, Task 4)
- `tests/test_editors_model.py` - Added `test_resolve_slug_rejects_widened_public_site_reserved_words`, parametrized over en/es/gallery/store/fonts/build (RED)

## Decisions Made
- Task 1's test overrides `app.deps._resolve_roles` per the plan's acceptance criteria, but since GET `/editor` still gates on `require_editor` (until 10-02), that override alone would be inert. To get a deterministic, network-free RED failure today, the test additionally monkeypatches `app.auth._fetch_member_roles` (the live Discord role read `require_editor`'s `has_editor_role()` call makes) so the current buggy path — session-clear + login.html — fires reliably without hitting the network. This keeps the override forward-compatible (it becomes load-bearing the moment 10-02 lands) while still producing a correct RED signal now.
- Verified Task 4's edits produce zero assertion changes and stay GREEN against the current `main.py`, per the plan's explicit requirement that this edit is forward-compatible, not a RED change.

## Deviations from Plan

None - plan executed exactly as written. All four tasks match their `<action>`/`<acceptance_criteria>` blocks; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

None. A pre-existing, out-of-scope `core.settings` "no such table: settings" warning appears when running `tests/test_app_editor.py::test_editor_page_renders_in_shell` (the module's `client` fixture, unlike `test_app_dashboard.py`'s, does not seed a `DB_PATH`/`settings` table) — this is a harmless warning already present for every other test in that file that touches `WEBSITE_BASE_URL`, not a regression introduced by this plan, and is left untouched (scope boundary).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 10-02 (backend) can now widen `RESERVED_SLUGS` and switch GET `/editor`'s dependency from `require_editor` to `_resolve_roles` with all three RED contracts (session-survival, reserved-words) as its automated verification target, and both pre-existing GET `/editor` tests already tolerate the gate switch.
- 10-05 (editor.html shell wrap) has a RED structural-marker test (`test_editor_page_renders_in_shell`) ready to turn GREEN once `editor.html` extends `_dashboard_base.html`.
- No blockers. Full repo test suite (`pytest tests/`) shows 880 passed / 9 intentionally-RED (this plan's new cases) with zero regressions elsewhere.

---
*Phase: 10-editors-section-integration*
*Completed: 2026-07-30*

## Self-Check: PASSED

All claimed files verified present (tests/test_app_dashboard.py, tests/test_app_editor.py,
tests/test_editors_model.py, 10-01-SUMMARY.md). All claimed commit hashes verified present
in git log (284090f, 444dbb8, 196dae5, 9742cf3, 6f858cd).
