---
phase: 03-dashboard-shell-tiered-access
plan: 05
subsystem: auth
tags: [fastapi, discord-oauth, tiered-access, rbac, settings-store]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access (plan 02)
    provides: manager_roles / editor_roles role_list keys in core/settings.py (no fallback_key)
provides:
  - app/auth.py::_fetch_member_roles(user_id) -> set[str] | None — single shared bot-token REST read
  - app/auth.py::has_editor_role(user_id) -> bool — reworked to read settings.get("editor_roles")
  - app/auth.py::callback — resolves owner/manager/editor tier union, admits any resolved tier
    (D-01), per-tier post-login redirect (/overview vs /editor), no cached tier in session
  - app/deps.py::_resolve_roles(request) -> dict — one live role read, tier union resolver
  - app/deps.py::require_manager — admits owner or Manager, raises TierForbidden otherwise
  - app/deps.py::TierForbidden(HTTPException) — carries .required_tier
affects: ["03-dashboard-shell-tiered-access plan 07 (routes wire require_manager + render
  forbidden.html from TierForbidden.required_tier)", "03-dashboard-shell-tiered-access plan 01
  (tests/test_app_dashboard.py's require_manager import now resolves; route-level 200/403
  assertions remain RED until plan 07 lands the routes)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared single-read role resolver: one bot-token REST call (_fetch_member_roles) feeds
      both has_editor_role and the deps.py tier resolver, avoiding an N+1 read per request"
    - "FastAPI Depends(..., use_cache=True) default relied on (not hand-rolled) to dedupe
      _resolve_roles within one request across multiple dependants"
    - "Owner tier resolved independently of the editable role mapping, evaluated before any
      role lookup, so a misconfigured/empty mapping can never lock out the owner"

key-files:
  created: []
  modified:
    - app/auth.py
    - app/deps.py
    - tests/test_app_auth.py

key-decisions:
  - "has_editor_role is now a thin wrapper over the shared _fetch_member_roles + settings.get(\"editor_roles\"),
    replacing the hardcoded config.ROLE_MODERATOR_ID check — an owner edit to editor_roles takes
    effect on the next request, no restart"
  - "ensure_draft/slug provisioning stays scoped to the editor tier only (is_editor branch) —
    an owner/manager-only login does not create an editors.json draft or store a slug in session"
  - "Updated tests/test_app_auth.py's has_editor_role/callback tests to mock the new
    _fetch_member_roles/settings.get seams instead of the retired config.ROLE_MODERATOR_ID
    hardcode — the old tests would otherwise silently target a default that no longer reflects
    live config, since core/settings.py's editor_roles default is baked in at import time from
    the ROLE_MODERATOR_ID env var, not read from config.ROLE_MODERATOR_ID at call time"
  - "Added three new callback tests (manager-tier redirect + no-draft guarantee, owner-tier
    redirect with zero roles) beyond the plan's stated behavior, to pin the per-tier redirect
    and editor-only-draft-provisioning invariants the plan's <behavior> block specifies"

patterns-established:
  - "Tier resolution helpers (_resolve_roles) return a plain dict of tier booleans, never an
    enum/cached value — every dependant re-derives what it needs from the same dict"

requirements-completed: [ACCESS-01, ACCESS-02, ACCESS-03, ACCESS-04]

# Metrics
duration: 20min
completed: 2026-07-22
---

# Phase 3 Plan 05: 3-Tier Owner/Manager/Editor Access Resolver Summary

**Generalized the single-role editor gate into an owner/Manager/editor union resolver: one shared bot-token REST read (`_fetch_member_roles`) now feeds both the reworked `has_editor_role` (reads the editable `editor_roles` setting) and a new `app/deps.py::_resolve_roles`/`require_manager`/`TierForbidden` stack, with the OAuth callback admitting any resolved tier and redirecting per-tier while never caching a tier in the session.**

## Performance

- **Duration:** 20 min
- **Started:** 2026-07-22T01:15:00Z
- **Completed:** 2026-07-22T01:35:07Z
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments
- `app/auth.py::_fetch_member_roles(user_id)` extracted as the single shared bot-token guild-role read (`None` on 404), used by both `has_editor_role` and (via `app/deps.py`) the new tier resolver — no N+1 Discord REST reads per protected page
- `has_editor_role` reworked into a thin wrapper checking the live role set against `settings.get("editor_roles")`, replacing the hardcoded `config.ROLE_MODERATOR_ID` constant (D-08) — an owner edit to the mapping now takes effect on the next request
- OAuth `callback` now resolves `is_owner` (hardcoded to `DISCORD_USER_ID`, independent of the mapping, D-04) plus `is_manager`/`is_editor` from one shared role read + `settings.get("manager_roles")`/`("editor_roles")`; admits a session for ANY resolved tier (D-01) and 403s only when none resolve; redirects owner/manager to `/overview` and editor-only to `/editor` (D-03/Pitfall 1, still a fixed server path, never a client `?next`); `ensure_draft`/slug provisioning stays scoped to the editor tier; the session stores only `discord_id` (+ `slug` for editors), never a tier (D-02)
- `app/deps.py` gained `_resolve_roles` (one live role read → `{discord_id, is_owner, is_manager, is_editor}`, 401 with no session, 403+session-clear on no resolved tier), `require_manager` (admits owner or Manager, else raises the new `TierForbidden`), and `TierForbidden(HTTPException)` carrying `.required_tier` — `require_owner`/`require_editor` bodies are byte-identical to before, so `/admin/settings` keeps its exact owner-only gate with no new self-elevation path (T-03-12)
- Updated `tests/test_app_auth.py`'s `has_editor_role`/callback tests to the new seams (`_fetch_member_roles`, `auth.settings.get`) and added coverage for the manager-tier redirect/no-draft guarantee and the owner-tier redirect independent of any role — full suite: 658 passed (the 5 `tests/test_app_dashboard.py` route-level failures are the expected Wave-1 RED signal for Plan 07's not-yet-built routes, per this plan's own `<verification>` note)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract _fetch_member_roles and rework has_editor_role + callback in app/auth.py** - `6cc9c5b` (test)
2. **Task 2: Add _resolve_roles, require_manager, and TierForbidden to app/deps.py** - `00ca5d0` (feat)

_Note: Task 1 is committed as `test(03-05)` because it bundles the app/auth.py rework together with the test-file updates required to keep tests/test_app_auth.py green against the new interface (see Deviations) — both changes landed together since the old tests directly asserted the retired hardcoded-role behavior._

## Files Created/Modified
- `app/auth.py` - Extracted `_fetch_member_roles`; reworked `has_editor_role` to read `editor_roles` from the settings store; reworked `callback` to resolve the owner/manager/editor tier union and redirect per-tier; added `_REDIRECT_MANAGER_TIER`/`_REDIRECT_EDITOR_TIER` constants
- `app/deps.py` - Added `TierForbidden`, `_resolve_roles`, `require_manager`; `require_owner`/`require_editor` left byte-identical
- `tests/test_app_auth.py` - Updated `has_editor_role` tests to mock the new `_fetch_member_roles`/`settings.get` seams instead of the retired `config.ROLE_MODERATOR_ID` hardcode; added `test_fetch_member_roles_*`, reworked `_patch_callback_happy` to mock `_fetch_member_roles` instead of `has_editor_role`, and added manager-tier/owner-tier redirect + no-draft-for-manager-only tests

## Decisions Made
- `has_editor_role`'s comparison set is read fresh from `settings.get("editor_roles")` on every call rather than cached — mirrors the read-at-use discipline already established by the rest of the settings store (Phase 1)
- `ensure_draft`/slug provisioning is gated on `is_editor` specifically (not "any authorized tier") — an owner or Manager who doesn't also hold an editor role never gets an `editors.json` draft or a `slug` written into their session, since they have no presentation page to manage
- Kept the existing `POST_LOGIN_REDIRECT = "/"` constant for the post-**logout** redirect only; the post-**login** redirect is now computed per-tier via two new constants (`_REDIRECT_MANAGER_TIER`, `_REDIRECT_EDITOR_TIER`) — avoids overloading one constant with two different meanings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated tests/test_app_auth.py to match the new has_editor_role/callback interface**
- **Found during:** Task 1 (rework of `has_editor_role` and `callback`)
- **Issue:** The plan's `<files>` for Task 1 lists only `app/auth.py`, but the plan's own `<behavior>`/`<action>` explicitly require `has_editor_role` to read `settings.get("editor_roles")` instead of `config.ROLE_MODERATOR_ID`, and the callback to resolve tiers via `_fetch_member_roles` instead of calling `has_editor_role` directly. The pre-existing tests monkeypatched `config.ROLE_MODERATOR_ID` and `auth.has_editor_role` directly — after the rework those mocks have no effect (the settings-store default for `editor_roles` is baked in at `core/settings.py` import time from the `ROLE_MODERATOR_ID` *env var*, not read from `config.ROLE_MODERATOR_ID` at call time), so the old tests would either false-fail or false-pass against stale assumptions, and the plan's own acceptance criterion (`pytest tests/test_app_auth.py -x` exits 0) would not hold without updating them.
- **Fix:** Updated `test_has_editor_role_*` to monkeypatch `auth.settings.get` instead of `config.ROLE_MODERATOR_ID`; reworked `_patch_callback_happy` to monkeypatch `auth._fetch_member_roles` (plus `auth.settings.get` and `config.DISCORD_USER_ID`) instead of `auth.has_editor_role`; updated the fixed-redirect assertion to the new per-tier target (`/editor` for an editor-only identity); added `test_fetch_member_roles_returns_set_of_str_and_uses_bot_token`, `test_fetch_member_roles_none_when_not_a_guild_member`, `test_callback_manager_tier_redirects_to_overview_no_draft_created`, and `test_callback_owner_tier_redirects_to_overview_even_without_any_role` to pin the new shared-read/per-tier/no-draft-for-non-editors behavior the plan's `<behavior>` block specifies.
- **Files modified:** `tests/test_app_auth.py`
- **Verification:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_auth.py -x` → 25 passed; full suite `pytest tests/` → 658 passed, 5 failed (all in `tests/test_app_dashboard.py`, expected RED for Plan 07's not-yet-built routes per this plan's `<verification>` note)
- **Committed in:** `6cc9c5b` (Task 1 commit, bundled with the app/auth.py rework since the two changes are inseparable — the old tests directly asserted the retired interface)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug/test-interface drift)
**Impact on plan:** Necessary for the plan's own acceptance criteria to hold (`pytest tests/test_app_auth.py -x` exits 0 is stated as Task 1's verify step); no scope creep beyond the plan's explicitly stated `<behavior>`.

## Issues Encountered
None beyond the test-interface deviation documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `app/deps.py::require_manager`/`_resolve_roles`/`TierForbidden` and `app/auth.py::_fetch_member_roles` are ready for Plan 07 to wire into the `/overview`, `/gallery`, `/reviews`, `/reminders`, `/jinxxy`, `/meetings` routes and the `TierForbidden`-aware exception-handler branch (rendering `forbidden.html` with `required_tier`).
- `tests/test_app_dashboard.py`'s `require_manager` import now resolves (previously would have `AttributeError`'d); its five route-level assertions remain the expected RED signal until Plan 07 adds the routes themselves — this is unchanged scope, not a regression introduced here.
- Full local suite: 658 passed, 5 failed (all `test_app_dashboard.py` route-not-found cases, expected per this plan's `<verification>` note). No blockers for Plan 07.

---
*Phase: 03-dashboard-shell-tiered-access*
*Completed: 2026-07-22*
