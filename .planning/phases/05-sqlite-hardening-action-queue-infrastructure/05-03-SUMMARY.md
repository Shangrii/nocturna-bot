---
phase: 05-sqlite-hardening-action-queue-infrastructure
plan: 03
subsystem: app
tags: [fastapi, alpinejs, sqlite, action-queue, tdd]

requires:
  - phase: 05-sqlite-hardening-action-queue-infrastructure
    plan: 01
    provides: Durable action_queue state machine and sqlite hardening
  - phase: 05-sqlite-hardening-action-queue-infrastructure
    plan: 02
    provides: Always-loaded bot queue worker and permanent noop action
provides:
  - Manager-gated enqueue, status, and failed-only retry API routes
  - Route-boundary noop kind allowlist and decoded action results
  - Existing heartbeat-derived bot_online state in action status responses
  - Standalone Overview noop proof card with short-poll, offline, success, failure, and retry states
affects: [05-04-concurrent-load-gate, 05-05-integration-verification, phases-06-09-module-actions]

tech-stack:
  added: []
  patterns: [manager-gated action API, run_in_threadpool sqlite boundary, sibling Alpine short-poll component]

key-files:
  created:
    - tests/test_app_actions.py
    - .planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-03-SUMMARY.md
  modified:
    - app/main.py
    - app/templates/overview.html
    - app/static/dashboard.css

key-decisions:
  - "All three action routes reuse require_manager; no new authentication or Discord credential surface was introduced."
  - "The API rejects unknown kinds before enqueue and delegates failed-only fresh-row retry semantics to core.action_queue."
  - "The proof card owns its polling timer independently of overviewApp and stops polling on terminal states."

patterns-established:
  - "Panel action widgets POST once, short-poll their per-action status, and redirect polling to the new id returned by retry."
  - "Pending or claimed actions use the existing heartbeat helper to distinguish bot-offline durability from genuine failure."

requirements-completed: [INFRA-01]
duration: 18min
completed: 2026-07-23
---

# Phase 5 Plan 03: App Action Queue API and Overview Proof Summary

**Managers can now enqueue, inspect, and retry durable bot actions through a guarded API, while the Overview page proves the complete noop lifecycle inline without reloading.**

## Performance

- **Duration:** 18 min
- **Completed:** 2026-07-23
- **Tasks:** 3
- **Production/test files changed:** 4

## Accomplishments

- Added manager-gated enqueue, status, and retry routes using the ready-to-use Pattern 3 implementation.
- Enforced the `_ALLOWED_KINDS` boundary before enqueue, returning 422 for unknown action kinds.
- Returned decoded result/error/status data plus the existing heartbeat-derived `bot_online` value, with 404 and 409 state guards.
- Added `db.init_action_queue()` to the existing dual-process lifespan initialization block.
- Added a manager/owner-visible bilingual Overview proof card that runs `noop`, polls every 1.5 seconds, distinguishes offline pending work, and follows fresh action IDs on retry.
- Added seven isolated route tests backed by a temporary `actions.db`, including real signed-session coverage of the non-manager 403 path.

## Task Commits

1. **Task 1: RED — `/api/actions` route tests** — `7f6037e` (`test`)
2. **Task 2: Three routes + kind allowlist + lifespan init** — `2c941e4` (`feat`)
3. **Task 3: Overview proof card + status styling** — `099a9b5` (`feat`)

## Files Created/Modified

- `tests/test_app_actions.py` - Manager gate, allowlist, enqueue, status shape, missing row, bot-offline, and retry contracts.
- `app/main.py` - Queue import/init, noop allowlist, and the three manager-gated action routes.
- `app/templates/overview.html` - Independent `actionProofApp()` component with enqueue, status polling, offline feedback, and retry.
- `app/static/dashboard.css` - Minimal proof-card state styling using existing dashboard tokens and card conventions.
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-03-SUMMARY.md` - Plan outcome and verification evidence.

## Decisions Made

- The unauthorised route test uses a correctly signed authenticated session with no qualifying roles, proving the real `require_manager` denial path without replacing the dependency.
- The status endpoint calls the existing `_bot_online()` helper instead of introducing another heartbeat calculation.
- UI visibility checks the already-resolved owner/Manager render context, while all API routes remain independently protected by `require_manager`.
- Fetch failures become concise bilingual failed states; persisted queue failures retain their server-recorded reason and expose the retry control.

## Deviations from Plan

None in implementation, behavior, or file scope.

## Issues Encountered

- Pytest requires normal access to its configured Windows temp directory for `tmp_path`; the exact commands were run with that access using the requested conda Python.
- The suite reports pre-existing dependency/deprecation warnings for `audioop`, Requests/urllib3, and Starlette TestClient.

## Verification

- **Task 1 RED:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_actions.py -q` — **7 failed** with expected 404 responses because the routes did not exist.
- **Task 2 GREEN:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_actions.py -q` — **7 passed, 3 warnings**.
- **Task 3 GREEN:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_dashboard.py -q` — **7 passed, 3 warnings**.
- **Combined target:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_actions.py tests/test_app_dashboard.py -q` — **14 passed, 3 warnings**.
- **Full suite:** `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` — **709 passed, 4 warnings**.
- Static audit confirmed all three routes use `Depends(require_manager)`, the kind allowlist precedes enqueue, `bot_online` reuses `_bot_online()`, retry polls the returned fresh ID, and no Discord import was added to the app.

## User Setup Required

None. No package, environment, credential, intent, or external-service changes are required.

## Next Phase Readiness

- Plan 05-04 can prove concurrent bot/panel sqlite writes under load.
- Plan 05-05 can manually verify the live app-to-bot noop path and the offline/reconnect presentation.
- Phases 6-9 can extend the allowlist and worker dispatch registry with their idempotent module actions.

## Self-Check: PASSED

Every task acceptance criterion and plan success criterion is satisfied, all task commits are isolated to their assigned files, and the full repository suite is green.

---
*Phase: 05-sqlite-hardening-action-queue-infrastructure*
*Completed: 2026-07-23*
