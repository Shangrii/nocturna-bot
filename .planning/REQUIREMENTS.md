# Requirements: Nocturna Bot — Settings Panel

**Defined:** 2026-07-19
**Core Value:** The owner can change the bot's safe operational settings from a web panel — no shell access, no restart for most values — without exposing secrets or letting a bad value break a cog.

## v1 Requirements

Requirements for the Settings Panel milestone. Each maps to a roadmap phase.

### Config Store (Phase 1)

- [ ] **STORE-01**: `core/settings.py` exposes `get(key)`, `set(key, value)`, and
      `all_for_ui()` as the single source of truth for what is tunable (key, type, default,
      validation, owning feature).
- [ ] **STORE-02**: A `settings` table (`key TEXT PRIMARY KEY, value TEXT` JSON-encoded)
      exists in the shared sqlite, created via the `CREATE TABLE IF NOT EXISTS` idiom in
      `core/db.py`.
- [ ] **STORE-03**: `settings.set` validates every value against the schema and raises a typed
      `SettingRejected(reason)` on invalid input, writing nothing (ID shape `^\d{17,20}$`, int
      ranges, TZ resolves via `zoneinfo.ZoneInfo`, enums/toggles constrained).
- [ ] **STORE-04**: `settings.get` never raises — a missing or corrupt row falls back to the
      `.env`/default seed so the bot always has a usable value.
- [ ] **STORE-05**: On startup the `settings` table is idempotently seeded from the current
      `.env`/defaults for any key not already present; behavior is byte-identical until the
      owner edits something (no destructive migration).

### Config Consolidation (Phase 1)

- [ ] **CONF-01**: The safe-tunable constants in `config.py` are read through `settings.get(...)`
      at the point of use (read-at-use), replacing import-time freezing for those keys only.
- [ ] **CONF-02**: Secrets and structural values in `config.py` stay exactly as they are —
      frozen from `.env`, never migrated into the store.
- [ ] **CONF-03**: The staff-role lists keep their fallback-to-`GALLERY_STAFF_ROLE_IDS`-when-empty
      semantic (REVIEWS/REMINDERS/JINXXY) after migration.

### Concurrency (Phase 1)

- [ ] **CONC-01**: The shared-sqlite access mode is decided and applied so the bot's reads and
      the panel's writes (two processes, one file) do not collide with "database is locked".

### Settings Panel (Phase 2)

- [ ] **PANEL-01**: A `require_owner` dependency in `app/deps.py` gates the panel to
      `session.discord_id == config.DISCORD_USER_ID`, returning 403 otherwise, and **fails
      closed** when `DISCORD_USER_ID` is unset (the `0` default must never authorize).
- [ ] **PANEL-02**: `GET /admin/settings` renders a form grouped by feature from
      `settings.all_for_ui()`, each field typed (channel/role IDs as validated number inputs,
      intervals as numbers, TZ as a select, toggles as checkboxes, prompts as text). Secrets
      never appear.
- [ ] **PANEL-03**: `POST /admin/settings` validates every field server-side via `settings.set`,
      writes the table, and re-renders with a success/error banner. An invalid value is rejected
      before any write, so the bot never reads a bad value.
- [ ] **PANEL-04**: A saved change is read by the bot on its next relevant use (reaction gate,
      poll cycle, reminder tick); loop-interval changes apply on the next cycle/restart.

## v2 Requirements

Deferred to a future release. Tracked but not in this roadmap.

### Panel polish

- **POLISH-01**: Channel/role dropdowns populated from the guild via the bot token (v1 uses
  validated ID inputs).

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Editing structural values or secrets | High blast radius / secret exposure; stay in `.env` |
| Ops console / monitoring / manual triggers (sync-now, view logs, manage reminders) | v1 is a settings *editor*, not an ops console |
| Multi-guild, multi-admin, or a dedicated bot-admin role | Single Nocturna guild, single owner |
| Live loop-interval hot-swap (`change_interval`) | Interval edits apply next cycle/restart |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| STORE-01 | Phase 1 | Pending |
| STORE-02 | Phase 1 | Pending |
| STORE-03 | Phase 1 | Pending |
| STORE-04 | Phase 1 | Pending |
| STORE-05 | Phase 1 | Pending |
| CONF-01 | Phase 1 | Pending |
| CONF-02 | Phase 1 | Pending |
| CONF-03 | Phase 1 | Pending |
| CONC-01 | Phase 1 | Pending |
| PANEL-01 | Phase 2 | Pending |
| PANEL-02 | Phase 2 | Pending |
| PANEL-03 | Phase 2 | Pending |
| PANEL-04 | Phase 2 | Pending |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2026-07-19*
*Last updated: 2026-07-19 after initial definition*
