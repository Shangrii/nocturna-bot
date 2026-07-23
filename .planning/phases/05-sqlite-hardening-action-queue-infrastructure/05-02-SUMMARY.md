---
phase: 05-sqlite-hardening-action-queue-infrastructure
plan: 02
subsystem: bot
tags: [discord-py, tasks-loop, sqlite, action-queue, tdd]

requires:
  - phase: 05-sqlite-hardening-action-queue-infrastructure
    plan: 01
    provides: Durable action_queue state machine and sqlite hardening
provides:
  - Always-loaded ActionQueueCog polling the durable queue every 1.5 seconds
  - Serialized stale-recovery, claim, dispatch, complete/fail worker flow
  - Permanent side-effect-free noop proof action with deterministic failure mode
  - Extracted _run_once worker body covered without starting a real tasks.loop
affects: [05-03-action-api, 05-04-concurrent-load-gate, phases-06-09-action-handlers]

tech-stack:
  added: []
  patterns: [tasks.loop delegate, asyncio.to_thread database boundary, kind-handler registry]

key-files:
  created:
    - cogs/action_queue_worker.py
    - tests/test_action_queue_cog.py
    - .planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-02-SUMMARY.md
  modified:
    - bot.py

key-decisions:
  - "The scheduler wrapper stays trivial; tests and future callers exercise the extracted _run_once body directly."
  - "Every action_queue operation in a tick is offloaded with asyncio.to_thread to protect the Discord gateway loop."
  - "Unknown kinds use the same bounded fail/backoff path as handler failures and never escape the tick."

patterns-established:
  - "Worker dispatch is extensible through self._dispatch, with noop retained as a permanent diagnostic kind."
  - "ActionQueueCog follows the heartbeat lifecycle: defensive init, start, cancel, before_loop readiness, and setup()."

requirements-completed: [INFRA-01]
duration: 12min
completed: 2026-07-22
---

# Phase 5 Plan 02: Bot-Side Action Queue Worker Summary

**A permanently loaded 1.5-second bot worker now turns durable queue rows into serialized, status-tracked dispatches without blocking the Discord event loop.**

## Performance

- **Duration:** 12 min
- **Completed:** 2026-07-22
- **Tasks:** 3
- **Production/test files changed:** 3

## Accomplishments

- Added `ActionQueueCog` with the established init/start/cancel/readiness/setup lifecycle and a 1.5-second scheduler.
- Extracted `_run_once()` for deterministic testing and kept `_tick` as a trivial delegate.
- Implemented stale-claim recovery, oldest-first claim, kind-registry dispatch, completion, and bounded failure recording with every sqlite call in `asyncio.to_thread`.
- Added the permanent `noop` proof action, including an echo success result and deterministic `force_fail` path.
- Registered the worker beside heartbeat and Discord names in the bot's unconditional extension block.

## Task Commits

1. **Task 1: RED — ActionQueueCog dispatch tests** — `b6ed3d4` (`test`)
2. **Task 2: ActionQueueCog + noop proof action** — `8a42e0f` (`feat`)
3. **Task 3: Always-loaded bot registration** — `3d900b9` (`feat`)

## Files Created/Modified

- `tests/test_action_queue_cog.py` - Isolated async tests for noop completion, forced terminal failure, unknown kinds, and empty ticks.
- `cogs/action_queue_worker.py` - Bot worker lifecycle, extracted dispatch body, registry, and noop handler.
- `bot.py` - Unconditional action-queue worker extension registration.
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-02-SUMMARY.md` - Plan outcome and verification evidence.

## Decisions Made

- Tests patch the loop object's `start` method during cog construction and call `await cog._run_once()` directly; the real scheduler is never started.
- Unknown action kinds are converted to `ValueError`, logged in the existing Spanish house style, and passed to `action_queue.fail()` until the row reaches terminal failure.
- JSON decoding sits inside the dispatch exception boundary so malformed persisted payloads are also recorded as queue failures rather than escaping the tick.

## Deviations from Plan

None in implementation or file scope.

## Issues Encountered

- Pytest needs access to its configured Windows temp directory for `tmp_path`; the exact green test commands were run outside the filesystem sandbox.
- The suite reports pre-existing dependency/deprecation warnings for `audioop`, Requests/urllib3, and Starlette TestClient.

## Verification

- **Task 1 RED:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue_cog.py -q` exited non-zero because `cogs.action_queue_worker` did not exist yet.
- **Task 2 GREEN:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue_cog.py -q` — **4 passed, 1 warning**.
- **Task 3:** the exact `python -c` source/AST command exited **0**.
- **Full suite:** `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` — **702 passed, 4 warnings**.
- Static audit found four `action_queue` calls in `_run_once` and four corresponding `asyncio.to_thread` wrappers; the bot registration appears before the optional meeting dependency guard.

## User Setup Required

None. No package, environment, credential, intent, or external-service changes are required.

## Next Phase Readiness

- Plan 05-03 can expose manager-gated enqueue/status/retry routes against the live worker.
- Plans 6-9 can extend `_dispatch` with idempotent real action handlers.

## Self-Check: PASSED

Every task acceptance criterion and plan success criterion is satisfied, task commits are isolated to their assigned files, and the full repository suite is green.

---
*Phase: 05-sqlite-hardening-action-queue-infrastructure*
*Completed: 2026-07-22*
