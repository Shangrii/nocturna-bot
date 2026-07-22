---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Staff Dashboard
status: executing
stopped_at: Phase 3 UI-SPEC approved
last_updated: "2026-07-22T01:08:49.846Z"
last_activity: 2026-07-22 -- Phase 03 planning complete
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 8
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-21)

**Core value:** The whole staff operates the bot from one web dashboard according to their
access level — owner everything, Managers day-to-day operations, editors their own
presentation pages — with no secrets exposed and no bad value able to break a cog.
**Current focus:** Phase 3 — Dashboard Shell + Tiered Access

## Current Position

Phase: 3 of 10 (Dashboard Shell + Tiered Access)
Plan: — (not yet planned)
Status: Ready to execute
Last activity: 2026-07-22 -- Phase 03 planning complete

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 8
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 3 | - | - |
| 02 | 5 | - | - |

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

Last session: 2026-07-21T16:35:55.304Z
Stopped at: Phase 3 UI-SPEC approved
Resume file: .planning/phases/03-dashboard-shell-tiered-access/03-UI-SPEC.md
