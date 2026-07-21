# Roadmap: Nocturna Bot — Settings Panel

## Overview

The bot and its editors admin app already ship (pre-GSD, delivered via the superpowers flow).
This milestone adds an owner-only web Settings Panel. The work splits cleanly into two phases:
first the **config store + consolidation** (the prerequisite that carries most of the risk —
introducing a validated settings store and routing `config.py`'s safe tunables through it
without changing any behavior), then the **panel** itself (an owner-gated form on the existing
FastAPI admin app that reads and writes that store). Phase 2 depends entirely on Phase 1.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Config Store + Consolidation** - Validated settings store in shared sqlite; `config.py` safe tunables read at-use (completed 2026-07-21)
- [x] **Phase 2: Owner Settings Panel** - Owner-gated `GET`/`POST /admin/settings` form on the existing admin app (completed 2026-07-21)

## Phase Details

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

**Plans**: 4 plans (3 waves)

Plans:
**Wave 1**

- [x] 02-01-PLAN.md — Store metadata extension (all_for_ui label/min/max/tz-options) + validate_only dry-run [Wave 1]
- [x] 02-02-PLAN.md — require_owner gate in app/deps.py, fail-closed on the 0 default [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-03-PLAN.md — settings.html form (typed fields + per-field errors), owner-only editor link, inline-error CSS [Wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-04-PLAN.md — GET/POST /admin/settings routes (atomic validate-then-write) + is_owner context + integration tests [Wave 3]

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Config Store + Consolidation | 3/3 | Complete   | 2026-07-21 |
| 2. Owner Settings Panel | 4/4 | Complete   | 2026-07-21 |
