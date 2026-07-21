---
phase: 02-owner-settings-panel
plan: 02
subsystem: auth
tags: [fastapi, session-auth, authorization, tdd]

# Dependency graph
requires:
  - phase: 02-owner-settings-panel (plan 02-01)
    provides: core/settings.py get/set/all_for_ui/validate_only data layer (not consumed by this plan directly, but the phase's foundation)
provides:
  - "require_owner FastAPI dependency in app/deps.py, gating /admin/settings to config.DISCORD_USER_ID"
  - "_OWNER_FORBIDDEN_COPY bilingual (ES/EN) 403 copy constant"
affects: [02-owner-settings-panel plan 02-04 (POST /admin/settings), 02-03 (GET /admin/settings), any future plan wiring Depends(require_owner)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-closed authorization guard: explicit `if not owner_id: raise 403` runs BEFORE any identity comparison, so a 0/unset sentinel config value can never accidentally authorize"
    - "str()-normalized identity comparison across an int-typed config value and a str-typed session value"
    - "Session-only identity resolution (D-08 IDOR discipline) reused from require_editor for a second, narrower gate"

key-files:
  created: []
  modified:
    - app/deps.py
    - tests/test_app_auth.py

key-decisions:
  - "require_owner returns 403 (never 401) for a non-owner — the caller is already an authenticated editor by the time they reach this dependency; 'authenticated but not the owner' is a strict authorization denial, not a login gate"
  - "Followed RESEARCH.md's exact require_owner body (Pattern 1 / Code Examples) verbatim — no deviation from the mirrored require_editor shape"

patterns-established:
  - "require_owner as the second auth choke-point in app/deps.py, alongside require_editor, both reading identity from request.session only"

requirements-completed: [PANEL-01]

# Metrics
duration: 15min
completed: 2026-07-21
---

# Phase 2 Plan 2: require_owner Dependency Summary

**`require_owner` FastAPI dependency added to `app/deps.py`, gating the future `/admin/settings` surface to `config.DISCORD_USER_ID` with an explicit fail-closed guard on the `0`/unset default and str-normalized identity comparison, built test-first with 4 dedicated unit tests.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-21T00:00:00Z (approx, worktree execution)
- **Completed:** 2026-07-21
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 2

## Accomplishments
- `require_owner(request: Request) -> dict` in `app/deps.py`: 403s when `DISCORD_USER_ID` is `0`/unset (fail-closed, checked BEFORE any comparison), 403s for a real editor who isn't the owner, 403s for an empty session, returns `{"discord_id": ...}` for the matching owner
- Comparison is `str()`-normalized on both operands so the int-typed `config.DISCORD_USER_ID` correctly admits the str-typed `session["discord_id"]`
- `_OWNER_FORBIDDEN_COPY` bilingual (ES first, `—`, EN second) 403 copy constant, matching the house style of `_FORBIDDEN_COPY`
- `require_editor` and the OAuth login flow (`app/auth.py`) are untouched — confirmed via `git diff` (only the module docstring header and additive lines changed)
- 4 new unit tests in `tests/test_app_auth.py` mirroring the existing `require_editor` test style (`_FakeRequest`, `monkeypatch.setattr(config, ...)`, `asyncio.run(deps.require_owner(req))`, `pytest.raises(HTTPException)`)

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: RED — require_owner unit tests** - `e85b2c5` (test)
2. **Task 2: GREEN — implement require_owner (fail-closed, str-normalized)** - `c15dc30` (feat)

**Plan metadata:** (this commit, following)

_No REFACTOR commit — the GREEN implementation matched RESEARCH.md's recommended shape exactly; no cleanup was needed._

## Files Created/Modified
- `app/deps.py` - Added `import config`, `_OWNER_FORBIDDEN_COPY`, and `async def require_owner(request: Request) -> dict`
- `tests/test_app_auth.py` - Added 4 tests: `test_require_owner_403_when_owner_id_unset`, `test_require_owner_200_for_matching_owner`, `test_require_owner_403_for_non_owner_session`, `test_require_owner_403_without_session`

## Decisions Made
- 403 (not 401) for a non-owner session — matches PANEL-01's exact wording and the fact that the caller already passed the editor-role login gate before ever reaching `require_owner`
- No new public API surface beyond `require_owner` + `_OWNER_FORBIDDEN_COPY` — the dependency is intentionally minimal, following `require_editor`'s existing shape verbatim per RESEARCH.md Pattern 1

## Deviations from Plan

None - plan executed exactly as written. The RESEARCH.md Code Examples section provided a ready-to-adapt `require_owner` body and three of the four test bodies; the fourth (empty-session case) was added directly from the plan's `<behavior>` spec, following the same style.

## Issues Encountered

None. RED phase failed for the correct reason (`AttributeError: module 'app.deps' has no attribute 'require_owner'`); GREEN phase passed on the first implementation attempt with no debugging needed.

## TDD Gate Compliance

Gate sequence verified in git log:
- RED: `e85b2c5 test(02-02): add failing require_owner unit tests` — present, precedes GREEN
- GREEN: `c15dc30 feat(02-02): implement require_owner (fail-closed, str-normalized)` — present, follows RED
- REFACTOR: none (not needed)

Both required gates present and correctly ordered. No violations.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`require_owner` is ready to be wired as `Depends(require_owner)` on the `GET`/`POST /admin/settings` routes in later plans of this phase (02-03, 02-04). Full test suite (621 tests) passes, including all pre-existing `require_editor` tests unmodified. No blockers.

---
*Phase: 02-owner-settings-panel*
*Completed: 2026-07-21*
