---
phase: 08-jinxxy-manual-sync
plan: 06
subsystem: api
tags: [fastapi, jinja2, sqlite, action-queue, dedupe, heartbeat, tdd]

# Dependency graph
requires:
  - phase: 08-jinxxy-manual-sync
    plan: 01
    provides: Widened Jinxxy status mirror and enqueue_deduped queue primitive
  - phase: 08-jinxxy-manual-sync
    plan: 02
    provides: OAuth-verified optional username in the Manager roles dict
provides:
  - Manager-gated Jinxxy page, status JSON, and deduped sync-trigger routes
  - Heartbeat-voided running status with never-synced and count reporting
  - Read-only, name-sorted store snapshot projection
  - Shared heartbeat staleness helpers for app routes
  - Generic action API exclusion for jinxxy_sync
affects: [08-05, 08-07, 08-08, jinxxy-panel, action-queue]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Module routers depend directly on require_manager for every route
    - App routes enqueue credentialed bot work through shared sqlite only
    - Persisted busy mirrors are voided when the authoritative process heartbeat is stale

key-files:
  created:
    - app/routers/jinxxy.py
    - tests/test_app_jinxxy.py
  modified:
    - app/deps.py
    - app/main.py

key-decisions:
  - "Keep jinxxy_sync out of the generic action allowlist so every panel trigger passes through enqueue_deduped."
  - "Derive actor_name only from the OAuth-backed roles username, with discord_id as the legacy-session fallback."
  - "Exclude raw sync errors and internal snapshot fields from Manager-facing payloads."
  - "Treat a persisted running flag as false whenever bot heartbeat freshness says the bot is offline."

patterns-established:
  - "compute_bot_online and bot_online in app/deps.py are the shared app-side liveness authority."
  - "Never-synced checks last_run_utc rather than row presence because mirror initialization can create an empty result row."
  - "A real module page defensively initializes every sqlite table it reads during app lifespan."

requirements-completed: [JINX-01]

# Metrics
duration: 11min
completed: 2026-07-25
---

# Phase 8 Plan 06: Jinxxy Panel Router Summary

**Managers can now read heartbeat-safe Jinxxy status and catalog data and enqueue one deduplicated sync action without exposing bot credentials or upstream errors to the app.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-25T03:42:23Z
- **Completed:** 2026-07-25T03:52:58Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Replaced the `/jinxxy` module stub with a real Manager-gated router exposing the page, ambient status JSON, and one-click sync POST.
- Enqueued `jinxxy_sync` exclusively through `enqueue_deduped`, preserving one pending/claimed row and OAuth-backed actor attribution.
- Added a safe status contract covering cold databases, mirror-only rows, last-run counts, source/actor, and heartbeat-voided running state without returning raw errors.
- Moved the dashboard heartbeat judgment into shared dependencies without changing its 90-second, timezone, or negative-age behavior.
- Added thirteen integration cases covering authorization, queue shape, pending/claimed dedupe, status semantics, stale heartbeat handling, and information-disclosure boundaries.

## Task Commits

Each task was committed atomically:

1. **Task 3: Jinxxy route integration tests** - `7955e70` (test)
2. **Task 1: Shared heartbeat staleness helpers** - `5424328` (refactor)
3. **Task 2: Jinxxy router, registration, and generic-action protection** - `61ccece` (feat)

The integration-test task ran first to preserve the required RED-before-GREEN sequence.

## Files Created/Modified

- `app/deps.py` - Exposes the shared heartbeat threshold, pure online computation, and async heartbeat reader.
- `app/main.py` - Registers the Jinxxy router, removes the stub, initializes the store snapshot defensively, and documents the generic allowlist exclusion.
- `app/routers/jinxxy.py` - Implements the three Manager-gated page/status/sync routes and safe product/status projections.
- `tests/test_app_jinxxy.py` - Proves enqueue attribution, pending/claimed dedupe, status shape, heartbeat voiding, raw-error exclusion, and Manager authorization.

## Decisions Made

- Kept the app credential-free: it only reads sqlite state and writes a typed queue row; it never imports or calls Jinxxy, GitHub, or Discord clients.
- Used `roles.get("username") or str(roles["discord_id"])` so attribution is trusted and remains non-empty for sessions issued before Plan 08-02.
- Returned only `name`, `price`, `category`, `nsfw`, `date`, and `checkout_url` from the snapshot projection, sorted case-insensitively by name.
- Preserved source, actor, and started-at metadata in the status response even when a stale heartbeat forces `running` to false.
- Excluded the raw `error` column from the JSON response.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Executed test Task 3 before implementation Tasks 1 and 2**

- **Found during:** Pre-execution TDD gate
- **Issue:** The plan listed integration tests after production implementation, conflicting with the mandatory failing-test-first protocol.
- **Fix:** Added and committed only the planned route tests first, observed the expected missing-route failures, then implemented Tasks 1 and 2.
- **Files modified:** `tests/test_app_jinxxy.py`
- **Verification:** Initial exact focused run reported `11 failed, 2 passed`; final focused run reported `13 passed`.
- **Committed in:** `7955e70`

**2. [Rule 2 - Missing Critical] Added app-side store snapshot initialization**

- **Found during:** Task 2 dashboard regression verification
- **Issue:** The former stub never read `store_snapshot`, so the app lifespan did not initialize it; the new real page would raise `sqlite3.OperationalError` when the app started before the bot.
- **Fix:** Added `db.init_store_state()` to the existing dual-process defensive lifespan initialization block.
- **Files modified:** `app/main.py`
- **Verification:** The exact Task 2 verifier changed from `2 failed, 12 passed` to `14 passed`.
- **Committed in:** `61ccece`

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical).
**Impact on plan:** Both changes enforce the plan’s TDD and cold-database requirements without expanding the route surface or credential boundary.

## Issues Encountered

- Task 1’s first verifier found one stale `_bot_online()` call in `/admin/settings`; a full legacy-symbol scan isolated it as the only missed reference. Replacing it with `bot_online()` produced `38 passed`.
- The plan’s route-list one-liner assumes every `app.routes` entry has `.path`. FastAPI 0.139 represents included routers as `_IncludedRouter` wrappers, so the exact command raises `AttributeError` even for pre-existing routers. Equivalent inspection through each wrapper’s `effective_candidates()` printed `['/jinxxy', '/jinxxy/status', '/jinxxy/sync']`; all three paths were also exercised successfully through `TestClient`.

## User Setup Required

None - no packages, credentials, environment variables, or external services were added.

## Verification

- RED gate: `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_jinxxy.py -v` reported `11 failed, 2 passed` before production changes.
- Task 1 exact verifier: `tests/test_app_dashboard.py tests/test_app_auth.py -q` reported `38 passed, 3 warnings`.
- Task 2 exact verifier: `tests/test_app_dashboard.py tests/test_app_actions.py -q` reported `14 passed, 3 warnings`.
- Task 3/final focused verifier: `tests/test_app_jinxxy.py -v` reported `13 passed, 3 warnings`.
- Dedupe selector: `tests/test_app_jinxxy.py::test_dedupe_at_enqueue -x` reported `1 passed`.
- Stale-heartbeat selector: `tests/test_app_jinxxy.py -k stale_heartbeat -v` reported `1 passed, 12 deselected`.
- Full suite: `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` reported `828 passed, 4 warnings`.
- Structural checks found exactly three `Depends(require_manager)` routes, one `enqueue_deduped` call, no plain enqueue call, no Jinxxy stub call, and no `jinxxy_sync` member in `_ALLOWED_KINDS`.
- FastAPI 0.139-compatible route inspection reported exactly `['/jinxxy', '/jinxxy/status', '/jinxxy/sync']`.
- Changed-file audit contains only the four files listed by the plan before this summary; `STATE.md` and `ROADMAP.md` were not modified.

## Self-Check: PASSED

## Next Phase Readiness

- Plan 08-07 can replace the fallback template with the full Jinxxy status card, one-click button, and read-only product table using the seeded `sync` and `products` context.
- Plan 08-05 can consume the queued `{"actor_name": ...}` payload and dispatch it through the guarded bot-side sync wrapper.
- No functional blockers remain; the only noted mismatch is the plan’s obsolete FastAPI route-introspection one-liner.

---
*Phase: 08-jinxxy-manual-sync*
*Completed: 2026-07-25*
