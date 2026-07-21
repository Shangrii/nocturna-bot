# Roadmap: Nocturna Bot

## Milestones

- ✅ **v1.0 Settings Panel** - Phases 1-2 (shipped 2026-07-21)
- 🚧 **v2.0 Staff Dashboard** - Phases 3-10 (in progress)

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

<details>
<summary>✅ v1.0 Settings Panel (Phases 1-2) - SHIPPED 2026-07-21</summary>

### Phase 1: Config Store + Consolidation

**Goal**: A single, validated source of truth for the bot's safe tunables, backed by the shared sqlite, with `config.py` reading those values at-use — all byte-identical to current `.env` behavior until the owner edits something.
**Depends on**: Nothing (first phase)
**Requirements**: STORE-01, STORE-02, STORE-03, STORE-04, STORE-05, CONF-01, CONF-02, CONF-03, CONC-01
**Success Criteria** (what must be TRUE):

  1. `settings.get`/`set`/`all_for_ui` round-trip through the `settings` table, with per-type validation rejecting bad IDs/intervals/TZ before any write.
  2. `settings.get` returns the `.env`/default seed when a key is unset or its row is corrupt (never raises).
  3. A fresh deploy seeds the store idempotently and the bot behaves identically to before (no observable change until an edit).
  4. A migrated cog reads a changed value at its next use (e.g. the staff gate honors a new role list; the Jinxxy poll reads a new announce channel).
  5. The shared-sqlite access mode is chosen and applied so concurrent bot-read / panel-write does not raise "database is locked".

**Plans**: 3 plans (3 waves)

Plans:

- [x] 01-01-PLAN.md — Wave 0 test scaffolding: tests/test_settings.py + read-at-use tests in the four migrated-cog test files (RED-first)
- [x] 01-02-PLAN.md — The validated store: core/settings.py (schema/get/set/all_for_ui/seed_defaults/SettingRejected) + core/db.py (init_settings + WAL)
- [x] 01-03-PLAN.md — Consolidation: config.py PEP 562 __getattr__ read-at-use shim + bot.py startup seed

### Phase 2: Owner Settings Panel

**Goal**: The owner can view and edit the safe tunables from a web form on the existing admin app, with server-side validation gating every write and secrets never exposed.
**Depends on**: Phase 1
**Requirements**: PANEL-01, PANEL-02, PANEL-03, PANEL-04
**Success Criteria** (what must be TRUE):

  1. A non-owner hitting any `/admin/settings` route gets 403 and no data; the owner gets 200. The gate fails closed when `DISCORD_USER_ID` is unset.
  2. `GET /admin/settings` renders the tunables grouped by feature with typed fields, and no secret ever appears in the form.
  3. A valid `POST` persists to the store and re-renders with a success banner; an invalid `POST` returns an inline field error and writes nothing.
  4. After a save, the bot picks up the new value on its next relevant use (loop-interval changes on the next cycle).

**Plans**: 5 plans (4 waves)

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Store metadata extension (all_for_ui label/min/max/tz-options) + validate_only dry-run [Wave 1]
- [x] 02-02-PLAN.md — require_owner gate in app/deps.py, fail-closed on the 0 default [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-03-PLAN.md — settings.html form (typed fields + per-field errors), owner-only editor link, inline-error CSS [Wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-04-PLAN.md — GET/POST /admin/settings routes (atomic validate-then-write) + is_owner context + integration tests [Wave 3]

**Gap closure** *(verification found gaps: SC2/CR-01 snowflake precision, SC3/CR-02 fallback baking)*

- [x] 02-05-PLAN.md — Data-integrity serialization in all_for_ui(): raw-value (_get_raw, no fallback) + string-typed snowflake/role_list + unit & integration regressions [Wave 1]

</details>

### 🚧 v2.0 Staff Dashboard (In Progress)

**Milestone Goal:** Convert the admin panel into a complete MEE6-style dashboard (sketch 001
variant A) where all staff operate the bot by access tier: owner everything, Managers
day-to-day operations, editors their own presentation page.

- [ ] **Phase 3: Dashboard Shell + Tiered Access** - Sidebar shell across 7 modules with owner/Manager/editor tiers, editable role→tier mapping, POST-only convention
- [ ] **Phase 4: Settings Migration + Name Resolution** - v1 panel folded into the shell; readable #channel/@role names via bot-pushed cache
- [ ] **Phase 5: sqlite Hardening + Action Queue** - busy_timeout/retry on write paths; generic action_queue infra every write-heavy module reuses
- [ ] **Phase 6: Reminders CRUD** - Full CRUD + pause/resume via table+modal, scheduler-race guard
- [ ] **Phase 7: Gallery + Reviews Approval Queues** - Approve/remove photos and reviews with reaction-flow parity, race-free
- [ ] **Phase 8: Jinxxy Manual Sync** - Manual sync trigger + last-run status, overlap-guarded against the poll
- [ ] **Phase 9: Meetings Browser + Re-publish** - Persist meetings; browse transcripts/summaries; edit + idempotent re-publish
- [ ] **Phase 10: Editors Section Integration** - Editors presentation app folded into the shared shell under the tier system

## Phase Details

### Phase 3: Dashboard Shell + Tiered Access

**Goal**: Every staff member lands on a dashboard shell that shows exactly the sections their access tier permits, and the owner can safely manage that role→tier mapping from within it.
**Depends on**: Phase 2 (existing admin app + owner gate)
**Requirements**: SHELL-01, SHELL-02, ACCESS-01, ACCESS-02, ACCESS-03, ACCESS-04
**Success Criteria** (what must be TRUE):

  1. Staff can navigate the 7 sections (Overview, Gallery, Reviews, Reminders, Jinxxy Store, Meetings, Settings) via a sidebar with per-module color accents, and Overview shows bot connection status, last Jinxxy sync, and recent activity.
  2. The owner can view and use every section, including Settings.
  3. A user with the Manager role can view and use the 6 operational modules; Settings responds 403 for them.
  4. An editor can only access their presentation section.
  5. The owner can edit the role→tier mapping from Settings; a Manager cannot self-elevate and the owner can never be locked out.

**Plans**: 8 plans (4 waves)

Plans:
**Wave 1**

- [ ] 03-01-PLAN.md — RED-first test scaffolding: tests/test_app_dashboard.py (SHELL/ACCESS) + tests/test_settings.py mapping cases [Wave 1]
- [ ] 03-02-PLAN.md — Role→tier mapping storage: manager_roles/editor_roles settings keys + Access group field [Wave 1]
- [ ] 03-03-PLAN.md — Overview data plumbing: bot_heartbeat/jinxxy_sync_status/activity_log tables + heartbeat cog [Wave 1]
- [ ] 03-06-PLAN.md — Variant-A shell templates + dashboard.css (base, sidebar, overview, module stub, forbidden) [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [ ] 03-04-PLAN.md — Cog event instrumentation: jinxxy sync status + gallery/reviews/meeting activity_log hooks [Wave 2]
- [ ] 03-05-PLAN.md — 3-tier resolution: _fetch_member_roles, has_editor_role, _resolve_roles/require_manager/TierForbidden [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 03-07-PLAN.md — Dashboard routes + wiring: 6 section routes, /api/overview/status, lifespan init, TierForbidden handler [Wave 3]

**Wave 4** *(blocked on Wave 3)*

- [ ] 03-08-PLAN.md — Human-verify checkpoint: variant-A fidelity + owner/Manager/editor tier matrix [Wave 4]

**UI hint**: yes

### Phase 4: Settings Migration + Name Resolution

**Goal**: The existing owner settings panel lives inside the new shell, and every channel/role field is human-readable.
**Depends on**: Phase 3
**Requirements**: SETT-01, SETT-02
**Success Criteria** (what must be TRUE):

  1. The v1 settings panel appears as a section of the shell with no loss of functionality.
  2. Channel/role fields show a readable name (#channel, @role) with the raw ID shown beneath, resolved via a bot-pushed name cache in the shared sqlite (not a cold Discord REST call from the app).

**Plans**: TBD
**UI hint**: yes

### Phase 5: sqlite Hardening + Action Queue Infrastructure

**Goal**: The shared sqlite and a generic panel-to-bot action pipeline are hardened and proven before any write-heavy module ships on top of them.
**Depends on**: Phase 4
**Requirements**: INFRA-01, INFRA-02
**Success Criteria** (what must be TRUE):

  1. Panel-initiated actions (approve, sync, re-publish) travel through a queue table that the bot dispatches, with each action's status (pending/complete/failed) visible in the panel.
  2. Concurrent panel writes and bot reads/writes against the shared sqlite complete without raising "database is locked" under realistic concurrent load (busy_timeout + retry/backoff proven under test).

**Plans**: TBD

### Phase 6: Reminders CRUD

**Goal**: A Manager can fully manage the reminder lifecycle from the panel without risking a stale-data fire or losing an edit to the scheduler.
**Depends on**: Phase 5
**Requirements**: REM-01, REM-02, REM-03
**Success Criteria** (what must be TRUE):

  1. A Manager can create, edit, and delete reminders via a table + modal pattern.
  2. A Manager can pause and resume a reminder.
  3. A reminder edited or deleted from the panel never fires with stale data, and never loses the edit to the scheduler's write-back (version/re-fetch guard proven under a concurrent-edit test).

**Plans**: TBD
**UI hint**: yes

### Phase 7: Gallery + Reviews Approval Queues

**Goal**: A Manager can moderate the gallery and reviews queues from the panel with the same guarantees as the live reaction flow — no double-publish, no bypassed bookkeeping.
**Depends on**: Phase 6
**Requirements**: GAL-01, GAL-02, GAL-03, REV-01, REV-02
**Success Criteria** (what must be TRUE):

  1. A Manager can see the queue of photos pending approval.
  2. A Manager can approve a photo and it publishes to the website with full parity to the ✅ reaction flow — no double publish if a reaction lands concurrently.
  3. A Manager can remove a published photo (🌙 parity).
  4. A Manager can approve a pending review and it publishes to `reviews.json`.
  5. A Manager can remove a published review from the website.

**Plans**: TBD
**UI hint**: yes

### Phase 8: Jinxxy Manual Sync

**Goal**: A Manager can force a store sync on demand without ever racing the scheduled poll.
**Depends on**: Phase 7
**Requirements**: JINX-01
**Success Criteria** (what must be TRUE):

  1. A Manager can trigger a manual sync and see the status/result of the last sync (disabled/spinner while in-flight).
  2. A manual trigger fired while the periodic poll is running does not double-sync (overlap guard proven under test).

**Plans**: TBD
**UI hint**: yes

### Phase 9: Meetings Browser + Re-publish

**Goal**: Meetings finally have durable storage, and a Manager can review and correct a summary without ever duplicating the forum post.
**Depends on**: Phase 8
**Requirements**: MEET-01, MEET-02, MEET-03
**Success Criteria** (what must be TRUE):

  1. Meetings (transcript + summary) are persisted in the shared sqlite — no longer lost after the bot process restarts.
  2. A Manager can browse the meeting history with transcript and summary.
  3. A Manager can edit a summary and re-publish it to the forum, editing the existing post rather than duplicating it, even on a double-click/retry.

**Plans**: TBD
**UI hint**: yes

### Phase 10: Editors Section Integration

**Goal**: Editors reach their presentation page through the same dashboard shell everyone else uses, under the same tier system.
**Depends on**: Phase 3 (shell + tier system); sequenced last as lowest-risk, lowest-priority integration work
**Requirements**: EDIT-01
**Success Criteria** (what must be TRUE):

  1. The editors presentation section (`editors.nocturna-avatars.site`) is reachable as a dashboard section with its own access tier.
  2. An editor's existing self-serve profile workflow (OAuth, profile edit, media upload, view counter) keeps working unchanged inside the shell.

**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Config Store + Consolidation | v1.0 | 3/3 | Complete | 2026-07-21 |
| 2. Owner Settings Panel | v1.0 | 5/5 | Complete | 2026-07-21 |
| 3. Dashboard Shell + Tiered Access | v2.0 | 0/8 | Not started | - |
| 4. Settings Migration + Name Resolution | v2.0 | 0/TBD | Not started | - |
| 5. sqlite Hardening + Action Queue | v2.0 | 0/TBD | Not started | - |
| 6. Reminders CRUD | v2.0 | 0/TBD | Not started | - |
| 7. Gallery + Reviews Approval Queues | v2.0 | 0/TBD | Not started | - |
| 8. Jinxxy Manual Sync | v2.0 | 0/TBD | Not started | - |
| 9. Meetings Browser + Re-publish | v2.0 | 0/TBD | Not started | - |
| 10. Editors Section Integration | v2.0 | 0/TBD | Not started | - |
