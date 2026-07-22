---
phase: 03-dashboard-shell-tiered-access
plan: 06
subsystem: ui
tags: [jinja2, alpine.js, fastapi, dashboard-shell, css-tokens, server-side-authz]

# Dependency graph
requires:
  - phase: 03-dashboard-shell-tiered-access (03-UI-SPEC.md)
    provides: locked variant-A design contract (spacing/typography/color closed sets, copy)
provides:
  - app/static/dashboard.css — variant-A theme tokens (color, per-module accents, closed
    4-size/2-weight typography, 4/8/12/16/24/32/48/64 spacing scale)
  - app/templates/_dashboard_base.html — shared topbar + sidebar + {% block content %} layout
  - app/templates/_sidebar.html — data-driven 7-section nav with server-computed lock icons
  - app/templates/overview.html — status-first stat tiles + activity table + 30s Alpine poll
  - app/templates/module_stub.html — generic "coming soon" module page (no toggle switch)
  - app/templates/forbidden.html — in-shell bilingual tier-403 page (required_tier param)
affects: [03-07 (route wiring: roles dict, active_section, overview status JSON, TierForbidden
  handler), 04 (Settings shell migration)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Server-computed lock state: _sidebar.html Jinja loop derives `unlocked` per section
      from the `roles` dict — zero client-side gating logic (D-14, T-03-18)."
    - "Base-template scripts block: _dashboard_base.html exposes {% block scripts %} before
      the deferred alpine.min.js load so page-local Alpine component functions (e.g.
      overviewApp) are defined in time, mirroring settings.html's settingsApp precedent."
    - "Single-quoted x-data with tojson: overview.html seeds Alpine state via
      x-data='overviewApp({{ seed | tojson }})' to avoid the same quote-escaping hazard
      documented in settings.html."

key-files:
  created:
    - app/static/dashboard.css
    - app/templates/_dashboard_base.html
    - app/templates/_sidebar.html
    - app/templates/overview.html
    - app/templates/module_stub.html
    - app/templates/forbidden.html
  modified: []

key-decisions:
  - "Sidebar nav items are real <a> links (not buttons/onclick) so locked sections still
    navigate to their real route — the forbidden page is the graceful dead end (D-16),
    never a disabled/no-op control."
  - "Footer status chip and topbar wire against two render-contract vars not explicit in
    the plan's <interfaces> block: bot_online (bool) and bot_version (string, default '1').
    Chosen to mirror the shape of the documented Overview status JSON (`online`) rather
    than invent a new heartbeat vocabulary; Plan 07's routes should supply these alongside
    `roles`/`active_section` on every render."
  - "Skipped the UI-SPEC's 12px (--space-3) sidebar-group-label / gallery-card exception
    entirely — this plan's sidebar renders a flat 7-item list (no Módulos/Sistema group
    headers) and no gallery-card grid ships this phase, so there was no legitimate site to
    apply the exception. --space-3 is still declared as a token for future phases."

requirements-completed: [SHELL-01, SHELL-02]

# Metrics
duration: 15min
completed: 2026-07-22
---

# Phase 3 Plan 06: Dashboard Shell Chrome + Overview Summary

**Variant-A dashboard shell (topbar/sidebar/main layout, dashboard.css theme tokens) with a
server-computed 7-section nav, a status-first Overview page polling `/api/overview/status`
every 30s via Alpine, a generic module-stub page, and an in-shell bilingual tier-403 page.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-22T01:05:00Z (approx)
- **Completed:** 2026-07-22T01:20:19Z
- **Tasks:** 2
- **Files modified:** 6 (all new)

## Accomplishments
- Ported the locked variant-A sketch theme into `app/static/dashboard.css` within the
  UI-SPEC's closed sets: 4 font sizes (12/13/18/26px), 2 weights (400/600, zero 700/800),
  and an 4/8/12/16/24/32/48/64px spacing scale.
- Built `_dashboard_base.html` + `_sidebar.html`: a reusable topbar/sidebar/main shell where
  lock icons on the 7 fixed-order sections are computed entirely server-side from the
  `roles` dict passed into every render (no Alpine/JS gating anywhere).
- Built `overview.html` with the bot-status tile as the primary visual anchor (green/red
  accent), a Jinxxy-sync tile, and a recent-activity table with bilingual empty-state copy —
  wired to a 30s Alpine poll of `/api/overview/status` reusing settings.html's
  fetch→json→assign-state→catch shape.
- Built `module_stub.html` (bilingual "coming soon", no toggle/badge) and `forbidden.html`
  (in-shell, bilingual, `required_tier`-parametrized, distinct from `login.html`'s
  editor-only 403 copy).

## Task Commits

Each task was committed atomically:

1. **Task 1: dashboard.css + _dashboard_base.html + _sidebar.html (shell chrome)** - `d90c707` (feat)
2. **Task 2: overview.html + module_stub.html + forbidden.html** - `502c604` (feat)

## Files Created/Modified
- `app/static/dashboard.css` - Variant-A theme tokens: colors, per-module accents, closed
  typography/spacing scales, and component styles (topbar, sidebar, stat tiles, cards,
  mod-hdr, forbidden page) for the new shell.
- `app/templates/_dashboard_base.html` - Shared layout: topbar (wordmark + editor/logout
  links), `{% include "_sidebar.html" %}`, `<main>` with `{% block content %}`, and a
  `{% block scripts %}` slot ahead of the deferred `alpine.min.js` load.
- `app/templates/_sidebar.html` - `{% set sections = [...] %}` data-driven loop over the 7
  fixed sections; `unlocked` computed from `roles.is_owner`/`roles.is_manager` per section
  tier; 🔒 glyph on locked (but still linked) items; editor-only bottom link gated on
  `roles.is_editor`; heartbeat-fed footer status chip.
- `app/templates/overview.html` - Status-first stat grid (bot-status primary anchor +
  last-Jinxxy-sync tile), recent-activity table with bilingual empty state, and an
  `overviewApp` Alpine component polling `/api/overview/status` every 30000ms.
- `app/templates/module_stub.html` - Generic `.mod-hdr` (icon/title/accent border, no
  toggle/badge) + bilingual "coming soon" empty-state body, static (no Alpine).
- `app/templates/forbidden.html` - In-shell bilingual 403 body parametrized on
  `required_tier`, extends `_dashboard_base.html` so the sidebar stays visible (D-16).

## Decisions Made
- Nav items are `<a>` links to real routes even when locked, not disabled controls —
  matches D-16's "graceful dead end" design (the forbidden page, wired in Plan 07, is the
  actual stop).
- Introduced `bot_online`/`bot_version` as the render-contract vars for the sidebar footer
  chip since the plan's `<interfaces>` block didn't specify them explicitly; chosen to
  mirror the Overview status JSON's `online` field shape for consistency. Documented here so
  Plan 07's route wiring supplies them.
- Left the UI-SPEC's 12px spacing exception (`--space-3` for `.grp`/`.gcard`) undeclared as
  CSS usage since this plan doesn't render a grouped sidebar or a gallery-card grid — only
  the token itself is declared for future phases, no ad-hoc 12px was introduced elsewhere.

## Deviations from Plan

None - plan executed exactly as written. Both tasks' acceptance-criteria greps (accent
variables, zero font-weight 700/800, `{% block content %}` + sidebar include, all 7 section
ids, `roles.is_owner`/`is_manager`/`is_editor`, no toggle/switch/x-data in `_sidebar.html`,
`/api/overview/status` + `setInterval`/`30000`, `Sin actividad reciente`, no "Acciones
rápidas", `Próximamente · Coming soon`, `required_tier`, absence of the login.html
editor-only copy) all pass as documented below in Self-Check.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All six template/CSS artifacts are authored strictly against the documented render
  contract (`roles`, `active_section`, Overview status JSON shape, `required_tier`,
  `bot_online`/`bot_version`) with zero Python imports — no runtime dependency on other
  Wave-1 plans in this phase.
- Plan 07 must supply: `roles` dict + `active_section` on every section render;
  `online`/`latency_ms`/`uptime`/`member_count`/`last_sync`/`activity` seed values plus the
  `/api/overview/status` JSON endpoint (`require_manager`-gated); `required_tier` on
  `forbidden.html` renders (via the `TierForbidden` exception-handler branch); and
  `bot_online`/`bot_version` for the sidebar footer chip.
- No blockers.

## Self-Check

Verified all created files exist and both commits are present in `git log`:

- FOUND: app/static/dashboard.css
- FOUND: app/templates/_dashboard_base.html
- FOUND: app/templates/_sidebar.html
- FOUND: app/templates/overview.html
- FOUND: app/templates/module_stub.html
- FOUND: app/templates/forbidden.html
- FOUND: d90c707 (Task 1 commit)
- FOUND: 502c604 (Task 2 commit)

All six templates were also render-tested directly with Jinja2 (`Environment(loader=FileSystemLoader("app/templates"))`) against representative `roles`/`active_section`/Overview-status/`required_tier` context — all rendered without error.

## Self-Check: PASSED

---
*Phase: 03-dashboard-shell-tiered-access*
*Completed: 2026-07-22*
