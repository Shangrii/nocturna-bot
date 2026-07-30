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

- [x] **Phase 3: Dashboard Shell + Tiered Access** - Sidebar shell across 7 modules with owner/Manager/editor tiers, editable role→tier mapping, POST-only convention (completed 2026-07-22)
- [ ] **Phase 4: Settings Migration + Name Resolution** - v1 panel folded into the shell; readable #channel/@role names via bot-pushed cache
- [ ] **Phase 5: sqlite Hardening + Action Queue** - busy_timeout/retry on write paths; generic action_queue infra every write-heavy module reuses
- [ ] **Phase 6: Reminders CRUD** - Full CRUD + pause/resume via table+modal, scheduler-race guard
- [ ] **Phase 7: Gallery + Reviews Approval Queues** - Approve/remove photos and reviews with reaction-flow parity, race-free
- [x] **Phase 8: Jinxxy Manual Sync** - Manual sync trigger + last-run status, overlap-guarded against the poll
 (completed 2026-07-28)
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

- [x] 03-01-PLAN.md — RED-first test scaffolding: tests/test_app_dashboard.py (SHELL/ACCESS) + tests/test_settings.py mapping cases [Wave 1]
- [x] 03-02-PLAN.md — Role→tier mapping storage: manager_roles/editor_roles settings keys + Access group field [Wave 1]
- [x] 03-03-PLAN.md — Overview data plumbing: bot_heartbeat/jinxxy_sync_status/activity_log tables + heartbeat cog [Wave 1]
- [x] 03-06-PLAN.md — Variant-A shell templates + dashboard.css (base, sidebar, overview, module stub, forbidden) [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [x] 03-04-PLAN.md — Cog event instrumentation: jinxxy sync status + gallery/reviews/meeting activity_log hooks [Wave 2]
- [x] 03-05-PLAN.md — 3-tier resolution: _fetch_member_roles, has_editor_role, _resolve_roles/require_manager/TierForbidden [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [x] 03-07-PLAN.md — Dashboard routes + wiring: 6 section routes, /api/overview/status, lifespan init, TierForbidden handler [Wave 3]

**Wave 4** *(blocked on Wave 3)*

- [x] 03-08-PLAN.md — Human-verify checkpoint: variant-A fidelity + owner/Manager/editor tier matrix [Wave 4]

**UI hint**: yes

### Phase 4: Settings Migration + Name Resolution

**Goal**: The existing owner settings panel lives inside the new shell, and every channel/role field is human-readable.
**Depends on**: Phase 3
**Requirements**: SETT-01, SETT-02
**Success Criteria** (what must be TRUE):

  1. The v1 settings panel appears as a section of the shell with no loss of functionality.
  2. Channel/role fields show a readable name (#channel, @role) with the raw ID shown beneath, resolved via a bot-pushed name cache in the shared sqlite (not a cold Discord REST call from the app).

**Plans**: 4 plans (3 waves)

Plans:
**Wave 1**

- [ ] 04-01-PLAN.md — Wave-0: discord_names sqlite triad (contract) + RED test scaffolds for migration & resolution [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [ ] 04-02-PLAN.md — Bot-side name cache: cogs/discord_names.py push loop + mapping helpers + bot.py wiring [Wave 2]
- [ ] 04-03-PLAN.md — App-side migration: settings.html into the shell + name resolution (route/template/css) [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 04-04-PLAN.md — Human-verify checkpoint: visual fidelity + name resolution + owner-gate + no-loss save [Wave 3]
**UI hint**: yes

### Phase 5: sqlite Hardening + Action Queue Infrastructure

**Goal**: The shared sqlite and a generic panel-to-bot action pipeline are hardened and proven before any write-heavy module ships on top of them.
**Depends on**: Phase 4
**Requirements**: INFRA-01, INFRA-02
**Success Criteria** (what must be TRUE):

  1. Panel-initiated actions (approve, sync, re-publish) travel through a queue table that the bot dispatches, with each action's status (pending/complete/failed) visible in the panel.
  2. Concurrent panel writes and bot reads/writes against the shared sqlite complete without raising "database is locked" under realistic concurrent load (busy_timeout + retry/backoff proven under test).

**Plans**: 5 plans (3 waves)

Plans:
**Wave 1**

- [ ] 05-01-PLAN.md — DB hardening (busy_timeout, D-11) + core/action_queue.py state machine + RED contract tests [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [ ] 05-02-PLAN.md — ActionQueueCog 1.5s dispatch loop + noop proof action + bot.py registration [Wave 2]
- [ ] 05-03-PLAN.md — Manager-gated /api/actions routes + Overview inline-status proof card (Alpine short-poll, D-07 offline) [Wave 2]
- [ ] 05-04-PLAN.md — D-12 concurrent-load go/no-go gate (zero unhandled "database is locked") [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 05-05-PLAN.md — Human-verify checkpoint: live inline auto-refresh + Retry + bot-offline/reconnect durability [Wave 3]

### Phase 6: Reminders CRUD

**Goal**: A Manager can fully manage the reminder lifecycle from the panel without risking a stale-data fire or losing an edit to the scheduler.
**Depends on**: Phase 5
**Requirements**: REM-01, REM-02, REM-03
**Scope expansion (owner decision 2026-07-23, CONTEXT D-05/D-06)**: also adds a new `biweekly`
frequency to the reminder engine (panel + Discord `/recordatorio` parity). Bookkeeping follow-up:
add REM-04 (biweekly recurrence) to REQUIREMENTS.md.
**Success Criteria** (what must be TRUE):

  1. A Manager can create, edit, and delete reminders via a table + modal pattern.
  2. A Manager can pause and resume a reminder.
  3. A reminder edited or deleted from the panel never fires with stale data, and never loses the edit to the scheduler's write-back (version/re-fetch guard proven under a concurrent-edit test).

**Plans**: 6 plans (4 waves)

Plans:
**Wave 1**

- [ ] 06-01-PLAN.md — Extract pure schedule math to core/reminder_schedule.py + biweekly + is_imminent [Wave 1]
- [ ] 06-02-PLAN.md — DB optimistic-version guard + paused column/migration + LOCKED D-17 concurrent-edit test [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [ ] 06-03-PLAN.md — Cog: biweekly Discord parity + version-guarded scheduler write-back [Wave 2]
- [ ] 06-04-PLAN.md — App backend: app/routers/reminders.py CRUD/pause/resume/preview (Manager-gated, 409 guard) [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 06-05-PLAN.md — Frontend: reminders.html table+modal+confirm + dashboard.css reminders block [Wave 3]

**Wave 4** *(blocked on Wave 3)*

- [ ] 06-06-PLAN.md — Human-verify checkpoint: Manager CRUD + biweekly + gate + imminent caveats [Wave 4]
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

**Plans**: 5 plans (4 waves)

Plans:
**Wave 1**

- [ ] 07-01-PLAN.md — Bot-side queue cache: core/db.py gallery_queue/reviews_queue helpers + cogs/gallery_reviews_cache.py push-cache cog (D-01/D-02, anonymity-safe)
- [ ] 07-02-PLAN.md — Four action_queue kind handlers with pre/post 🟢-marker state check (GAL-02/03, REV-01/02, D-08/D-11)

**Wave 2** *(blocked on Wave 1)*

- [ ] 07-03-PLAN.md — Manager-gated app/routers/gallery.py + reviews.py (page + JSON refresh + approve/remove enqueue), app/main.py wiring

**Wave 3** *(blocked on Wave 2)*

- [ ] 07-04-PLAN.md — Frontend: gallery.html + reviews.html (Pending|Published tabs, grid/cards, lightbox, inline status, confirm) + dashboard.css blocks

**Wave 4** *(blocked on Wave 3)*

- [ ] 07-05-PLAN.md — Human-verify checkpoint: live queue visibility + approve/remove parity + no-double-publish + anonymity
**UI hint**: yes

### Phase 8: Jinxxy Manual Sync

**Goal**: A Manager can force a store sync on demand without ever racing the scheduled poll.
**Depends on**: Phase 7
**Requirements**: JINX-01
**Success Criteria** (what must be TRUE):

  1. A Manager can trigger a manual sync and see the status/result of the last sync (disabled/spinner while in-flight).
  2. A manual trigger fired while the periodic poll is running does not double-sync (overlap guard proven under test).

**Plans**: 8 plans (5 waves)

Plans:
**Wave 1**

- [x] 08-01-PLAN.md — Widen jinxxy_sync_status via the ADD-COLUMN idiom (running/started_at/source/actor_name + D-09 counts) + core/action_queue.enqueue_deduped (D-04)
- [x] 08-02-PLAN.md — Persist the OAuth-verified username into the session and thread it into the roles dict (D-07/D-12 attribution source)

**Wave 2** *(blocked on Wave 1)*

- [x] 08-03-PLAN.md — The overlap guard: asyncio.Lock + _run_sync_guarded + mirror writes + startup clear; _poll and /tienda sync refactored onto it, one _announce call site (D-01/D-02/D-03/D-05/D-06)
- [x] 08-06-PLAN.md — Manager-gated app/routers/jinxxy.py (page + status JSON + deduped enqueue POST), shared heartbeat helper, module stub removed (D-04/D-06/D-13/D-15)

**Wave 3** *(blocked on Wave 2)*

- [x] 08-04-PLAN.md — Sync instrumentation: sync_error_category() + counts persistence + source/actor attribution in the activity line (D-09/D-10/D-12)
- [x] 08-07-PLAN.md — Frontend: jinxxy.html status card + one-click Sync button + Alpine state machine + read-only product table + empty states, narrow dashboard.css additions (D-01/D-07/D-14/D-15/D-16)

**Wave 4** *(blocked on Wave 3)*

- [x] 08-05-PLAN.md — cogs/action_queue_worker.py: the single new jinxxy_sync dispatch kind, count-shaped result, D-10 category mapping (D-01/D-09/D-10/D-11)

**Wave 5** *(blocked on Waves 3-4)*

- [x] 08-08-PLAN.md — Phase gate (full suite + overlap-guard proof) and human-verify checkpoint: live disabled/spinner/elapsed/attribution + collision + real store round-trip
**UI hint**: yes

### Phase 9: Meetings Browser + Re-publish

**Goal**: Meetings finally have durable storage, and a Manager can review and correct a summary without ever duplicating the forum post.
**Depends on**: Phase 8
**Requirements**: MEET-01, MEET-02, MEET-03
**Success Criteria** (what must be TRUE):

  1. Meetings (transcript + summary) are persisted in the shared sqlite — no longer lost after the bot process restarts.
  2. A Manager can browse the meeting history with transcript and summary.
  3. A Manager can edit a summary and re-publish it to the forum, editing the existing post rather than duplicating it, even on a double-click/retry.

**Plans**: 5 plans (3 waves)

Plans:
**Wave 1**

- [ ] 09-01-PLAN.md — Core storage + per-entity dedupe: meetings table + CRUD in core/db.py, backward-compatible dedupe_key column + generalized enqueue_deduped, RED-first tests (MEET-01/03) [Wave 1]
- [ ] 09-02-PLAN.md — Frontend templates: meetings.html (reverse-chron list) + meeting_detail.html (summary editor + Alpine republish state machine + collapsible transcript + D-14/D-09 states) [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [ ] 09-03-PLAN.md — Bot-side: persist on _publish both paths (D-14) + attendee snapshot + archived-safe _republish + idempotent on_ready backfill + worker meeting_republish dispatch (MEET-01/03) [Wave 2]
- [ ] 09-04-PLAN.md — Manager-gated app/routers/meetings.py (list/detail/republish, per-meeting dedupe, no bot creds) + app/main.py wiring + stub deletion (MEET-02/03) [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 09-05-PLAN.md — Phase gate (full suite) + human-verify checkpoint: live no-duplicate re-publish + archived-thread edit + MANAGE_THREADS + restart persistence [Wave 3]
**UI hint**: yes

### Phase 10: Editors Section Integration

**Goal**: Editors reach their presentation page through the same dashboard shell everyone else uses under the same tier system, editor pages get short vanity URLs, and the editor surface is polished to match the shell.
**Depends on**: Phase 3 (shell + tier system)
**Requirements**: EDIT-01, EDIT-02
**Scope expansion (owner decision 2026-07-29, CONTEXT D-01..D-07)**: pulled the maximal "full
experience" scope IN — full shell wrap + **vanity URLs** (new public-site routing, EDIT-02) +
**integrate-and-polish** (not integrate-as-is). SC2 softened from "unchanged" to **workflow parity**.
**Success Criteria** (what must be TRUE):

  1. The editors presentation section is integrated as a dashboard section under the editor tier: `/editor` renders inside the shell (topbar + sidebar), Editor is a real 8th data-driven section, and a non-editor clicking the locked entry is denied via `forbidden.html` WITHOUT being logged out (Pitfall-1 fix).
  2. The editor's self-serve workflow keeps **workflow parity** (OAuth, publish-on-save, media upload+re-encode, self-unpublish, IDOR guards behave identically) while the chrome is retinted onto dashboard tokens and the three named polish items ship — the live-preview canvas is unchanged.
  3. Published editor pages are served at `nocturna-avatars.site/{slug}` (vanity URL), with legacy `/e/{slug}` links redirecting; an editor cannot claim a slug that collides with a reserved public-site route.

**Plans**: 7 plans (4 waves)

Plans:
**Wave 1**

- [x] 10-01-PLAN.md — RED-first test scaffolding: locked-nav session-preservation, in-shell render, widened reserved-word cases (EDIT-01/EDIT-02) [Wave 1]
- [x] 10-03-PLAN.md — CSS reconciliation: dashboard.css `--accent-editor`/`.status-badge.pending` + editor.css chrome retint (preview canvas frozen) + polish rules (EDIT-01) [Wave 1]
- [x] 10-06-PLAN.md — Astro vanity route: move `e/[slug].astro` → root `[slug].astro` + legacy redirect stub (EDIT-02) [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [x] 10-02-PLAN.md — Backend security fix: GET `/editor` tier-gate split (`_resolve_roles`+`TierForbidden`, no session clear) + widen `RESERVED_SLUGS` (EDIT-01/EDIT-02) [Wave 2]
- [ ] 10-04-PLAN.md — Sidebar 8th editor section + `is_editor` lock branch + remove topbar Back-to-editor link (EDIT-01) [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 10-05-PLAN.md — `editor.html` shell wrap: extend `_dashboard_base.html`, sticky `.editor-subhead`, drop `/e/` link segment (EDIT-01) [Wave 3]

**Wave 4** *(blocked on Wave 3)*

- [ ] 10-07-PLAN.md — Phase gate (full pytest + Astro build) + human-verify checkpoint: in-shell editor, vanity URL + redirect, non-editor stays logged in [Wave 4]
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|-----------------|--------|-----------|
| 1. Config Store + Consolidation | v1.0 | 3/3 | Complete | 2026-07-21 |
| 2. Owner Settings Panel | v1.0 | 5/5 | Complete | 2026-07-21 |
| 3. Dashboard Shell + Tiered Access | v2.0 | 8/8 | Complete   | 2026-07-22 |
| 4. Settings Migration + Name Resolution | v2.0 | 0/TBD | Not started | - |
| 5. sqlite Hardening + Action Queue | v2.0 | 0/5 | Not started | - |
| 6. Reminders CRUD | v2.0 | 0/6 | Not started | - |
| 7. Gallery + Reviews Approval Queues | v2.0 | 0/5 | Not started | - |
| 8. Jinxxy Manual Sync | v2.0 | 8/8 | Complete   | 2026-07-28 |
| 9. Meetings Browser + Re-publish | v2.0 | 0/5 | Not started | - |
| 10. Editors Section Integration | v2.0 | 4/7 | In Progress|  |
