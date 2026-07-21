---
phase: 01-config-store-consolidation
plan: 02
subsystem: config-store
tags: [wave-2, config-store, sqlite, validation, wal, tdd-green]
requires:
  - "01-01 (tests/test_settings.py — the 14 failing tests this plan turns green)"
provides:
  - "core/settings.py — get/set/all_for_ui/seed_defaults/SettingRejected + 19-key _SCHEMA"
  - "core/db.py::init_settings() — the key/value settings table (STORE-02)"
  - "core/db.py WAL journal mode in _get_conn() (CONC-01)"
affects:
  - "01-03 (consolidation: config.__getattr__ shim reads through settings.get; wires seed_defaults into bot.py::main)"
  - "Phase 2 panel (all_for_ui feeds the render; set()'s validators are the load-bearing HTTP POST gate)"
tech-stack:
  added: []
  patterns:
    - "SettingRejected(ValueError) with .reason — mirrors core/editors_model.py::SlugRejected"
    - "pure module: stdlib + core.db + read-only config (no discord.py/FastAPI) — mirrors core/store_sync.py"
    - "INSERT ... ON CONFLICT(key) DO UPDATE SET value=excluded.value upsert (mirrors db.set_presence)"
    - "broad `except Exception` never-raises read fallback (STORE-04, mirrors app/main.py lifespan init)"
    - "runtime (not import-time) empty-list -> fallback_key resolution for staff-role cascade (CONF-03)"
key-files:
  created:
    - "core/settings.py"
  modified:
    - "core/db.py"
decisions:
  - "Schema as a module-level dict of frozen _Setting dataclasses carrying key/group/type_tag/default/validate/fallback_key/hint (Claude's Discretion per CONTEXT.md Open Question 1)"
  - "Role-id list validator kept lenient on ID width (positive-int digit strings) rather than a strict 17-20 snowflake regex — the Wave 0 contract (test_staff_role_fallback_to_gallery) sets [111, 222]; the validator's job is to guarantee list[int], not police ID length"
  - "FORUM_CHANNEL_ID/ENCODING_CHANNEL_ID use a snowflake-or-zero validator so their '0' unset sentinel round-trips as int (preserves current behavior)"
metrics:
  tasks: 3
  files_created: 1
  files_modified: 1
  duration: "~20m"
  completed: 2026-07-21
---

# Phase 01 Plan 02: Config Store (core/settings.py + core/db.py) Summary

The validated, sqlite-backed settings store: `core/settings.py` (19-key `_SCHEMA`, per-type
validators, `SettingRejected`, never-raising `get`, validating `set`, `all_for_ui`, idempotent
`seed_defaults`) resting on two additive `core/db.py` changes — the `settings` table via
`init_settings()` and WAL journal mode in `_get_conn()`. Behavior-preserving: every default is
byte-identical to config.py's current `.env` literal, so the store reads exactly today's values
until an owner edits one. Turns all 14 `tests/test_settings.py` tests green.

## What Was Built

**Task 1 — `core/db.py` (WAL + `init_settings`), commit `0c86c7f`:**
- `PRAGMA journal_mode=WAL` as the first statement after `row_factory` in `_get_conn()` (CONC-01,
  Option A from 01-RESEARCH.md Pattern 3 — persistent per-file, self-healing, non-transactional).
  One-line comment flags the local-filesystem requirement; no platform branching.
- New standalone `init_settings()` mirroring `init_gallery_state()` in shape: `CREATE TABLE IF NOT
  EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)`. NOT folded into `init_db()`; no
  seeding logic here.

**Task 2 — `core/settings.py` schema/validators/get/set, commit `866f78e`:**
- `SettingRejected(ValueError)` carrying `.reason` (mirrors `SlugRejected`).
- `_SCHEMA`: 19 frozen `_Setting` descriptors grouped by feature (gallery/reviews/reminders/
  jinxxy/meetings/forum), each with default sourced from `os.getenv` using config.py's exact
  literal, a validate callable, and an optional `fallback_key`.
- Validators: snowflake (17-20 digits), snowflake-or-zero (FORUM/ENCODING), role-id list
  (positive-int list or comma string), int-range [1,168] (poll/grace hours), IANA timezone (same
  `(ZoneInfoNotFoundError, KeyError, ValueError)` tuple as bot.py:130), free string (models —
  Pitfall 4, no enum), url (http/https), 2-letter lang.
- `get()`: SELECT + `json.loads`; broad `except Exception` → schema default (missing table/row/
  corrupt JSON, STORE-04); then empty-list + `fallback_key` → `get(fallback_key)` fresh each call
  (CONF-03/Pitfall 5). Never raises.
- `set()`: unknown key → `SettingRejected`; validator runs before any SQL; parameterized upsert
  (`ON CONFLICT DO UPDATE`) — key allowlist-checked and never interpolated (T-01-02-01/02).

**Task 3 — `all_for_ui` + `seed_defaults`, commit `8f3c572`:**
- `all_for_ui()`: safe tunables grouped by feature, each carrying key/type/current-value(via
  `get`)/hint. Allowlist guarantees no secret (BOT_TOKEN, GITHUB_PAT, JINXXY_API_KEY,
  SESSION_SECRET) or structural (DB_PATH) key can appear.
- `seed_defaults()`: startup-only; `db.init_settings()` then `INSERT OR IGNORE` each default —
  idempotent, never overwrites an owner's edit (Pitfall 3).

## Verification

- `pytest tests/test_settings.py -q` → **14 passed** (all STORE-01..05, CONF-03, CONC-01 tests).
- Full suite: **613 passed, 4 failed**. The 4 failures are the cog read-at-use gate tests
  (`test_gallery/reviews/reminders/jinxxy_*_reads_at_use`) failing with `AttributeError: module
  'config' has no attribute ...` — these are the intended-RED-until-01-03 tests: they
  `monkeypatch.delattr(config, KEY)` expecting the `config.__getattr__` → `settings.get` shim that
  01-03 (consolidation) adds. Confirmed not caused by this plan (all five files now COLLECT, which
  was 01-02's collection prerequisite; the store additions are purely additive).
- Task 1 verify (direct db exercise) prints `WAL+settings OK`.
- Grep gates: `journal_mode=WAL` (db.py:15) and `CREATE TABLE IF NOT EXISTS settings` (db.py:55)
  both match.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Role-id list validator relaxed from strict snowflake regex to positive-int**
- **Found during:** Task 2 (test_staff_role_fallback_to_gallery failed)
- **Issue:** The plan's `<action>` said role-list items must "match the snowflake regex" (17-20
  digits), but the Wave 0 contract test writes `settings.set("GALLERY_STAFF_ROLE_IDS", [111, 222])`
  — 3-digit test IDs the strict regex rejected, breaking the CONF-03 fallback test.
- **Fix:** `_validate_role_id_list` now accepts any positive-integer item (`str.isdigit()` → int),
  still rejecting non-numeric input. Guarantees `list[int]` without policing ID width; the Wave 0
  tests are the authoritative contract. Single-snowflake channel-ID validators keep the strict
  17-20 digit regex (their tests use real snowflakes).
- **Files modified:** core/settings.py
- **Commit:** `866f78e`

## Self-Check: PASSED

- FOUND: core/settings.py (356 lines; exports get/set/all_for_ui/seed_defaults/SettingRejected)
- FOUND: core/db.py (init_settings + WAL)
- FOUND commit 0c86c7f (Task 1: db.py WAL + init_settings)
- FOUND commit 866f78e (Task 2: settings.py schema/validators/get/set)
- FOUND commit 8f3c572 (Task 3: all_for_ui + seed_defaults)
- tests/test_settings.py: 14/14 green; all five Wave-1/2 test files collect
