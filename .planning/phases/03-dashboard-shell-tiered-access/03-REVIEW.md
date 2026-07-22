---
phase: 03-dashboard-shell-tiered-access
reviewed: 2026-07-22T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - app/auth.py
  - app/deps.py
  - app/main.py
  - app/static/dashboard.css
  - app/templates/_dashboard_base.html
  - app/templates/_sidebar.html
  - app/templates/forbidden.html
  - app/templates/module_stub.html
  - app/templates/overview.html
  - app/templates/settings.html
  - bot.py
  - cogs/gallery.py
  - cogs/heartbeat.py
  - cogs/jinxxy.py
  - cogs/meeting.py
  - cogs/reviews.py
  - core/db.py
  - core/settings.py
  - tests/test_app_auth.py
  - tests/test_app_dashboard.py
  - tests/test_settings.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-07-22T00:00:00Z
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

This phase adds a 3-tier (owner / Manager / editor) access model layered onto the existing
editor admin app: a shared live bot-token role read (`_resolve_roles`), a `require_manager`
gate for the six operational dashboard modules, an unchanged `require_owner` gate for
`/admin/settings`, an in-shell tier-403 page (`forbidden.html`), the Overview status page,
and bot-side heartbeat/activity-log instrumentation.

The core authorization surface is sound. I traced the specific attack vectors called out for
this phase and found **no** exploitable defect in any of them:

- **Authorization bypass / 403→200 leak:** every dashboard module route is gated by
  `require_manager` (→ `_resolve_roles`), Overview's poll endpoint is gated (not public), and
  Settings stays on `require_owner`. No route reaches a 200 without a satisfied dependency.
- **Tier escalation (Manager → owner):** `manager_roles`/`editor_roles` are editable only
  through `/admin/settings`, which is `require_owner`-gated; a Manager POST is 403'd
  (confirmed by `test_manager_cannot_edit_mapping`). No tier is ever cached in the session
  (D-02) — every request re-resolves live from Discord, so a stale cookie cannot carry an
  elevated tier.
- **IDOR on settings:** identity comes only from `require_owner`'s session read; the body
  supplies only key/value pairs, each allowlist-checked against `_SCHEMA` before any SQL.
- **Session handling:** `SessionMiddleware` uses `https_only` + `same_site=lax` + a short TTL;
  session is issued only after full tier resolution in the callback.

The issues below are correctness/robustness defects, not authorization holes. The most
important, WR-01, is an **owner-lockout path** that contradicts the D-04 "owner is never
locked out" invariant and diverges from how the OAuth callback handles the same condition —
directly relevant to the phase's stated owner-lockout concern.

## Warnings

### WR-01: `_resolve_roles` locks the owner out on a bot-token 404, contradicting D-04

**File:** `app/deps.py:145-148`
**Issue:** `_resolve_roles` computes `is_owner` first, then performs the live role read and
treats a `None` result (Discord `GET /guilds/{g}/members/{id}` → 404, i.e. "not a guild
member") as a hard denial that clears the session and raises 403 — **before** honoring
`is_owner`:

```python
is_owner = bool(config.DISCORD_USER_ID) and str(discord_id) == str(config.DISCORD_USER_ID)
role_ids = await auth._fetch_member_roles(discord_id)
if role_ids is None:
    request.session.clear()
    raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)   # owner never gets here
```

This means the configured owner is fully locked out of the entire dashboard whenever the
bot-token member read returns 404 — a non-member owner, or a transient/spurious Discord 404.
Because the callback re-grants a session to the owner independently of membership (see below),
the owner enters a **login loop**: log in → callback succeeds (`is_owner` true) → `/overview`
→ `_resolve_roles` 404s → session cleared → back to login, forever.

This directly contradicts the module's own D-04 docstring ("the owner is NEVER locked out")
and is inconsistent with `app/auth.py::callback:249`, which handles the identical read as
`role_ids = await _fetch_member_roles(user_id) or set()` — a `None` there degrades to an empty
set and the owner still passes the tier gate. The two code paths disagree on the same input.

**Fix:** short-circuit the owner (and any already-resolved tier) before the non-member denial,
mirroring the callback's `or set()`:

```python
role_ids = await auth._fetch_member_roles(discord_id)
if role_ids is None:
    role_ids = set()          # non-member: no mapped roles, but not an automatic denial
manager_ids = {str(r) for r in settings.get("manager_roles")}
editor_ids = {str(r) for r in settings.get("editor_roles")}
is_manager = bool(role_ids & manager_ids)
is_editor = bool(role_ids & editor_ids)
if not (is_owner or is_manager or is_editor):
    request.session.clear()
    raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)
```

This keeps the fail-closed denial for genuine no-tier users while preserving the owner's
independence from guild membership.

### WR-02: Unauthenticated hit to `/admin/settings` renders the in-shell forbidden page, never a login prompt

**File:** `app/main.py:362-366` (with `app/deps.py:99-104`)
**Issue:** `require_owner` returns **403** (never 401) for a missing session — by design, on
the assumption the caller is already an authenticated editor. But `/admin/settings` is gated
*only* by `require_owner`; there is no `require_editor` in front of it. So an anonymous browser
navigation to `/admin/settings` (no session cookie) produces a 403, which the D-16 branch then
turns into the in-shell `forbidden.html` "needs owner access" page:

```python
if exc.status_code == 403 and request.url.path == "/admin/settings" and accept_html:
    return templates.TemplateResponse(request, "forbidden.html",
        {"required_tier": "owner", "roles": _NO_TIER_ROLES}, status_code=403)
```

An unauthenticated user is thus shown the full dashboard shell (sidebar chrome, topbar,
section labels) and a dead-end "needs owner access" message instead of being routed to the
login page like every other unauthenticated navigation (branch 3 → `login.html`). This is a
correctness/UX regression versus the rest of the app's auth surface and leaks the dashboard
structure to anonymous callers.

**Fix:** distinguish "no session" (send to login) from "authenticated but not owner" (show
forbidden). Simplest: have `require_owner` raise 401 when there is no `discord_id` in the
session at all (an unauthenticated caller), and keep 403 only for an authenticated non-owner —
then branch 3's `login.html` handles the anonymous case. Alternatively, gate the branch on the
presence of a session before rendering `forbidden.html`.

### WR-03: Forbidden page shows a Manager their accessible modules as locked

**File:** `app/main.py:356-366`, `app/templates/_sidebar.html:16-22`
**Issue:** Both `forbidden.html` branches in `_auth_html_or_json` pass the hardcoded
`_NO_TIER_ROLES = {"is_owner": False, "is_manager": False, "is_editor": False}`. When a
legitimate **Manager** navigates to `/admin/settings` and is (correctly) 403'd, the rendered
sidebar computes lock icons from this all-locked dict, so the six operational modules the
Manager *can* use are all shown with a 🔒. Clicking any of them still works, so the lock
state actively misrepresents the caller's real access. The failure direction is safe
(over-restrictive), but the displayed authorization state is wrong for the most common real
denial case.

**Fix:** the exception handler cannot cheaply re-derive the tier without a second Discord read
(acknowledged in the docstring). A lightweight option: since the caller reached
`/admin/settings`, they passed `require_owner`'s upstream auth only if authenticated; render
the sidebar in a "tier unknown" mode that omits lock icons entirely rather than asserting all
sections are locked, or thread the already-resolved `roles` dict through `TierForbidden` when
it is available so the branch can render true lock state. At minimum, document this as a known
cosmetic limitation so it is not mistaken for correct lock rendering.

## Info

### IN-01: Overview poll overwrites good state with an error body on mid-session role loss

**File:** `app/templates/overview.html:70-77`
**Issue:** `refresh()` does not check `r.ok` before assigning `this.data`:

```js
const r = await fetch('/api/overview/status');
const json = await r.json().catch(() => null);
if (json) this.data = json;
```

If a Manager's role is revoked mid-session, the 30s poll hits `require_manager` → 403 with a
JSON body `{"detail": "needs manager access"}`. That body is truthy, so `this.data` is
overwritten with it, and the tiles (`data.online`, `data.last_sync`, `data.activity`) go
blank/broken — the opposite of the intended "keep last-known-good on failure" behavior.
**Fix:** guard the assignment with `if (r.ok && json) this.data = json;`.

### IN-02: `_compute_online` reads a clock-skewed future heartbeat as offline

**File:** `app/main.py:498-509`
**Issue:** `return 0 <= age_seconds <= _HEARTBEAT_STALE_SECONDS`. The `0 <=` lower bound means
a heartbeat timestamp that lands slightly in the future relative to the app's clock (NTP
adjustment, or app clock momentarily behind the bot's) is classified as offline even though it
is the freshest possible beat. Both processes share a host so the window is tiny, but the
lower bound is a latent footgun with no upside. **Fix:** drop the lower bound
(`age_seconds <= _HEARTBEAT_STALE_SECONDS`) or clamp negatives to 0.

### IN-03: Dashboard routes never pass `bot_version`, so the sidebar footer is permanently "v1"

**File:** `app/main.py:582-602`, `app/templates/_sidebar.html:37`
**Issue:** `_sidebar.html` renders `v{{ bot_version | default('1') }}`, but neither
`overview_page`, `_module_stub_page`, nor the `forbidden.html` render path ever supplies
`bot_version`, so the footer always shows "v1" regardless of the actual bot version. Purely
cosmetic. **Fix:** thread a real version constant into the dashboard render context, or remove
the version fragment if it is not meant to be live.

---

_Reviewed: 2026-07-22T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
