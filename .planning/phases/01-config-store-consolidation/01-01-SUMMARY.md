---
phase: 01-config-store-consolidation
plan: 01
subsystem: testing
tags: [wave-0, test-first, config-store, tdd-red]
requires: []
provides:
  - "tests/test_settings.py — 14 failing tests defining the core.settings + core.db.init_settings surface"
  - "read-at-use gate test in each of the four migrated-cog test files"
affects:
  - "01-02 (store implementation turns test_settings.py green)"
  - "01-03 (consolidation turns the cog read-at-use tests green)"
tech-stack:
  added: []
  patterns:
    - "DB isolation via monkeypatch.setattr(config, 'DB_PATH', str(tmp_path/...)) (mirrors test_counter_app.py:23)"
    - "values written through settings.set / direct row insert, never monkeypatch.setattr(config, <tunable>)"
    - "autouse config pins stripped with monkeypatch.delattr so config.X falls through to the future __getattr__ shim"
key-files:
  created:
    - "tests/test_settings.py"
  modified:
    - "tests/test_gallery_cog.py"
    - "tests/test_reviews_cog.py"
    - "tests/test_reminders_cog.py"
    - "tests/test_jinxxy_cog.py"
decisions:
  - "Adding module-level 'from core import settings' to the cog test files makes them RED at collection until 01-02 ships core/settings.py — accepted, per the plan's explicit import instruction"
metrics:
  tasks: 2
  files_created: 1
  files_modified: 4
  duration: "~15m"
  completed: 2026-07-21
---

# Phase 01 Plan 01: Wave 0 Test Scaffolding Summary

Test-first scaffold for the config store: a new `tests/test_settings.py` with 14 failing tests
that define the `core.settings` / `core.db.init_settings` contract, plus one read-at-use gate
test appended to each of the four migrated-cog test files — all RED by design, turning green in
01-02 (the store) and 01-03 (the consolidation).

## What Was Built

**Task 1 — `tests/test_settings.py` (new, 14 tests):**
- STORE-01 round-trip (`test_round_trip_get_set`, `test_all_for_ui_grouped`)
- STORE-02 table creation + idempotent init (`test_init_table_creates_settings`)
- STORE-03 per-type validation: bad snowflake / bad interval / bad timezone reject via
  `SettingRejected` and write nothing; free-string model accepted (Pitfall 4)
- STORE-04 `get` never raises: missing row / missing table (Pitfall 2) / corrupt JSON → default
- STORE-05 idempotent seed matching config defaults
- CONF-03 staff-role fallback to `GALLERY_STAFF_ROLE_IDS`
- CONC-01 WAL active + concurrent read/write without "database is locked"

Every test isolates the DB via `config.DB_PATH` → a `tmp_path` file, and writes only through
`settings.set` or a direct `db._get_conn()` row insert — never `monkeypatch.setattr(config, ...)`
for a safe tunable.

**Task 2 — one read-at-use test per migrated cog:**
- `test_gallery_staff_gate_reads_at_use` (GALLERY_STAFF_ROLE_IDS)
- `test_reviews_staff_gate_reads_at_use` (REVIEWS_STAFF_ROLE_IDS + empty-list → gallery fallback, CONF-03)
- `test_reminders_staff_gate_reads_at_use` (REMINDERS_STAFF_ROLE_IDS)
- `test_jinxxy_announce_channel_reads_at_use` (JINXXY_ANNOUNCE_CHANNEL_ID)

Each new test's first statements `monkeypatch.delattr(config, "<KEY>", raising=False)` for every
key that file's autouse fixture pins (gallery 2, reviews 2, reminders 1, jinxxy 2 — 7 total), so
`config.X` falls through to the future `__getattr__`/`settings.get` shim rather than a value frozen
in `config.__dict__`. Value changes are driven through `settings.set`. Added the module-level
`from core import db` / `from core import settings` imports each file needed (gallery already had
`db`; the other three lacked both).

## Verification

- `python -m py_compile` succeeds for all five files.
- Grep gates pass: 14 named store tests present; all four cog read-at-use test names present;
  `monkeypatch.delattr(config` counts are gallery 2, reviews 2, reminders 1, jinxxy 2.
- `pytest tests/test_settings.py -q` → ERROR at collection (`ModuleNotFoundError: core.settings`) — the intended Wave 0 RED.
- The four cog files → ERROR at collection (`cannot import name 'settings' from 'core'`) — same intended RED, sole cause is the not-yet-created `core/settings.py`.

## Deviations from Plan

None — plan executed exactly as written.

## Known Wave 0 State (not a stub, not a bug)

The plan explicitly instructs adding a module-level `from core import settings` import to the four
cog test files. Because `core/settings.py` does not exist until 01-02, this makes those four files
**error at collection**, and pytest's default behavior halts the whole session on collection errors
— so a bare `pytest` run currently collects zero tests. This is the intended test-first RED window:

- 01-02 ships `core/settings.py` + `core.db.init_settings` → all five files collect again; the 14
  `test_settings.py` tests go green; the pre-existing cog tests (untouched) run green again.
- 01-03 removes config.py's frozen module-level assignments and adds the `config.__getattr__` shim
  → the four read-at-use assertions go green (CONF-01/CONF-03).

The pre-existing cog tests' code was not modified (only imports added + one test appended per file),
so CONF-02 (secrets/structural regression) is unaffected once collection resolves in 01-02.

## Self-Check: PASSED

- FOUND: tests/test_settings.py
- FOUND: tests/test_gallery_cog.py (modified — new test + imports)
- FOUND: tests/test_reviews_cog.py (modified — new test + imports)
- FOUND: tests/test_reminders_cog.py (modified — new test + imports)
- FOUND: tests/test_jinxxy_cog.py (modified — new test + imports)
- FOUND commit 0763575 (Task 1: test_settings.py)
- FOUND commit 2655ec3 (Task 2: four cog read-at-use tests)
