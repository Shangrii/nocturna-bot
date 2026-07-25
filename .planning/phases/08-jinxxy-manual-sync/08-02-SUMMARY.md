---
phase: 08-jinxxy-manual-sync
plan: 02
subsystem: auth
tags: [discord-oauth, fastapi, session, attribution, tdd]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access
    provides: OAuth callback, live role resolution, and Manager-gated roles dict
provides:
  - OAuth-verified Discord username persisted in the signed session
  - None-safe username key in every resolved roles dict
  - Spoofing regression proving client input cannot override OAuth identity
affects: [08-05, 08-06, jinxxy-sync, activity-attribution]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Non-authorization identity metadata sourced only from the verified OAuth response
    - Legacy session fields read with dict.get for None-safe rollout

key-files:
  created: []
  modified:
    - app/auth.py
    - app/deps.py
    - tests/test_app_auth.py

key-decisions:
  - "Persist the existing OAuth-derived username variable only after authorization succeeds."
  - "Treat username as display-only metadata; authorization remains exclusively live tier resolution."
  - "Return None for username in legacy sessions rather than invalidating or clearing them."

patterns-established:
  - "Display attribution may live in the signed session but never influences tier authorization."
  - "Downstream consumers receive roles.username as optional and must retain the discord_id fallback."

requirements-completed: [JINX-01]

# Metrics
duration: 5min
completed: 2026-07-25
---

# Phase 8 Plan 02: OAuth Username Attribution Summary

**Successful Discord OAuth callbacks now retain the verified username for human-readable Jinxxy attribution, with legacy-safe propagation through the Manager roles dict.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-07-25T02:56:20Z
- **Completed:** 2026-07-25T03:00:59Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Persisted the already-computed Discord OAuth username only on the fully authorized callback path.
- Added a None-safe `username` field to `_resolve_roles` without changing owner, Manager, editor, 401, or 403 behavior.
- Added four regression behaviors covering trusted-source persistence, global-name/id fallbacks, roles propagation, and legacy sessions.
- Proved a hostile client-supplied `?username=` value cannot override the OAuth-verified identity.

## Task Commits

Each task was committed atomically:

1. **Task 2: Regression tests for session username and roles key** - `a2d0ac0` (test)
2. **Task 1: Persist OAuth username and thread it into roles** - `2ef7443` (feat)

The regression-test task ran first to preserve the required RED-before-GREEN sequence.

## Files Created/Modified

- `app/auth.py` - Documents and persists the OAuth-verified username after tier authorization.
- `app/deps.py` - Adds a legacy-safe optional username to the resolved roles dict.
- `tests/test_app_auth.py` - Covers the trusted source, fallback order, propagation, and legacy-session behavior.

## Decisions Made

- Reused `username = user.get("username") or user.get("global_name") or user_id` directly; no second derivation or client-controlled source was added.
- Kept the session write immediately beside `discord_id` and after all authorization/provisioning gates.
- Used `request.session.get("username")` so cookies issued before this deployment continue to authorize normally with `roles["username"] is None`.
- Did not change any tier gate or redirect target.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Executed test Task 2 before implementation Task 1**

- **Found during:** Pre-execution TDD gate
- **Issue:** The plan listed its regression-test task after production implementation, conflicting with the mandatory failing-test-first protocol.
- **Fix:** Added and committed only the planned auth tests first, observed the expected missing-key failures, then implemented the session and roles plumbing.
- **Files modified:** `tests/test_app_auth.py`
- **Verification:** Initial username slice reported 4 failed and 1 existing test passed; final slice reported 5 passed.
- **Committed in:** `a2d0ac0`

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** No scope, behavior, or artifact changes; task order changed only to enforce TDD.

## Issues Encountered

None.

## User Setup Required

None - no packages, credentials, environment variables, or external services were added.

## Verification

- RED gate: `tests/test_app_auth.py -k username -v` reported `4 failed, 1 passed, 26 deselected` before production changes.
- Focused GREEN gate: the same username selector reported `5 passed, 26 deselected`.
- Task 1 exact verifier: `tests/test_app_auth.py -q` reported `31 passed, 2 warnings`.
- Task 2 exact verifier: `tests/test_app_auth.py -v` reported `31 passed, 2 warnings`.
- Full suite: `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` reported `807 passed, 4 warnings`.
- Security scans found the session username write immediately after `discord_id`, exactly one None-safe roles key, no query/form username source, and no `pytest-asyncio` usage.
- Changed-file audit contains only `app/auth.py`, `app/deps.py`, and `tests/test_app_auth.py` before this summary; `STATE.md` and `ROADMAP.md` were not modified.

## Self-Check: PASSED

## Next Phase Readiness

- Plan 08-06 can enqueue the human-readable `roles["username"]` with a raw `discord_id` fallback for legacy sessions.
- Plans 08-05/08-06 can use the verified name for panel source labels and activity attribution.
- No blockers remain.

---
*Phase: 08-jinxxy-manual-sync*
*Completed: 2026-07-25*
