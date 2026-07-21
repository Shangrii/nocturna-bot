# Milestones

## v1.0 — Settings Panel (shipped 2026-07-21)

**Goal:** Owner-only web Settings Panel so the bot's safe operational settings can be viewed
and edited without shell access to hand-edit `.env`.

**Delivered:**
- Config store `core/settings.py` (schema + get/set/all_for_ui) backed by a `settings` table
  in the shared sqlite, per-type validation, WAL journal mode
- `config.py` consolidation: 19 safe tunables read-at-use via PEP 562 `__getattr__` shim;
  secrets/structural values frozen from `.env`
- Owner-gated `GET`/`POST /admin/settings` on the admin app: fails closed on unset
  `DISCORD_USER_ID`, typed fields grouped by feature, validate-then-write, no secrets rendered

**Phases:** 01 (Config Store + Consolidation), 02 (Owner Settings Panel) — archived at
`.planning/milestones/v1.0-settings-panel/phases/`

**Verification:** 4/4 success criteria, full suite 645 passing, `02-SECURITY.md` via
`/gsd:secure-phase 2`. Open advisory: 6 code-review warnings in archived `02-REVIEW.md`.

---

## v2.0 — Staff Dashboard (in progress, started 2026-07-21)

**Goal:** Convert the admin panel into a complete MEE6-style dashboard (sketch 001 variant A)
where all staff operate the bot by access tier: owner everything, Managers operations,
editors their own presentation page.
