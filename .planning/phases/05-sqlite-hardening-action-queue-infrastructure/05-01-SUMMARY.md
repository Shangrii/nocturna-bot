---
phase: 05-sqlite-hardening-action-queue-infrastructure
plan: 01
subsystem: database
tags: [sqlite, wal, busy-timeout, action-queue, tdd]

requires:
  - phase: 04-settings-migration-name-resolution
    provides: Shared sqlite dual-process patterns and isolated database-test idioms
provides:
  - Explicit 8000ms sqlite busy timeout on every project connection
  - Generic action_queue schema and status index
  - Durable pending-to-claimed-to-terminal queue state machine with backoff and stale recovery
  - Regression coverage for purge safety, fresh/stale claims, manual retry, and lock retries
affects: [05-02-action-queue-worker, 05-03-action-api, 05-04-concurrent-load-gate, phases-06-09]

tech-stack:
  added: []
  patterns: [global sqlite busy timeout, scoped retry-on-locked decorator, terminal-only purge]

key-files:
  created:
    - core/action_queue.py
    - tests/test_action_queue.py
    - tests/test_db_hardening.py
    - .planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-01-SUMMARY.md
  modified:
    - core/db.py

key-decisions:
  - "busy_timeout=8000 is applied centrally in core.db._get_conn so every connection receives it."
  - "Explicit database-lock retry remains scoped to the six action_queue write functions; get_status and existing writers are not wrapped."
  - "Queue history purging can delete only done/failed rows, and manual retry can mint a fresh row only from failed state."

patterns-established:
  - "Queue writes use fresh sqlite connections plus bounded retry after busy_timeout exhaustion."
  - "At-least-once recovery requeues only claims older than the 60-second stale threshold."
  - "Every queue database test redirects config.DB_PATH to a tmp_path file and never touches bot.db."

requirements-completed: [INFRA-01, INFRA-02]
duration: 15min
completed: 2026-07-22
---

# Phase 5 Plan 01: sqlite Hardening and Action Queue Foundation Summary

**Every sqlite connection now has an explicit contention timeout, and a pure durable action queue provides serialized claims, bounded retry, stale recovery, and safe terminal history.**

## Performance

- **Duration:** 15 min
- **Completed:** 2026-07-22
- **Tasks:** 3
- **Production/test files changed:** 4

## Accomplishments

- Added `PRAGMA busy_timeout=8000` immediately after WAL activation in the single `_get_conn()` choke point.
- Added the generic `action_queue` table and `idx_action_queue_status` index with the exact Phase-5 schema.
- Added the pure queue state machine: enqueue, stale recovery, oldest-first/backoff-aware claim, completion, automatic retry/failure, failed-only manual retry, and status lookup.
- Guarded both halves of terminal-history purge so pending or claimed actions can never be deleted.
- Added 13 focused tests covering the complete queue contract and connection hardening.

## Task Commits

1. **Task 1: RED — state-machine + hardening test scaffolds** — `2fc321f` (`test`)
2. **Task 2: busy_timeout pragma + init_action_queue** — `98e0fc0` (`feat`)
3. **Task 3: pure action queue state machine** — `5459174` (`feat`)

## Files Created/Modified

- `tests/test_action_queue.py` - Full state-machine, purge/stale/retry regressions, and `_retry_on_locked` behavior.
- `tests/test_db_hardening.py` - Isolated `busy_timeout == 8000` contract importing only `config` and `core.db`.
- `core/db.py` - Central busy timeout plus queue DDL/index initializer.
- `core/action_queue.py` - Pure sqlite queue protocol and scoped database-lock retry decorator.
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-01-SUMMARY.md` - Plan outcome and verification evidence.

## Decisions Made

- Followed RESEARCH Pattern 1 directly; no new dependency or framework was introduced.
- Kept existing low-frequency database writers unchanged: the global busy timeout protects them, while explicit retries are limited to high-contention queue writes.
- Preserved the 60-second stale-claim warning for Phases 6-9 to validate against real dispatch-handler duration.

## Deviations from Plan

None in implementation or test scope.

## Issues Encountered

- In-sandbox pytest runs that reached `tmp_path` could not access the default Windows pytest temp directory. The exact Task 2, Task 3, and full-suite commands were rerun outside the filesystem sandbox and completed successfully.
- Pytest reports pre-existing dependency/deprecation warnings for Requests/urllib3, Starlette TestClient, and `audioop`; they do not affect the queue contract.

## Verification

- **Task 1 RED:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue.py tests/test_db_hardening.py -q` exited non-zero at collection because `core.action_queue` did not exist yet.
- **Task 2 GREEN:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_db_hardening.py tests/test_settings.py -q` — **31 passed**.
- **Task 3 GREEN:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue.py tests/test_db_hardening.py -q` — **13 passed**.
- **Full suite:** `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` — **698 passed, 4 warnings**.
- Static audit confirmed six `@_retry_on_locked` write functions, an unwrapped `get_status`, two terminal-state purge guards, a failed-only manual retry guard, and no Discord/FastAPI imports in `core/action_queue.py`.

## User Setup Required

None. No package, environment, credential, or external-service changes are required.

## Next Phase Readiness

- Plan 05-02 can build the serialized bot worker against the stable queue API.
- Plan 05-03 can expose manager-gated enqueue/status/retry routes.
- Plan 05-04 can exercise the busy-timeout and retry floor under concurrent load.

## Self-Check: PASSED

Every task acceptance criterion and plan success criterion is satisfied, all task commits are isolated to their assigned files, and the full repository suite is green.

---
*Phase: 05-sqlite-hardening-action-queue-infrastructure*
*Completed: 2026-07-22*
