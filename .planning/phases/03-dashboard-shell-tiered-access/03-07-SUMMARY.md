---
phase: 03-dashboard-shell-tiered-access
plan: 07
subsystem: api
tags: [fastapi, jinja2, tiered-access, rbac, sqlite, dashboard-shell]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access (plan 03)
    provides: core/db.py bot_heartbeat/jinxxy_sync_status/activity_log tables + init/set/get helpers
  - phase: 03-dashboard-shell-tiered-access (plan 05)
    provides: app/deps.py require_manager/_resolve_roles/TierForbidden, per-tier OAuth redirect
  - phase: 03-dashboard-shell-tiered-access (plan 06)
    provides: app/templates _dashboard_base.html/_sidebar.html/overview.html/module_stub.html/forbidden.html
provides:
  - "app/main.py routes: GET /overview, /gallery, /reviews, /reminders, /jinxxy, /meetings (require_manager)"
  - "app/main.py: GET /api/overview/status (require_manager, live heartbeat + last-sync + recent-activity JSON)"
  - "app/main.py: lifespan defensively inits bot_heartbeat/jinxxy_sync_status/activity_log"
  - "app/main.py::_auth_html_or_json: TierForbidden branch + unified /admin/settings Manager-403 branch, both rendering forbidden.html in-shell (D-16)"
affects: ["04 (Settings shell migration reuses the same dashboard-shell chrome/route pattern)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared status-payload builder (_build_overview_status/_read_overview_status) feeds
      both the /overview page's first-paint seed and /api/overview/status's 30s poll —
      one code path, byte-identical JSON shape, no drift between initial render and poll."
    - "All-locked fallback roles dict (_NO_TIER_ROLES) for exception-handler renders of
      forbidden.html, since the handler never has a resolved tier for a denied caller
      without a second live Discord role read."

key-files:
  created: []
  modified:
    - app/main.py
    - tests/test_app_dashboard.py

key-decisions:
  - "_auth_html_or_json's forbidden.html branches pass an all-False/all-locked roles
    dict rather than re-deriving the caller's real tiers (which would mean a second
    live Discord REST read purely to render an error page) — the sidebar still renders
    correctly (every section locked), just without knowing which specific tiers the
    denied caller actually holds."
  - "Overview/module-stub routes each hit core.db via run_in_threadpool per request
    (heartbeat read for module stubs' footer chip, heartbeat+sync+activity for
    Overview) rather than a request-scoped cache — matches the existing api_presence/
    settings_page precedent of no caching layer over sqlite reads in this app."

requirements-completed: [SHELL-01, SHELL-02, ACCESS-01, ACCESS-02, ACCESS-03]

# Metrics
duration: 25min
completed: 2026-07-21
---

# Phase 3 Plan 07: Dashboard Route Wiring + Tiered Access Summary

**Wired the six `require_manager`-gated dashboard-shell routes, a tier-gated `/api/overview/status` JSON endpoint, and an in-shell `forbidden.html` 403 (including a unified D-16 render for a Manager hitting the owner-only `/admin/settings`) into `app/main.py`, turning Plan 01's five RED dashboard tests GREEN with no regression in the 663-test full suite.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-21T19:35:00-06:00 (approx, first Read)
- **Completed:** 2026-07-21T19:53:08-06:00
- **Tasks:** 3 completed
- **Files modified:** 2 (`app/main.py`, `tests/test_app_dashboard.py`)

## Accomplishments
- `lifespan()` now defensively initializes `bot_heartbeat`/`jinxxy_sync_status`/`activity_log` in the same try/except as the pre-existing presence/view_counts init (Pitfall 6) — the app never 500s reading Overview data on a cold/fresh database.
- `_auth_html_or_json` gained two new branches (checked before the existing `login.html` fallback): a `TierForbidden` branch rendering `forbidden.html` with `required_tier`, and a unified branch that renders the SAME `forbidden.html` (hardcoded `required_tier="owner"`) for any 403 landing on `/admin/settings` — so a Manager clicking the locked Settings nav item sees the bilingual "needs owner access" dead end (D-16), never `login.html`'s wrong-audience editor-only copy. `require_owner` itself is byte-identical/unchanged.
- Six new routes — `/overview` (renders `overview.html`, seeded with live status), `/gallery`/`/reviews`/`/reminders`/`/jinxxy`/`/meetings` (render `module_stub.html` with that module's accent/icon/label) — all `Depends(require_manager)`, each passing `roles` + `active_section` so `_sidebar.html` computes lock icons server-side (D-14).
- `GET /api/overview/status` (`require_manager`-gated, NOT public unlike `api_presence`) reuses the exact `_build_overview_status`/`_read_overview_status` helpers the `/overview` route's first paint is seeded from — Alpine's 30s poll (D-12) gets a byte-identical shape, and both degrade gracefully to `online=False`/null fields/`activity=[]` on an empty database rather than 500ing.
- Full local suite: 663 passed (up from 658 passed / 5 failed at the end of Plan 05) — the five Wave-1 RED dashboard tests (`test_sidebar_renders_seven_sections`, `test_overview_shows_status_tiles`, `test_owner_full_access`, `test_manager_operational_access_settings_403`, `test_editor_only_locked_out_of_dashboard`) are now GREEN, plus the previously-passing `test_manager_cannot_edit_mapping` stayed green throughout.

## Task Commits

Each task was committed atomically:

1. **Task 1: lifespan table init + TierForbidden handler branch + imports** - `9d4ef7b` (feat)
2. **Task 2: The six section routes (require_manager, roles + active_section context)** - `6295dff` (feat)
3. **Task 3: /api/overview/status JSON endpoint (require_manager)** - `43cf61e` (feat)

## Files Created/Modified
- `app/main.py` - Imports `require_manager`/`TierForbidden`; `lifespan()` inits the three Overview tables; `_auth_html_or_json` gains the `TierForbidden` + unified-Settings-403 branches (plus the `_NO_TIER_ROLES` fallback fix, see Deviations); new `_dashboard_asset_v`/`_compute_online`/`_compute_uptime`/`_build_overview_status`/`_read_overview_status`/`_bot_online`/`_MODULE_SECTIONS`/`_module_stub_page` helpers; six new `GET` routes (`/overview`, `/gallery`, `/reviews`, `/reminders`, `/jinxxy`, `/meetings`) and `GET /api/overview/status`.
- `tests/test_app_dashboard.py` - Fixed `test_overview_shows_status_tiles`'s seed calls to match `core/db.py`'s actual `set_heartbeat`/`set_jinxxy_sync_status` signatures (Plan 03-03), and mocked `app.main._fetch_current_entry` in `test_editor_only_locked_out_of_dashboard`'s `GET /editor` assertion so it doesn't depend on live GitHub network access.

## Decisions Made
- Deferred `bot_version` to `module_stub.html`/`overview.html`'s existing `{{ bot_version | default('1') }}` Jinja fallback rather than inventing a version-tracking mechanism — no version source exists yet in this codebase, and the UI-SPEC/03-06-SUMMARY only flagged `bot_online`/`bot_version` as render-contract vars, not a hard requirement to supply both explicitly on every render.
- `_bot_online()` re-reads `get_heartbeat` per module-stub-page request (rather than sharing the Overview route's already-read value) since the two code paths never run in the same request — a second lightweight sqlite SELECT per stub-page load is negligible and keeps each route's logic self-contained.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `forbidden.html`'s sidebar include crashed with `jinja2.UndefinedError` on both new branches**
- **Found during:** Task 2/3 verification (manually exercising the real `TierForbidden` and Manager-Settings-403 paths, not just the `dependency_overrides`-based pytest paths)
- **Issue:** `forbidden.html` extends `_dashboard_base.html`, which `{% include %}`s `_sidebar.html` — that partial unconditionally reads `roles.is_owner`/`.is_manager` to compute lock icons (D-14). Task 1's two `forbidden.html` renders in `_auth_html_or_json` didn't pass a `roles` context key at all, so a real 403 (not the test's dependency-override bypass, which routes through the plain `login.html` fallback instead) turned into an unhandled 500 instead of the intended in-shell 403 page.
- **Fix:** Added a module-level `_NO_TIER_ROLES = {"is_owner": False, "is_manager": False, "is_editor": False}` fallback and passed it as `roles` in both `forbidden.html` `TemplateResponse` calls — re-deriving the caller's actual tiers here would require a second live Discord role read purely to render an error page, so an all-locked default was chosen (correct in spirit: a denied caller sees every section as locked).
- **Files modified:** `app/main.py`
- **Verification:** Manually exercised both real code paths via `TestClient` with `require_owner`/`require_manager` overridden to actually raise (not bypass) — both now render 403 with the correct bilingual `forbidden.html` copy and no exception; full suite stayed green (663 passed).
- **Committed in:** `6295dff` (Task 2 commit, since discovered while verifying Task 2's routes)

**2. [Rule 1 - Bug] `tests/test_app_dashboard.py`'s `core_db.set_heartbeat`/`set_jinxxy_sync_status` seed calls didn't match the actual `core/db.py` signatures**
- **Found during:** Task 3 verification (`test_overview_shows_status_tiles`)
- **Issue:** The Wave-0 test called `core_db.set_heartbeat(member_count=42, latency_ms=50)` and `core_db.set_jinxxy_sync_status(ok=True, product_count=10)`, but Plan 03-03 (landed after Plan 01 wrote this test) implemented `set_heartbeat(latency_ms, started_at_utc, guild_member_count, loaded_cogs)` and `set_jinxxy_sync_status(ok, product_count, error)` — all positional/required, with a `guild_member_count` param name, not `member_count`. This is the same class of test/implementation interface drift documented and auto-fixed in `03-05-SUMMARY.md`.
- **Fix:** Updated the seed calls to the real signatures (`guild_member_count=42`, explicit `started_at_utc`/`loaded_cogs`/`error=None`).
- **Files modified:** `tests/test_app_dashboard.py`
- **Verification:** `test_overview_shows_status_tiles` passes; full suite 663 passed.
- **Committed in:** `43cf61e` (Task 3 commit)

**3. [Rule 1 - Bug] `test_editor_only_locked_out_of_dashboard`'s `GET /editor` assertion made a real, unmocked GitHub network call**
- **Found during:** Task 2 verification
- **Issue:** `require_editor`-gated `/editor` fetches the caller's live `editors.json` entry via `github_publish._fetch_json` (a real HTTPS call). Every other test in the repo exercising this route (`tests/test_app_editor.py`) mocks `app.main._fetch_current_entry` for isolation; this Wave-0 test didn't, so it 401'd against the real GitHub API in this environment instead of testing the tier-gating logic it's meant to pin.
- **Fix:** Added a `monkeypatch` fixture parameter and mocked `app.main._fetch_current_entry` with a fake entry, matching `tests/test_app_editor.py::test_editor_page_renders_slug_field`'s established pattern.
- **Files modified:** `tests/test_app_dashboard.py`
- **Verification:** `test_editor_only_locked_out_of_dashboard` passes without network access; full suite 663 passed.
- **Committed in:** `6295dff` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 test/implementation interface drift, 1 real-path template-context bug)
**Impact on plan:** All three were necessary for the plan's own stated verification to hold (the 5 RED tests passing + full suite green) and for the real (non-test-override) request paths to actually work as designed — not scope creep beyond the plan's `<must_haves>`.

## Issues Encountered
None beyond the three deviations documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All five Plan 01 RED dashboard tests (SHELL-01/02, ACCESS-01/02/03) are GREEN; ACCESS-04's `test_manager_cannot_edit_mapping` stayed green throughout (pre-existing `require_owner` gate on `/admin/settings` POST already covered it).
- Full local suite: 663 passed, 0 failed, 0 regressions.
- `app/main.py` now exposes the complete dashboard-shell surface (`/overview`, `/gallery`, `/reviews`, `/reminders`, `/jinxxy`, `/meetings`, `/api/overview/status`) that Phase 4's Settings-shell migration and later phases' CRUD flows (Phases 6-9) will extend — the module-stub pages are intentionally inert placeholders, ready to be replaced route-by-route without touching the shared `require_manager`/`_sidebar.html`/`forbidden.html` machinery.
- No blockers.

---
*Phase: 03-dashboard-shell-tiered-access*
*Completed: 2026-07-21*

## Self-Check: PASSED

- FOUND: app/main.py
- FOUND: tests/test_app_dashboard.py
- FOUND: .planning/phases/03-dashboard-shell-tiered-access/03-07-SUMMARY.md
- FOUND: 9d4ef7b (Task 1 commit)
- FOUND: 6295dff (Task 2 commit)
- FOUND: 43cf61e (Task 3 commit)
- FOUND: 4beb484 (SUMMARY.md commit)
