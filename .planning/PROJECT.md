# Nocturna Bot

## What This Is

A Discord bot for the Nocturna Avatars community that automates the team's content
pipeline: it publishes staff-approved gallery photos, reviews, and store products to the
public website repo (cross-repo GitHub commits), transcribes/summarizes voice meetings,
runs scheduled reminders, and powers a separate FastAPI admin app where editors self-serve
their profile pages. This milestone turns that admin app into a **full staff dashboard**
(MEE6-style, sketch 001 variant A): sidebar navigation across 7 modules with real actions
(gallery approval queue, reminders CRUD, manual Jinxxy sync, reviews moderation, meeting
transcripts), tiered access (owner / Manager / editor), and permissions editable from the
panel itself.

## Core Value

The whole staff operates the bot from one web dashboard according to their access level —
owner gets everything, Managers run day-to-day operations without shell or Discord-reaction
workarounds, editors manage their own presentation pages — with the same guarantees as v1:
no secrets exposed, no bad value able to break a cog.

## Current Milestone: v2.0 Staff Dashboard

**Goal:** Convert the admin panel into a complete MEE6-style dashboard (sketch 001, variant A)
where all staff operate the bot by access tier: owner everything, Managers operations,
editors their own page.

**Target features:**
- Dashboard shell — sidebar with per-module color accents (sketch 001 variant A), 7 sections:
  Overview, Gallery, Reviews, Reminders, Jinxxy Store, Meetings, Settings
- Tiered access — owner: full; Manager role (`1453560115423875205`): everything except
  Settings; editors: their profile/presentation section
- Editable permissions — role→tier assignment (Manager, editor roles) manageable from
  Settings (owner-only)
- Gallery — approval queue: approve/remove photos with parity to the ✅/🌙 reaction flow
- Reviews — approve/remove website reviews from the panel
- Reminders — full CRUD + pause/resume (table + modal pattern)
- Jinxxy Store — manual sync trigger + last-sync status
- Meetings — browse transcripts/summaries; edit and re-publish a summary to the forum
- Settings — v1 panel migrated into the shell, now with readable names (#channel, @role)
  resolved via Discord API, ID shown beneath (POLISH-01 in scope)
- Editors section — the guns.lol-style presentation panel (`editors.nocturna-avatars.site`)
  integrated as a dashboard section

## Requirements

### Validated

<!-- Shipped and confirmed valuable (pre-GSD phases, delivered via the superpowers flow). -->

- ✓ Forum indexing + search of avatar posts — pre-GSD
- ✓ Gallery: staff ✅/🌙 reactions publish/remove photos to the website repo — pre-GSD
- ✓ Reviews: staff-approved reviews published to `reviews.json` — pre-GSD
- ✓ Reminders: scheduled weekly/monthly/one-off reminders with catch-up grace — pre-GSD
- ✓ Jinxxy store sync: periodic poll reflects products into `store.json` — pre-GSD
- ✓ Meetings: voice capture → Whisper transcription → Ollama summary → forum post — pre-GSD
- ✓ Editors admin app (FastAPI): Discord OAuth + live role re-check, self-serve profile
  editor, image/media upload, view counter — pre-GSD
- ✓ Config store: `core/settings.py` (schema + get/set/all_for_ui) backed by a `settings`
  table in the shared sqlite, with per-type validation rejecting bad IDs/intervals/TZ before
  any write — Validated in Phase 1: Config Store + Consolidation
- ✓ `config.py` consolidation: the 19 safe tunables read at-use via `settings.get` through a
  PEP 562 `__getattr__` shim; secrets/structural values stay frozen from `.env`; behavior
  byte-identical until an owner edits — Validated in Phase 1: Config Store + Consolidation
- ✓ Owner-only settings panel on the existing admin app (`GET`/`POST /admin/settings`):
  owner-gated (fails closed on unset `DISCORD_USER_ID`), typed fields grouped by feature,
  server-side validate-then-write, no secrets rendered; snowflakes string-serialized end-to-end
  and raw values (not resolved fallbacks) round-tripped — Validated in Phase 2: Owner Settings Panel

### Active

<!-- Current scope: the v2.0 Staff Dashboard milestone. Building toward these. -->

- Dashboard shell with sidebar navigation across 7 modules (sketch 001 variant A)
- Tiered access: owner / Manager role / editors, with role→tier assignment editable in
  Settings (owner-only)
- Gallery approval queue with reaction-flow parity
- Reviews approve/remove from the panel
- Reminders CRUD + pause/resume
- Jinxxy manual sync + status
- Meetings transcript/summary browser with edit + re-publish
- Settings migrated into the shell with Discord-API-resolved readable names
- Editors presentation section integrated into the dashboard

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Editing structural values or secrets — high blast radius / secret exposure; stay in `.env`
- Multi-guild support — single Nocturna guild
- Live loop-interval hot-swap (`change_interval`) — interval edits apply next cycle/restart
- Log viewer / process monitoring — v2.0 shows bot status on Overview, not an ops log console
- Overview quick actions (variant C of sketch 001) — variant A won; actions live in their modules

<!-- Superseded in v2.0 (were out of scope in v1.0):
     - Guild channel/role name resolution (POLISH-01) — now in scope via Discord API
     - Manual action triggers — Jinxxy sync-now now in scope
     - Non-owner admin access — Manager tier now in scope -->

## Context

- Design spec (approved): `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md`.
  This milestone was bootstrapped into GSD from that spec.
- All config currently lives in `config.py` (~50 `os.getenv` reads from `.env`). It is NOT
  scattered — the pain is volume + no way to see/change it without shell access.
- The bot process and the FastAPI admin app are two separate processes (separate systemd
  units on host "cinema") that already **share the sqlite file** (`DB_PATH`). The panel
  writes settings; the bot reads them. No IPC/socket/signal is built — sqlite is the channel.
- DB access idiom (`core/db.py`): fresh connection per call, `CREATE TABLE IF NOT EXISTS`
  init functions called from each cog's `__init__`. The `settings` table follows this idiom.
- Codebase is well-maintained: parameterized SQL throughout, explicit column allowlists for
  dynamic updates, privacy-conscious IP hashing, a single documented auth choke-point
  (`app/deps.py::require_editor`). `require_owner` extends that pattern.

## Constraints

- **Tech stack**: Python 3, discord.py (bot), FastAPI + Starlette SessionMiddleware +
  Discord OAuth (admin app), sqlite (shared store), stdlib + Pydantic for models.
- **Security**: Secrets (`BOT_TOKEN`, `GITHUB_PAT`, `JINXXY_API_KEY`, `SESSION_SECRET`, OAuth
  client id/secret) are never read into the panel, never rendered, never editable.
- **Security**: Validation is load-bearing in `settings.set` — a crafted POST must not be able
  to store a value that would break a cog (ID shape `^\d{17,20}$`, int ranges, TZ resolves via
  `zoneinfo.ZoneInfo`, enums/toggles constrained).
- **Compatibility**: The seed/migration must be byte-identical to current `.env` behavior until
  the owner edits something — no destructive migration, no behavior change on deploy.
- **Concurrency**: Two processes share one sqlite file with the panel now adding writes from the
  second process — the access mode (WAL vs default) must be decided so bot reads and panel
  writes don't collide with "database is locked" (see Key Decisions).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Shared sqlite is the settings channel (panel writes, bot reads) | Both processes already share `DB_PATH`; avoids building IPC/socket/signal | ✓ Validated in Phase 1 |
| Reload = read-at-use (`settings.get` at the point of consumption) | A saved change takes effect on the next use; no restart for most values | ✓ Validated in Phase 1 |
| Loop-interval edits apply next cycle/restart, not instantly | `@tasks.loop` intervals are read once per cycle; live hot-swap is out of scope | ✓ Validated in Phase 2 |
| Access = owner only (`session.discord_id == DISCORD_USER_ID`) | Editing staff-role lists is a trust-boundary change; only the owner may | ✓ Validated in Phase 2 (`require_owner`) |
| Owner gate must fail closed when `DISCORD_USER_ID` is unset (defaults to `0`) | Review note: a `0` default must never authorize; unset config must deny, not open | ✓ Validated in Phase 2 |
| Adopt WAL journal mode for the shared sqlite | Bot reads + panel writes from two processes; WAL avoids reader/writer lock contention | ✓ Validated in Phase 1 (`PRAGMA journal_mode=WAL` on every connection) |
| v2.0: Admin app calls Discord API to resolve channel/role names | Readable names (#channel, @role) in the dashboard; partially revisits the v1 "no bot credentials in the admin app" stance — scope/credential choice decided at planning | — Pending (v2.0) |
| v2.0: Access tiers = owner > Manager role > editor, tier assignment editable in Settings (owner-only) | One dashboard for all staff; permission edits are a trust-boundary change so they stay owner-gated | — Pending (v2.0) |

## Current State

Milestone v1.0 (Settings Panel) shipped 2026-07-21: config store + consolidation (Phase 1)
and the owner-only settings panel (Phase 2), verification 4/4, full suite 645 passing,
`02-SECURITY.md` produced via `/gsd:secure-phase 2`. Open advisory items: 6 code-review
warnings in the archived `02-REVIEW.md`.

Milestone v2.0 (Staff Dashboard) started 2026-07-21 — defining requirements. Visual contract:
`.planning/sketches/001-dashboard-shell/` (variant A won).

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-21 after starting milestone v2.0 (Staff Dashboard)*
