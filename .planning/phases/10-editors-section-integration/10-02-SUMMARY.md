---
phase: 10-editors-section-integration
plan: 02
subsystem: auth
tags: [fastapi, session-security, tier-gate, slug-validation]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access
    provides: "_resolve_roles/require_manager 3-tier owner/Manager/editor union resolver, TierForbidden/forbidden.html rendering"
  - phase: 10-editors-section-integration (10-01)
    provides: "RED regression tests pinning the Pitfall-1 session-clear bug and the widened reserved-slug set"
provides:
  - "GET / and GET /editor gate on _resolve_roles with a TierForbidden(required_tier='editor') branch — a locked nav click from a non-editor owner/Manager now renders forbidden.html with the session intact, never login.html with the session cleared"
  - "editor_page sources identity from roles['discord_id']/request.session only (one live Discord role read per request, no second require_editor call) and passes roles + active_section='editor' to editor.html"
  - "Every POST editor mutation endpoint (/editor/save, /editor/image, /editor/media, /editor/audio, /editor/unpublish) stays on the byte-for-byte unchanged require_editor dependency (D-07 freeze)"
  - "RESERVED_SLUGS widened with en/es/gallery/store/fonts/build to close the public-site root-namespace collision (T-10-02)"
affects: [10-05-PLAN, 10-06-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "GET-route tier split: a route that must remain reachable-but-denyable for non-target tiers gates on _resolve_roles + an inline TierForbidden raise, while sibling POST endpoints stay on the narrower single-purpose dependency (require_editor) — avoids a second live role read and avoids the broader dependency's session-clearing side effect for a caller who is authenticated, just not in the target tier"

key-files:
  created: []
  modified:
    - app/main.py
    - core/editors_model.py

key-decisions:
  - "editor_page keeps require_editor imported (still used by the five POST mutation endpoints) and adds _resolve_roles as a second import — no change to require_editor itself"
  - "Dropped the handler's local owner_id/is_owner recomputation in favor of roles['is_owner'] (already resolved by the single _resolve_roles call), per the plan's Pitfall-2 discipline (exactly one Discord role read per request)"

patterns-established:
  - "Pattern: when a locked-but-visible nav item must dead-end without logging out an authenticated-but-wrong-tier caller, gate the GET route on _resolve_roles + inline TierForbidden rather than the narrower single-tier dependency that has a session-clearing side effect"

requirements-completed: [EDIT-01, EDIT-02]

# Metrics
duration: 20min
completed: 2026-07-30
---

# Phase 10 Plan 02: Split the GET /editor tier-gate and widen RESERVED_SLUGS Summary

**GET / and GET /editor now gate on `_resolve_roles` with an inline `TierForbidden("editor")` raise instead of `require_editor`, so a locked-nav click from a non-editor owner/Manager 403s via `forbidden.html` with the session intact rather than being logged out of the whole dashboard; `RESERVED_SLUGS` widened with `en/es/gallery/store/fonts/build` to protect the public site's root namespace before vanity URLs ship.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-30
- **Tasks:** 2/2 completed
- **Files modified:** 2

## Accomplishments
- Fixed the Pitfall-1 self-inflicted-logout defect (T-10-01, CRITICAL): a non-editor clicking the visible-but-locked "Editor" sidebar item no longer triggers `require_editor`'s `session.clear()` + `login.html`; it now renders the in-shell `forbidden.html` tier dead-end with the session cookie intact.
- Preserved the D-08 IDOR choke point and the one-live-role-read-per-request discipline (Pitfall 2): identity for `_fetch_current_entry` comes from `roles["discord_id"]`, and the slug fallback comes from `request.session.get("slug")` — no second Discord role read, no client-supplied identity.
- Left all five POST editor mutation endpoints (`/editor/save`, `/editor/image`, `/editor/media`, `/editor/audio`, `/editor/unpublish`) byte-for-byte on the unchanged `require_editor` dependency (D-07 freeze) — verified via grep and the full `tests/test_app_editor.py` regression run.
- Widened `RESERVED_SLUGS` with the six public-site collision words (`en`, `es`, `gallery`, `store`, `fonts`, `build`) so an editor-chosen vanity slug can never shadow a real top-level public-site route (T-10-02) — a pure frozenset-literal change, no new validation logic.

## Task Commits

Each task was committed atomically:

1. **Task 1: Split the GET /editor tier-gate off the mutation gate (Pitfall 1/2 fix)** - `7d97183` (fix)
2. **Task 2: Widen RESERVED_SLUGS to cover the public-site root namespace** - `2d6d442` (fix)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `app/main.py` - `editor_page` (mounted at both `GET /` and `GET /editor`) now depends on `_resolve_roles` instead of `require_editor`; raises `TierForbidden(required_tier="editor")` when `not roles["is_editor"]`; sources identity from `roles`/session instead of a second `require_editor` call; drops the local `owner_id`/`is_owner` recomputation in favor of `roles["is_owner"]`; adds `"roles"` and `"active_section": "editor"` to the `editor.html` `TemplateResponse` context. Import list gains `_resolve_roles` from `app.deps`. No POST endpoint changed.
- `core/editors_model.py` - `RESERVED_SLUGS` frozenset widened from 12 to 18 entries, adding `en`, `es`, `gallery`, `store`, `fonts`, `build`. No change to `resolve_slug`/`normalize_slug` function bodies.

## Decisions Made
- Kept `require_editor` imported in `app/main.py` (it still gates the five POST mutation endpoints) and added `_resolve_roles` alongside it, rather than swapping the import — makes the diff obviously additive and keeps both dependencies visibly in use at their respective call sites.
- Followed the plan's explicit instruction to drop the handler's local `owner_id = config.DISCORD_USER_ID; is_owner = ...` recomputation and reuse `roles["is_owner"]` (already resolved inside the single `_resolve_roles` call) — avoids duplicating the same fail-closed 0/unset guard `_resolve_roles` already applies.

## Deviations from Plan

None - plan executed exactly as written. Both tasks match their `<action>`/`<acceptance_criteria>` blocks; no Rule 1-4 auto-fixes were needed.

## Issues Encountered

None. Ran the plan's own verification commands first to confirm RED (2 failed in `test_app_dashboard.py -k locked_editor_nav`, 6 failed in `test_editors_model.py -k reserved`), then confirmed GREEN after each task's edit, matching the pre-existing-state briefing exactly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 10-05 (editor.html shell wrap) can now proceed: `editor_page`'s `TemplateResponse` context already carries `roles` + `active_section="editor"`, the two keys `_dashboard_base.html`/`_sidebar.html` need — only the template's `{% extends %}` needs to change. The one remaining RED case in the full suite, `tests/test_app_editor.py::test_editor_page_renders_in_shell`, is exactly the marker this unblocks and is expected to stay RED until 10-05 lands.
- 10-06 (vanity route move) can rely on the now-widened `RESERVED_SLUGS` collision set.
- No blockers. Full repo test suite (`pytest tests/`) shows 888 passed / 1 intentionally-RED (the 10-05-deferred shell-wrap marker) with zero regressions elsewhere.

---
*Phase: 10-editors-section-integration*
*Completed: 2026-07-30*

## Self-Check: PASSED

All claimed files verified present (app/main.py, core/editors_model.py, 10-02-SUMMARY.md).
All claimed commit hashes verified present in git log (7d97183, 2d6d442).
