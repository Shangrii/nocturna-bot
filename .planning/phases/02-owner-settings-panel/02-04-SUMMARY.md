---
phase: 02-owner-settings-panel
plan: 04
subsystem: api
tags: [fastapi, sqlite, jinja2, tdd, integration-tests]

# Dependency graph
requires:
  - phase: 02-owner-settings-panel (plan 02-01)
    provides: "core/settings.py::all_for_ui() render metadata, validate_only() dry-run"
  - phase: 02-owner-settings-panel (plan 02-02)
    provides: "require_owner dependency in app/deps.py"
  - phase: 02-owner-settings-panel (plan 02-03)
    provides: "app/templates/settings.html expecting {groups, asset_v} context"
provides:
  - "GET /admin/settings — owner-gated, server-renders settings.all_for_ui() into settings.html"
  - "POST /admin/settings — owner-gated, atomic two-pass validate_only-then-set write"
  - "editor_page's TemplateResponse context now includes is_owner (D-12), wiring the Wave-2 owner link"
affects: [phase-2-verification, future settings-panel-polish plans]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-pass atomic multi-field validation: validate_only every key into a dict first, only set() any key once the whole batch passes (D-04/D-05) — first per-field multi-error POST pattern in this codebase"
    - "is_owner context flag computed with the same fail-closed 0/unset guard as require_owner, kept in the route handler rather than the template (template only branches on the boolean)"

key-files:
  created:
    - tests/test_app_settings.py
  modified:
    - app/main.py

key-decisions:
  - "Followed 02-PATTERNS.md's exact target code for both routes verbatim (no deviation) — the pattern map had already resolved the one genuinely novel piece (the per-field multi-error validation loop)"
  - "Non-owner POST test asserts 403 for the deny path without needing to reach the two-pass validation logic at all — require_owner runs as a FastAPI dependency before the handler body executes"

patterns-established:
  - "Settings-panel POST atomicity: validate_only(key, value) in a first pass building an errors map; 422+errors and zero writes if any field fails; set(key, value) in a second pass only when the whole batch is clean"

requirements-completed: [PANEL-01, PANEL-02, PANEL-03, PANEL-04]

# Metrics
duration: 15min
completed: 2026-07-21
---

# Phase 2 Plan 4: Settings Panel Routes Summary

**`GET`/`POST /admin/settings` wired to `app/main.py`, both gated by `Depends(require_owner)` — GET server-renders `settings.all_for_ui()` into `settings.html`, POST does an atomic two-pass `validate_only`-then-`set` write that returns a per-field `{errors:{KEY:reason}}` map with zero writes on any invalid field; `editor_page` now passes `is_owner` so the Wave-2 owner link renders.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-07-21T12:10:00Z (approx, worktree execution)
- **Completed:** 2026-07-21T12:27:46Z
- **Tasks:** 3 (TDD RED, GREEN GET, GREEN POST)
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- `tests/test_app_settings.py` (NEW, 8 tests): a `client` fixture mirroring `test_app_editor.py`'s dummy-OAuth-config + `TestClient` pattern, additionally pointing `config.DB_PATH` at a `tmp_path` sqlite file and calling `settings.seed_defaults()` since these routes hit the real store, not a mock
- `GET /admin/settings`: owner-gated, renders `settings.html` with `{"groups": settings.all_for_ui(), "asset_v": <mtime>}` — same cache-buster idiom as `editor_page`; a non-owner gets 403 with zero settings data in the body; the owner's body contains grouped markup and no secret (BOT_TOKEN/GITHUB_PAT/JINXXY_API_KEY/SESSION_SECRET/DB_PATH all absent)
- `POST /admin/settings`: owner-gated, two-pass atomic write — `validate_only` every submitted key first (collecting `SettingRejected.reason` into an `errors` map), 422+errors with **zero writes** if any field is invalid, `set()` on every key only once the whole batch validates; a valid POST returns `{ok: true, message}` and the value is immediately visible to `settings.get` (PANEL-04 read-at-use)
- `editor_page` now computes `is_owner = bool(config.DISCORD_USER_ID) and str(ident["discord_id"]) == str(config.DISCORD_USER_ID)` (same fail-closed guard as `require_owner`) and includes it in the `TemplateResponse` context, so the `{% if is_owner %}`-guarded settings link built in 02-03 now actually renders for the owner
- Full repo suite: 638 passed (up from 630 baseline), including the 8 new integration tests

## Task Commits

Each task followed RED → GREEN:

1. **Task 1: RED — /admin/settings integration tests** - `04c7e2c` (test)
2. **Task 2: GREEN — GET /admin/settings + is_owner dashboard context** - `78d3fca` (feat)
3. **Task 3: GREEN — POST /admin/settings atomic validate-then-write** - `c819caf` (feat)

**Plan metadata:** (this SUMMARY commit, follows)

_No REFACTOR commit — both GREEN implementations matched 02-PATTERNS.md's target shape exactly; no cleanup was needed._

## Files Created/Modified
- `tests/test_app_settings.py` - NEW: 8 integration tests covering the require_owner gate (403 no data), GET render/secret-absence, atomic POST (valid persists, mixed valid/invalid writes nothing), the read-at-use round-trip, and bad-JSON/non-dict body handling
- `app/main.py` - `from app.deps import require_owner` + `from core import settings` added to imports; `_SETTINGS_SAVED_COPY`/`_SETTINGS_ERROR_COPY` bilingual copy constants; new `GET /admin/settings` (`settings_page`) and `POST /admin/settings` (`save_settings`) handlers; `editor_page` extended with the `is_owner` context flag

## Decisions Made
- Followed 02-PATTERNS.md's exact target code for both routes and the `is_owner` extension verbatim — no deviation needed since the pattern map had already resolved the one genuinely novel piece (the per-field multi-error validate-then-write loop) against `save_editor`'s existing "validate-fully-before-write" shape
- `_SETTINGS_ERROR_COPY` was added even though the server-side POST handler doesn't currently reference it directly (the `errors` map itself carries per-field reasons) — kept for symmetry with `settings.html`'s client-side toast text and as the natural home for a future generic settings-save-failure banner, matching this file's existing bilingual-copy-constants convention

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. RED phase failed for the correct reason (404 — routes not yet registered, an explicitly acceptable RED signal per the plan); both GREEN phases passed on the first implementation attempt with no debugging needed.

## TDD Gate Compliance

Gate sequence verified in git log:
- RED: `04c7e2c test(02-04): add failing test for /admin/settings gate, GET render, atomic POST` — present, precedes GREEN
- GREEN: `78d3fca feat(02-04): GET /admin/settings + is_owner dashboard context` — present, follows RED
- GREEN: `c819caf feat(02-04): POST /admin/settings atomic validate-then-write` — present, follows RED
- REFACTOR: none (not needed)

Both required gates present and correctly ordered. No violations.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The Phase 2 core value is now observable end-to-end: the owner can view and edit the bot's
safe operational settings from `/admin/settings`, validation gates every write atomically,
secrets never appear in the panel, and a saved value is immediately visible to the bot's
`settings.get` read-at-use path (verified directly in the round-trip test, not just by
inference from the store layer). This was the last plan in Phase 2's single wave-3 dependency
chain (02-01 → 02-02 → 02-03 → 02-04) — no blockers, full suite (638 tests) green.

## Self-Check: PASSED

- FOUND: tests/test_app_settings.py (8 tests, contains `client` fixture, `require_owner` override, `config.DB_PATH` tmp-path pointer, `settings.seed_defaults()`)
- FOUND: app/main.py (contains `@app.get("/admin/settings"`, `@app.post("/admin/settings")`, `Depends(require_owner)` x2, `from core import db, github_publish, settings`, `from app.deps import require_editor, require_owner`, `"is_owner": is_owner`, `_SETTINGS_SAVED_COPY`)
- FOUND commits 04c7e2c, 78d3fca, c819caf in `git log --oneline --all`
- `grep -c 'INSERT\|conn.execute' app/main.py` (excluding unrelated editor.css hits) → 0 matches in the new handlers — no raw SQL
- `grep -n 'validate_only' app/main.py` precedes `grep -n 'settings.set'` in the POST handler body — validate pass before write pass confirmed by reading the function
- `pytest tests/test_app_settings.py tests/test_app_editor.py tests/test_settings.py -x` → 57 passed
- `pytest` (full repo suite) → 638 passed (up from 630 baseline)

---
*Phase: 02-owner-settings-panel*
*Completed: 2026-07-21*
