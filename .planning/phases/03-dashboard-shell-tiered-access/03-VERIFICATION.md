---
phase: 03-dashboard-shell-tiered-access
verified: 2026-07-22T07:30:29Z
status: human_needed
score: 6/6 must-haves verified (automated)
overrides_applied: 1
overrides:
  - must_have: "A human confirms the variant-A shell renders per UI-SPEC and the three tiers behave correctly end-to-end (03-08 live OAuth 3-account walkthrough)"
    reason: "No local .env with OAuth/session secrets exists on this machine (app fail-fasts without them), so the live 3-account Discord OAuth walkthrough could not be run. The owner explicitly reviewed and APPROVED the 03-08 checkpoint on 2026-07-22, accepting the automated 663-test TestClient access-matrix (dependency-override-based 200/403 coverage for owner/Manager/editor across all 7 sections) plus static-render visual review of the real Jinja templates against the locked UI-SPEC and sketch, in lieu of the live OAuth round-trip. The only delta a live walkthrough would add over the automated suite is confirming the Discord OAuth network round-trip itself, unchanged from prior phases."
    accepted_by: "owner (per 03-08-SUMMARY.md sign-off, 2026-07-22)"
    accepted_at: "2026-07-22T00:00:00Z"
human_verification:
  - test: "Live 3-account Discord OAuth walkthrough (owner / Manager / editor-only) against a real guild, confirming the OAuth round-trip itself resolves the correct tier and redirects per D-01/D-03."
    expected: "Each of the three real Discord accounts logs in via /login → /auth/callback and lands on the correct tier-appropriate page (owner/Manager → /overview, editor-only → /editor), matching the automated TestClient matrix."
    why_human: "Requires a live Discord OAuth client secret + bot token + real guild membership; this verifier (and the 03-08 checkpoint) had no local .env with those secrets available. Automated TestClient coverage (dependency_overrides on require_manager/require_owner/require_editor) proves the route-gating and rendering logic exactly, but does not exercise the live OAuth network round-trip end-to-end. Classified as human_needed per explicit task instruction, not gaps_found, since the owner already accepted the automated-matrix-in-lieu-of substitution for the 03-08 checkpoint."
---

# Phase 3: Dashboard Shell + Tiered Access Verification Report

**Phase Goal:** Every staff member lands on a dashboard shell that shows exactly the sections
their access tier permits, and the owner can safely manage that role→tier mapping from within
it.
**Verified:** 2026-07-22T07:30:29Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Staff can navigate the 7 sections (Overview, Gallery, Reviews, Reminders, Jinxxy Store, Meetings, Settings) via a sidebar with per-module color accents, and Overview shows bot connection status, last Jinxxy sync, and recent activity (SHELL-01/02) | VERIFIED | `app/templates/_sidebar.html` renders all 7 fixed-order sections with per-section `--acc` accent vars and server-computed lock icons (`{% if not unlocked %}🔒{% endif %}`); `app/templates/overview.html` renders bot-status tile (`data.online`), last-Jinxxy-sync tile, and a recent-activity table fed by `/api/overview/status`, polled every 30000ms via Alpine `setInterval`. Backed by real data: `core/db.py` has `get_heartbeat`/`get_jinxxy_sync_status`/`get_recent_activity`; `app/main.py::_build_overview_status` assembles the exact JSON from live rows (not fabricated); `test_sidebar_renders_seven_sections` and `test_overview_shows_status_tiles` (both real, non-stub assertions on rendered HTML body) pass in the 663-green suite. |
| 2 | The owner can view and use every section, including Settings (ACCESS-01) | VERIFIED | `app/deps.py::_resolve_roles` hardcodes `is_owner` to `config.DISCORD_USER_ID`, independent of the role mapping. `app/main.py`'s 6 module routes + `/admin/settings` (`require_owner`, unchanged) admit the owner. `test_owner_full_access` asserts 200 on all 6 module routes + `/admin/settings` for an owner identity. |
| 3 | A user with the Manager role (`1453560115423875205`) can view and use the 6 operational modules; Settings responds 403 for them (ACCESS-02) | VERIFIED | `core/settings.py::_SCHEMA["manager_roles"]` seeds `1453560115423875205`; `require_manager` admits owner-or-Manager; `/admin/settings` stays on unchanged `require_owner`. `test_manager_operational_access_settings_403` asserts 200 on the 6 module routes and 403 on `/admin/settings` for a Manager-only identity; `_auth_html_or_json` renders `forbidden.html` (not `login.html`) with `required_tier="owner"` for this exact case (D-16), verified by reading the exception handler code directly. |
| 4 | An editor can only access their presentation section (ACCESS-03) | VERIFIED | `test_editor_only_locked_out_of_dashboard` asserts 403 on all 6 module routes + `/admin/settings`, and 200 on `/editor`, for an editor-only identity (with `require_manager` forced to raise, `require_editor` overridden). `_sidebar.html` shows every section locked except a distinct "Editor" link gated on `roles.is_editor` (D-15). |
| 5 | The owner can edit the role→tier mapping from Settings; a Manager cannot self-elevate and the owner can never be locked out (ACCESS-04) | VERIFIED | `core/settings.py` exposes `manager_roles`/`editor_roles` as owner-editable `role_list` settings (validated `^\d{17,20}$`-style via `_validate_role_id_list`), rendered under a bilingual "Acceso · Access" group in `settings.html`; round-trip + no-cascade-fallback covered by `tests/test_settings.py` (`test_manager_roles_round_trip`, `test_editor_roles_round_trip`, `test_manager_roles_empty_does_not_fall_back_to_gallery_staff`, etc.). Self-elevation guard: `/admin/settings` (GET+POST) stays on the byte-identical, unchanged `require_owner` dependency — a Manager session can never satisfy it regardless of what's in the POST body; `test_manager_cannot_edit_mapping` asserts a Manager POST to `/admin/settings` (including a `manager_roles` payload) still 403s. Owner-never-locked-out: `is_owner` in `_resolve_roles` is derived independently of `manager_roles`/`editor_roles` — `test_callback_owner_tier_redirects_to_overview_even_without_any_role` in `tests/test_app_auth.py` pins this even with zero roles held. |
| 6 | (03-08 checkpoint) A human confirms the variant-A shell renders per UI-SPEC and the three tiers behave correctly end-to-end | PASSED (override) | Live 3-account OAuth walkthrough was not run locally (no `.env` with OAuth secrets on this machine). Owner explicitly reviewed static-rendered templates against the UI-SPEC/sketch and the automated TestClient access matrix on 2026-07-22 and approved the checkpoint (03-08-SUMMARY.md). See `overrides:` in frontmatter. The residual gap (live OAuth round-trip itself) is listed under Human Verification Required below per this verification's explicit instruction to classify remaining live-only confirmation as `human_needed`, not `gaps_found`. |

**Score:** 6/6 truths verified (5 directly verified in codebase + tests; 1 accepted via documented override, with the live-only residual surfaced as a human-verification item, not a gap)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/test_app_dashboard.py` | 6 named behavioral tests covering SHELL-01/02 + ACCESS-01..04 | VERIFIED | All 6 tests present (`test_sidebar_renders_seven_sections`, `test_overview_shows_status_tiles`, `test_owner_full_access`, `test_manager_operational_access_settings_403`, `test_editor_only_locked_out_of_dashboard`, `test_manager_cannot_edit_mapping`), all pass in the current 663-green suite (verified via a fresh local pytest run, not trusted from SUMMARY). |
| `tests/test_settings.py` | manager_roles/editor_roles schema round-trip + no-fallback cases | VERIFIED | 8 cases present: seed, round-trip, invalid-id rejection, no-cascade-fallback for both keys. |
| `core/settings.py` | `manager_roles`/`editor_roles` `_Setting` entries, group `"access"`, no `fallback_key` | VERIFIED | Lines 296-308: both entries present, `role_list` type, `_validate_role_id_list`, seeded from `MANAGER_ROLE_IDS`/`ROLE_MODERATOR_ID` env vars respectively, no `fallback_key` param. |
| `app/templates/settings.html` | bilingual group legend for `"access"` | VERIFIED | `groupNames` dict contains `access: 'Acceso · Access'` (line 125). |
| `core/db.py` | init/get/set helpers for `bot_heartbeat`, `jinxxy_sync_status`, `activity_log` | VERIFIED | All 9 functions present and confirmed by name: `init_heartbeat`, `set_heartbeat`, `get_heartbeat`, `init_jinxxy_sync_status`, `set_jinxxy_sync_status`, `get_jinxxy_sync_status`, `init_activity_log`, `log_activity`, `get_recent_activity`. |
| `cogs/heartbeat.py` | `HeartbeatCog` `@tasks.loop` writing `bot_heartbeat` every ~45s | VERIFIED | `@tasks.loop(seconds=45)` on `_beat`, writes via `asyncio.to_thread(db.set_heartbeat, ...)` wrapped in try/except (never kills the loop), `before_loop` waits for gateway ready, `cog_unload` cancels the loop. |
| `bot.py` | `load_extension("cogs.heartbeat")` in always-loaded block | VERIFIED | Line 60, `await self.load_extension("cogs.heartbeat")`. |
| `cogs/jinxxy.py`, `cogs/gallery.py`, `cogs/reviews.py`, `cogs/meeting.py` | `set_jinxxy_sync_status`/`log_activity` instrumentation on notable events | VERIFIED | jinxxy.py: `set_jinxxy_sync_status` + `log_activity("jinxxy_sync", ...)`; gallery.py: `log_activity("gallery_published"/"gallery_removed", ...)`; reviews.py: `log_activity("review_published"/"review_removed", ...)`; meeting.py: `log_activity("meeting_posted", ...)`. |
| `app/deps.py` | `_resolve_roles`, `require_manager`, `TierForbidden` | VERIFIED | All three present and implemented as documented — owner hardcode independent of mapping, single live role read, `TierForbidden(required_tier=...)`. |
| `app/auth.py` | `_fetch_member_roles`, `has_editor_role→editor_roles`, per-tier post-login redirect | VERIFIED | `_fetch_member_roles` (line 94) shared by both `has_editor_role` (now reads `settings.get("editor_roles")`) and `callback`'s tier resolution; `_REDIRECT_MANAGER_TIER`/`_REDIRECT_EDITOR_TIER` drive the per-tier redirect. |
| `app/static/dashboard.css`, `_dashboard_base.html`, `_sidebar.html`, `overview.html`, `module_stub.html`, `forbidden.html` | Variant-A theme + shell chrome + pages | VERIFIED | All 6 files exist; sidebar/overview/module_stub/forbidden all extend/include the shared base; per-module accent vars present; module_stub has no toggle switch (per UI-SPEC out-of-scope note); forbidden.html is a distinct in-shell 403, not `login.html`. |
| `app/main.py` | 6 module routes + Overview JSON endpoint + lifespan table init + TierForbidden handler branch | VERIFIED | `/overview`, `/gallery`, `/reviews`, `/reminders`, `/jinxxy`, `/meetings` (all `Depends(require_manager)`), `GET /api/overview/status` (`require_manager`), `lifespan()` calls `db.init_heartbeat()`/`init_jinxxy_sync_status()`/`init_activity_log()`, `_auth_html_or_json` has the `TierForbidden` branch + unified Settings-403 branch, both rendering `forbidden.html`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `tests/test_app_dashboard.py` | `app.dependency_overrides` | `require_manager`/`require_owner`/`require_editor` overrides | WIRED | Every test scopes overrides in `try`/`finally`, confirmed by direct read of the file. |
| `core/settings.py::all_for_ui`/form | `app/templates/settings.html` group loop | `descriptor.group == 'access'` | WIRED | `groupNames.access` legend renders; the existing generic `role_list` field-type branch requires no new template code (confirmed no new field-type branch was needed or added). |
| `cogs/heartbeat.py` | `core/db.py::set_heartbeat` | `asyncio.to_thread(db.set_heartbeat, ...)` | WIRED | Confirmed at `cogs/heartbeat.py:44-50`. |
| `bot.py::setup_hook` | `cogs.heartbeat` | `load_extension` | WIRED | Confirmed at `bot.py:60`. |
| `cogs/jinxxy.py::_run_sync` | `core/db.py::set_jinxxy_sync_status` | single instrumentation point (success + failure) | WIRED | `_record_sync_status` helper called from both branches; confirmed. |
| `cogs/gallery.py` | `core/db.py::log_activity` | `asyncio.to_thread(db.log_activity, ...)` | WIRED | Confirmed at 2 call sites (publish/remove). |
| `app/deps.py::_resolve_roles` | `app/auth.py::_fetch_member_roles` | single live bot-token REST read | WIRED | Confirmed — `_resolve_roles` calls `auth._fetch_member_roles(discord_id)` once. |
| `app/deps.py::_resolve_roles` | `core/settings.py::get` | `manager_roles`/`editor_roles` reads | WIRED | Confirmed — `settings.get("manager_roles")`/`settings.get("editor_roles")` called directly. |
| `app/templates/_sidebar.html` | `roles` dict | server-computed `unlocked` flag per section | WIRED | Confirmed — Jinja `{% set unlocked = ... %}` derives lock state purely from `roles.is_owner`/`is_manager`, zero client JS. |
| `app/templates/overview.html` | `/api/overview/status` | Alpine `setInterval` fetch | WIRED | Confirmed — `setInterval(() => this.refresh(), 30000)` calling `fetch('/api/overview/status')`. |
| `app/main.py::/overview` | `app/deps.py::require_manager` | `Depends(require_manager)` | WIRED | Confirmed at `app/main.py:572`. |
| `app/main.py::_auth_html_or_json` | `app/templates/forbidden.html` | `TierForbidden` branch | WIRED | Confirmed at `app/main.py:356-366`, two branches rendering `forbidden.html`. |
| `app/main.py::/api/overview/status` | `core/db.py` getters | `run_in_threadpool` reads | WIRED | Confirmed via `_read_overview_status` calling `run_in_threadpool(db.get_heartbeat)` etc. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `overview.html` (bot-status tile) | `data.online`/`data.uptime`/`data.member_count` | `_build_overview_status` ← `db.get_heartbeat()` ← `HeartbeatCog._beat` writes every 45s | Yes — computed from real heartbeat row age (`_compute_online`), not hardcoded | FLOWING |
| `overview.html` (last-sync tile) | `data.last_sync` | `db.get_jinxxy_sync_status()` ← written by `cogs/jinxxy.py::_run_sync` on every poll/manual run | Yes | FLOWING |
| `overview.html` (activity table) | `data.activity` | `db.get_recent_activity(10)` ← `log_activity(...)` calls from gallery/reviews/jinxxy/meeting cogs | Yes — degrades to `[]` (real empty-state copy) on a cold DB, not a fabricated row | FLOWING |
| `_sidebar.html` (lock icons) | `roles.is_owner`/`is_manager`/`is_editor` | `Depends(require_manager)` → `_resolve_roles` → live Discord role read + `settings.get(...)` | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-3 test suite is green | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/ -q` | `663 passed, 3 warnings in 10.03s` | PASS |
| Anti-pattern scan (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER/"not yet implemented") across all phase-3-modified files | `grep -inE` per file | Only legitimate hits: HTML `placeholder=` attrs, Spanish docstring word "próxima"/"placeholders" referring to SQL `?` placeholders, and the UI-SPEC-mandated "Próximamente · Coming soon" stub copy | PASS (no blockers) |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` convention or PLAN/SUMMARY-declared probes found in this repository/phase. Verification relies on the pytest suite (a first-class, already-integrated test runner) instead of a standalone probe script.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|--------------|-------------|-------------|--------|----------|
| SHELL-01 | 03-01, 03-06, 03-07 | Sidebar navigates 7 sections with per-module accent | SATISFIED | `_sidebar.html` + `test_sidebar_renders_seven_sections` |
| SHELL-02 | 03-01, 03-03, 03-04, 03-06, 03-07 | Overview shows bot status/last sync/recent activity | SATISFIED | `overview.html` + `_build_overview_status` + `test_overview_shows_status_tiles` |
| ACCESS-01 | 03-01, 03-05, 03-07 | Owner uses every section incl. Settings | SATISFIED | `test_owner_full_access` |
| ACCESS-02 | 03-01, 03-05, 03-07 | Manager gets 6 modules, 403 on Settings | SATISFIED | `test_manager_operational_access_settings_403` |
| ACCESS-03 | 03-01, 03-05, 03-07 | Editor only accesses their presentation section | SATISFIED | `test_editor_only_locked_out_of_dashboard` |
| ACCESS-04 | 03-01, 03-02, 03-05 | Owner edits mapping; Manager can't self-elevate; owner never locked out | SATISFIED | `test_manager_cannot_edit_mapping`, `test_settings.py` round-trip cases, `test_callback_owner_tier_redirects_to_overview_even_without_any_role` |

No orphaned requirements: `.planning/REQUIREMENTS.md`'s traceability table maps exactly SHELL-01, SHELL-02, ACCESS-01..04 to Phase 3, and every plan's `requirements:` frontmatter field across 03-01 through 03-08 covers this same set with no additional/unclaimed IDs.

Note: `.planning/REQUIREMENTS.md`'s per-requirement checkboxes (`- [ ] **SHELL-01**...`) are still unchecked as of this verification — this is a documentation-bookkeeping item, not a code-truth gap; the phase-level Traceability table's "Status: Pending" column is similarly stale. Flagged for the phase-close step to update, not a blocker to this phase's goal achievement.

### Anti-Patterns Found

None (blocker or warning-level). All "placeholder"/"coming soon" hits are legitimate (HTML input placeholders, the UI-SPEC-mandated stub copy, or SQL-placeholder docstring references) — no debt markers (TBD/FIXME/XXX/TODO/HACK) found in any phase-3-modified file.

### Human Verification Required

### 1. Live 3-account Discord OAuth walkthrough

**Test:** Log in as the real owner Discord account, a real account holding the Manager role, and a real account holding only the editor role (no Manager/owner), each via `/login` → Discord consent → `/auth/callback`.
**Expected:** Owner and Manager land on `/overview` with the correct sidebar unlock state; editor-only lands on `/editor`; no account with zero mapped roles or tiers is granted a session (falls through to the existing rejection).
**Why human:** Requires live Discord OAuth client credentials, a live bot token, and real guild role membership — this verifier's environment (and the 03-08 checkpoint's environment) has no local `.env` with OAuth/session secrets configured, so the OAuth network round-trip itself cannot be exercised by an automated check. The route-gating and tier-resolution *logic* downstream of a successful OAuth round-trip is already fully proven by the 663-test automated suite (dependency-override-based TestClient coverage across all 3 tiers × all 7 routes). The owner already reviewed and approved this exact substitution for the 03-08 checkpoint on 2026-07-22 (see `overrides:` above) — this item is surfaced here only because a fully live confirmation of the OAuth round-trip itself remains outstanding, not because any gap was found in the implementation.

### Gaps Summary

No gaps found. All 5 ROADMAP.md Success Criteria for Phase 3 are directly verified against real, wired, non-stub code and pass in a freshly-run 663-test suite. The one outstanding item is the live OAuth round-trip itself, which the owner has already explicitly accepted as covered-in-substance by the automated access-matrix and static visual review (03-08 checkpoint, APPROVED 2026-07-22) — surfaced here as a human-verification item per this verification's own reasonable classification, not as a blocking gap.

---

*Verified: 2026-07-22T07:30:29Z*
*Verifier: Claude (gsd-verifier)*
