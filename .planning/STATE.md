---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Staff Dashboard
status: executing
stopped_at: Completed 10-02-PLAN.md
last_updated: "2026-07-30T18:06:27.165Z"
last_activity: 2026-07-30
progress:
  total_phases: 8
  completed_phases: 3
  total_plans: 48
  completed_plans: 38
  percent: 38
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-21)

**Core value:** The whole staff operates the bot from one web dashboard according to their
access level — owner everything, Managers day-to-day operations, editors their own
presentation pages — with no secrets exposed and no bad value able to break a cog.
**Current focus:** Phase 10 — editors-section-integration

## Current Position

Phase: 10 (editors-section-integration) — EXECUTING
Plan: 5 of 7
Status: Ready to execute
Last activity: 2026-07-30

Progress: [████████░░] 79%

## Performance Metrics

**Velocity:**

- Total plans completed: 24
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 02 | 5 | - | - |
| 03 | 8 | - | - |
| 08 | 8 | - | - |
| Phase 10 P03 | 55min | 2 tasks | 3 files |
| Phase 10 P06 | 8min | 2 tasks | 2 files |
| Phase 10 P02 | 20min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Shared sqlite remains the only cross-process channel; v2.0 adds a reverse-direction cache
  (bot→app, e.g. `discord_names`) and a forward-direction `action_queue` (app→bot) rather than
  any new IPC/socket/HTTP endpoint

- Tiered access = owner > Manager role > editor; tier-assignment writes are owner-gated only,
  never a generic manager-or-higher check (self-elevation/lockout guard)

- Every panel-initiated Discord write (gallery/reviews approve, meeting re-publish) routes
  through the bot process via the action queue — no bot credentials added to the FastAPI app

- Roadmap ordering: tiered access first (Phase 3) → settings/name-resolution (Phase 4) →
  sqlite hardening + action queue (Phase 5, before any write-heavy module) → Reminders
  (Phase 6, standalone CRUD) → Gallery+Reviews together (Phase 7, shared publish-race fix) →
  Jinxxy (Phase 8) → Meetings last among modules (Phase 9, newest credential/idempotency
  question) → Editors integration last overall (Phase 10, lowest risk)

- [Phase 10]: editor.css chrome retinted onto dashboard.css tokens; legacy ink/red palette kept only as preview-canvas fallback literals (D-01/D-06)
- [Phase 10]: Split editor.css's conflated --red into --color-primary (CTA/active) vs --color-danger (destructive) to match dashboard.css's convention
- [Phase 10]: Editor vanity URLs move to root /{slug}; legacy /e/{slug} becomes a build-time redirect stub (define:vars + location.replace), mirroring the shipped [lang]/[concept]/[slug].astro pattern one cartesian dimension shallower
- [Phase 10]: GET / and GET /editor gate on _resolve_roles + inline TierForbidden(editor), not require_editor, so a locked-nav click from a non-editor owner/Manager never clears the session (T-10-01)
- [Phase 10]: RESERVED_SLUGS widened with en/es/gallery/store/fonts/build to protect the public site's root-level routes from vanity-slug collision (T-10-02)

### Pending Todos

None yet.

### Blockers/Concerns

- **[Research gap, Phase 4]** Discord-credential scope for name resolution (read-only,
  bot-gateway-cache-push, not admin-app REST calls) needs explicit sign-off during Phase 4
  planning before writing code (Pitfall 4).

- **[Research gap, Phase 7]** Gallery/Reviews pending-state schema is unverified — confirm
  during Phase 7 planning whether a queryable pending state already exists or a denormalized
  flag/table is needed.

- **[Research gap, Phase 9]** Meetings re-publish idempotency has no existing precedent in
  this codebase (editing an already-posted forum message from a second trigger path) — work
  out the retry-safe design during Phase 9 planning.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Panel polish | Guild-populated channel/role dropdowns (FUT-01) | Deferred to future release | 2026-07-21 |
| Panel polish | Overview quick actions, sketch 001 variant C (FUT-02) | Deferred to future release | 2026-07-21 |

## Session Continuity

Last session: 2026-07-30T18:06:27.155Z
Stopped at: Completed 10-02-PLAN.md
Resume file: None
