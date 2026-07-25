---
phase: 08-jinxxy-manual-sync
plan: 05
subsystem: infra
tags: [action-queue, jinxxy, discord-cog, dispatch, error-classification]

# Dependency graph
requires:
  - phase: 08-jinxxy-manual-sync
    plan: 04
    provides: sync_error_category() D-10 boundary mapper and source/actor-aware _run_sync_guarded
provides:
  - The one new action_queue dispatch kind for this phase, jinxxy_sync
  - A handler that resolves the live JinxxyCog and calls only its guarded sync wrapper
  - A shaped, JSON-safe result (counts only, never the raw product list)
  - Every _handle_jinxxy_sync failure path (missing cog, guarded-wrapper exception)
    mapped to one of the three fixed D-10 bilingual categories
affects: [08-06, dashboard, jinxxy-sync, action-queue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Handler-local exception-type mapping before a result reaches action_queue.fail"
    - "Bot-side cog resolution by GroupCog name= kwarg, not class name"

key-files:
  created: []
  modified:
    - cogs/action_queue_worker.py
    - tests/test_action_queue_cog.py

key-decisions:
  - "The get_cog(\"Jinxxy\") lookup and its missing-cog raise live INSIDE the try block, not before it, so a missing cog is mapped to the generic D-10 category instead of leaking internal wording to the panel."
  - "The handler shapes the reconcile result into a small counts-only dict; the raw product list (and any checkout_url) never reaches result_json."
  - "The dispatch-table registration test runs under @pytest.mark.anyio rather than as a plain sync def, because _build_cog's tick.start monkeypatch only reaches the class-level Loop template, not the per-instance copy discord.py's tasks.loop descriptor creates in __init__."

patterns-established:
  - "_handle_jinxxy_sync is the template for any future action-queue handler that must map exceptions to a fixed category before action_queue.fail ever sees them."

requirements-completed: [JINX-01]

# Metrics
duration: 8min
completed: 2026-07-25
---

# Phase 8 Plan 05: Jinxxy Sync Queue Dispatch Summary

**The action queue now dispatches `jinxxy_sync` to `JinxxyCog._run_sync_guarded(source="panel")`, returning a shaped counts-only result and mapping every failure (including a missing cog) to one of the three fixed D-10 bilingual categories.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-25T08:54:21Z
- **Completed:** 2026-07-25T09:01:55Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `jinxxy_sync` as the sixth entry in `ActionQueueCog._dispatch`, alongside the existing `noop`/gallery/review kinds.
- `_handle_jinxxy_sync` resolves `JinxxyCog` via `get_cog("Jinxxy")` (the `GroupCog` `name=` kwarg, not the class name) and delegates entirely to `_run_sync_guarded(source="panel", actor_name=...)` — no sync logic, lock, or announce call is reimplemented.
- Every exception the handler can raise — a missing cog or any `_run_sync_guarded` failure — is mapped through `sync_error_category()` before it reaches `action_queue.fail`, so the panel only ever sees one of the three fixed bilingual categories.
- A collision (`{"already": True}`) completes as a benign success; a real result is shaped into `{"already", "changed", "added", "updated", "removed", "products"}` counts, never the raw product list.
- Added 7 tests covering registration, shaped-count success, no-raw-product-payload, moot collision, missing actor name, and both category-mapped failure paths (upstream `JinxxyAPIError` and a missing cog).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add `_handle_jinxxy_sync` and register the `jinxxy_sync` dispatch kind** - `758bc49` (feat)
2. **Task 1 follow-up: map a missing cog through the D-10 category too** - `40a06a0` (fix, same task)
3. **Task 2: Dispatch tests for the `jinxxy_sync` kind** - `3d5f0ce` (test)

## Files Created/Modified

- `cogs/action_queue_worker.py` - Adds the `jinxxy_sync` dispatch entry and `_handle_jinxxy_sync`, which resolves `JinxxyCog`, calls only `_run_sync_guarded`, shapes the result to counts, and maps every failure to a fixed D-10 category.
- `tests/test_action_queue_cog.py` - Adds 7 tests covering the dispatch table, shaped counts, no-raw-payload, collision, both failure categories, and a missing actor name.

## Decisions Made

- Moved the `get_cog("Jinxxy")` lookup and its missing-cog `RuntimeError` inside the `try` block (rather than before it, as the plan's numbered steps read literally) so that failure is also mapped through `sync_error_category()` to the generic D-10 bucket — required by the plan's own Task 2 test spec (`test_jinxxy_sync_without_the_cog_loaded_fails_with_bilingual_copy`), which asserts the recorded error is the generic category, not the internal "no está cargado" wording.
- Kept the register-in-dispatch test async (`@pytest.mark.anyio`) instead of a plain `def`, matching every other test in the file — see Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing-cog error was not mapped through the D-10 category**
- **Found during:** Task 1 (writing `_handle_jinxxy_sync`), confirmed against Task 2's own test spec
- **Issue:** The plan's action steps, read literally, place the `get_cog("Jinxxy")` lookup and its `RuntimeError` before the `try`/`except` that calls `sync_error_category`. That would let the internal "JinxxyCog no está cargado · JinxxyCog is not loaded" string reach `action_queue.fail` and the panel unmapped — directly contradicted by the plan's own Task 2 test (`test_jinxxy_sync_without_the_cog_loaded_fails_with_bilingual_copy`), which requires the recorded error to be the generic D-10 category.
- **Fix:** Moved the cog lookup and its raise inside the `try` block so any exception — missing cog or a guarded-wrapper failure — is mapped through `sync_error_category()` before `_handle_jinxxy_sync` re-raises.
- **Files modified:** `cogs/action_queue_worker.py`
- **Verification:** All 6 acceptance-criteria greps from Task 1 still pass after the restructuring (`jinxxy_sync` dispatch entry, single `get_cog("Jinxxy")` line, no `get_cog("JinxxyCog")`, exactly 2 `sync_error_category` lines, single `_run_sync_guarded(source="panel"` line, no `_announce`/`_run_sync()`); `test_jinxxy_sync_without_the_cog_loaded_fails_with_bilingual_copy` passes.
- **Committed in:** `40a06a0` (fix, immediately following the Task 1 feat commit)

**2. [Rule 3 - Blocking] Dispatch-table registration test could not run as a plain synchronous `def`**
- **Found during:** Task 2 (writing `test_jinxxy_sync_is_registered_in_the_dispatch_table`)
- **Issue:** The plan specifies this as "a synchronous test." Run as a plain `def`, `_build_cog(...)` raised `RuntimeError: no running event loop` inside `ActionQueueCog.__init__`'s `self._tick.start()`. `_build_cog`'s `monkeypatch.setattr(ActionQueueCog._tick, "start", ...)` patches the class-level `Loop` template, but discord.py's `tasks.loop` descriptor creates a fresh per-instance `Loop` copy on first attribute access inside `__init__` and calls the REAL (unpatched) `start()` on that copy, which unconditionally calls `asyncio.create_task(...)`. Every other test in the file is `@pytest.mark.anyio async def`, so a running loop is always present when they instantiate the cog; this is the only place the pre-existing helper's ineffective patch was ever exercised without one.
- **Fix:** Wrote the test as `@pytest.mark.anyio async def`, matching the file's established idiom and every other `_build_cog` call site. The assertion itself (`"jinxxy_sync" in cog._dispatch`) is unchanged and still runs with no `_run_once` call.
- **Files modified:** `tests/test_action_queue_cog.py`
- **Verification:** `pytest tests/test_action_queue_cog.py -k jinxxy -v` — 7 passed, including this test.
- **Committed in:** `3d5f0ce` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking).
**Impact on plan:** No behavior, scope, or artifact changes beyond what the plan's own threat model and Task 2 test spec already required. The registration test's async marker is a test-infrastructure adaptation only; the dispatch-table assertion itself is unchanged.

## Issues Encountered

None beyond the two auto-fixed items above.

## User Setup Required

None - no packages, credentials, environment variables, or external services were added.

## Verification

- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue_cog.py -v` — 24 passed (17 pre-existing + 7 new).
- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue_cog.py -k jinxxy -v` — 7 passed.
- `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` (full suite) — 852 passed.
- `python -c "import json; from cogs import action_queue_worker"` — exit 0, no circular import.
- Structural grep checks: exactly one `"jinxxy_sync": self._handle_jinxxy_sync` line; exactly one `get_cog("Jinxxy")` line; zero `get_cog("JinxxyCog")` lines; exactly two `sync_error_category` lines (import + raise); exactly one `_run_sync_guarded(source="panel"` line; zero `_announce`/`_run_sync()` lines.
- Post-commit deletion audit: `git diff --diff-filter=D --name-only HEAD~1 HEAD` empty after both commits — no unintended file deletions.

## Self-Check: PASSED

- FOUND: `cogs/action_queue_worker.py` contains `_handle_jinxxy_sync` and the `jinxxy_sync` dispatch entry.
- FOUND: `tests/test_action_queue_cog.py` contains the 7 new `jinxxy_sync` tests.
- FOUND commit `758bc49` in `git log --oneline --all`.
- FOUND commit `40a06a0` in `git log --oneline --all`.
- FOUND commit `3d5f0ce` in `git log --oneline --all`.

## Next Phase Readiness

- Plan 08-06 (the `/jinxxy` panel page) can enqueue `jinxxy_sync` via `action_queue.enqueue_deduped` and poll `/api/actions/{id}` to render the shaped counts dict (`already`/`changed`/`added`/`updated`/`removed`/`products`) directly — no further shaping needed on the app side.
- Every `jinxxy_sync` failure the panel will ever see is one of the three fixed D-10 bilingual categories; no upstream Jinxxy/GitHub detail can leak through this path.
- No blockers remain.

---
*Phase: 08-jinxxy-manual-sync*
*Completed: 2026-07-25*
