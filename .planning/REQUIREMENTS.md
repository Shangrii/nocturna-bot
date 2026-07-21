# Requirements: Nocturna Bot — v2.0 Staff Dashboard

**Defined:** 2026-07-21
**Core Value:** The whole staff operates the bot from one web dashboard according to their
access level — owner everything, Managers day-to-day operations, editors their own
presentation pages — with no secrets exposed and no bad value able to break a cog.

## v2.0 Requirements

Requirements for the Staff Dashboard milestone. Each maps to a roadmap phase.
Visual contract: `.planning/sketches/001-dashboard-shell/` (variant A won).

### Dashboard Shell (SHELL)

- [ ] **SHELL-01**: Staff can navigate the 7 sections (Overview, Gallery, Reviews, Reminders,
      Jinxxy Store, Meetings, Settings) via a sidebar with a per-module color accent
      (sketch 001, variant A).
- [ ] **SHELL-02**: Overview shows bot status (connection, last Jinxxy sync, recent activity).

### Tiered Access (ACCESS)

- [ ] **ACCESS-01**: The owner can view and use every section, including Settings.
- [ ] **ACCESS-02**: A user with the Manager role (`1453560115423875205`) can view and use the
      6 operational modules; Settings responds 403 for them.
- [ ] **ACCESS-03**: An editor can only access their presentation section.
- [ ] **ACCESS-04**: The owner can edit the role→tier mapping from Settings; a Manager cannot
      self-elevate and the owner can never be locked out.

### Gallery (GAL)

- [ ] **GAL-01**: A Manager can see the queue of photos pending approval.
- [ ] **GAL-02**: A Manager can approve a photo and it publishes to the website with full
      parity to the ✅ reaction flow — no double publish if a reaction lands concurrently.
- [ ] **GAL-03**: A Manager can remove a published photo (🌙 parity).

### Reviews (REV)

- [ ] **REV-01**: A Manager can approve a pending review and it publishes to `reviews.json`.
- [ ] **REV-02**: A Manager can remove a published review from the website.

### Reminders (REM)

- [ ] **REM-01**: A Manager can create, edit, and delete reminders (table + modal pattern).
- [ ] **REM-02**: A Manager can pause and resume a reminder.
- [ ] **REM-03**: A reminder edited or deleted from the panel never fires with stale data and
      never loses the edit to the scheduler's write-back.

### Jinxxy Store (JINX)

- [ ] **JINX-01**: A Manager can trigger a manual sync and see the status/result of the last
      sync (with an overlap guard against the periodic poll).

### Meetings (MEET)

- [ ] **MEET-01**: Meetings are persisted (transcript + summary) in the shared sqlite — today
      they are not stored anywhere.
- [ ] **MEET-02**: A Manager can browse the meeting history with transcript and summary.
- [ ] **MEET-03**: A Manager can edit a summary and re-publish it to the forum.

### Settings (SETT)

- [ ] **SETT-01**: The v1 settings panel is migrated as a section of the shell with no loss of
      functionality.
- [ ] **SETT-02**: Channel/role fields show a readable name (#channel, @role) with the ID
      beneath, resolved via a cache the bot publishes into the shared sqlite.

### Editors (EDIT)

- [ ] **EDIT-01**: The editors presentation section (`editors.nocturna-avatars.site`) is
      integrated as a dashboard section with its own access tier.

### Infrastructure (INFRA)

- [ ] **INFRA-01**: Panel→bot actions (approve, sync, re-publish) travel through a queue table
      in the shared sqlite that the bot dispatches, with action status visible in the panel.
- [ ] **INFRA-02**: The shared sqlite is hardened for concurrent writers (`busy_timeout` +
      retry) before the first write-heavy module ships.

## Future Requirements

Deferred to a future release. Tracked but not in this roadmap.

- **FUT-01**: Guild-populated channel/role *dropdowns* (SETT-02 ships readable names on ID
  inputs; full dropdown pickers remain future polish).
- **FUT-02**: Overview quick actions (sketch 001 variant C) — approve-from-home, new reminder
  shortcut.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Editing structural values or secrets | High blast radius / secret exposure; stay in `.env` |
| Global module kill-switches (MEE6-style off toggles on Gallery/Reviews/Meetings) | Those flows have no designed "off" state; validated as anti-feature by research |
| Audit-log console / process monitoring / log viewer | v2.0 Overview shows status, not an ops log console |
| Wick-style granular per-permission builder | Three fixed tiers (owner/Manager/editor) are enough for one guild |
| Real-time websocket status updates | Polling/reload is sufficient at this scale |
| Multi-guild support | Single Nocturna guild |
| Live loop-interval hot-swap (`change_interval`) | Interval edits apply next cycle/restart |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SHELL-01 | Phase 3 | Pending |
| SHELL-02 | Phase 3 | Pending |
| ACCESS-01 | Phase 3 | Pending |
| ACCESS-02 | Phase 3 | Pending |
| ACCESS-03 | Phase 3 | Pending |
| ACCESS-04 | Phase 3 | Pending |
| SETT-01 | Phase 4 | Pending |
| SETT-02 | Phase 4 | Pending |
| INFRA-01 | Phase 5 | Pending |
| INFRA-02 | Phase 5 | Pending |
| REM-01 | Phase 6 | Pending |
| REM-02 | Phase 6 | Pending |
| REM-03 | Phase 6 | Pending |
| GAL-01 | Phase 7 | Pending |
| GAL-02 | Phase 7 | Pending |
| GAL-03 | Phase 7 | Pending |
| REV-01 | Phase 7 | Pending |
| REV-02 | Phase 7 | Pending |
| JINX-01 | Phase 8 | Pending |
| MEET-01 | Phase 9 | Pending |
| MEET-02 | Phase 9 | Pending |
| MEET-03 | Phase 9 | Pending |
| EDIT-01 | Phase 10 | Pending |

**Coverage:**
- v2.0 requirements: 23 total
- Mapped to phases: 23/23
- Unmapped: 0

---
*Requirements defined: 2026-07-21*
*Last updated: 2026-07-21 after roadmap creation (Phases 3-10)*
