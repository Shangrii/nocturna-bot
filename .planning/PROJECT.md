# Nocturna Bot

## What This Is

A Discord bot for the Nocturna Avatars community that automates the team's content
pipeline: it publishes staff-approved gallery photos, reviews, and store products to the
public website repo (cross-repo GitHub commits), transcribes/summarizes voice meetings,
runs scheduled reminders, and powers a separate FastAPI admin app where editors self-serve
their profile pages. This milestone adds an **owner-only web Settings Panel** so the bot's
safe operational settings can be viewed and edited without SSHing into the host to hand-edit
`.env`.

## Core Value

The owner can change the bot's safe operational settings (channels, staff roles, poll
intervals, timezone, meeting/whisper tuning) from a web panel — no shell access, no restart
for most values — without ever exposing secrets or letting a bad value break a cog.

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

### Active

<!-- Current scope: the Settings Panel milestone. Building toward these. -->

- [ ] Config store: a single source of truth (`core/settings.py`) for what is tunable,
      backed by a `settings` table in the shared sqlite, with typed validation
- [ ] `config.py` consolidation: safe tunables read at-use via `settings.get`; secrets and
      structural values stay frozen from `.env`
- [ ] Owner-only settings panel on the existing admin app (`GET`/`POST /admin/settings`)

### Out of Scope

<!-- Explicit boundaries. Includes reasoning to prevent re-adding. -->

- Editing structural values or secrets — high blast radius / secret exposure; stay in `.env`
- Guild-populated channel/role dropdowns — v1 uses validated ID inputs; live guild fetch is later polish
- Ops console / monitoring / manual action triggers (sync-now, view logs) — v1 is a settings *editor*, not an ops console
- Multi-guild, multi-admin, or a dedicated bot-admin role — single Nocturna guild, single owner
- Live loop-interval hot-swap (`change_interval`) — interval edits apply next cycle/restart

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
| Shared sqlite is the settings channel (panel writes, bot reads) | Both processes already share `DB_PATH`; avoids building IPC/socket/signal | — Pending |
| Reload = read-at-use (`settings.get` at the point of consumption) | A saved change takes effect on the next use; no restart for most values | — Pending |
| Loop-interval edits apply next cycle/restart, not instantly | `@tasks.loop` intervals are read once per cycle; live hot-swap is out of scope | — Pending |
| Access = owner only (`session.discord_id == DISCORD_USER_ID`) | Editing staff-role lists is a trust-boundary change; only the owner may | — Pending |
| Owner gate must fail closed when `DISCORD_USER_ID` is unset (defaults to `0`) | Review note: a `0` default must never authorize; unset config must deny, not open | — Pending |
| Adopt WAL journal mode for the shared sqlite (proposed) | Bot reads + panel writes from two processes; WAL avoids reader/writer lock contention | — Pending |

---
*Last updated: 2026-07-19 after bootstrapping GSD from the settings-panel design spec*
