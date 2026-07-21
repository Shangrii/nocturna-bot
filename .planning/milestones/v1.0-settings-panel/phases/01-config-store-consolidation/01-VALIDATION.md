---
phase: 1
slug: config-store-consolidation
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-19
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >= 8.0.0 (already pinned in `requirements.txt`) |
| **Config file** | none — tests run via bare `pytest` from repo root, relying on `tests/conftest.py`'s `sys.path` bootstrap |
| **Quick run command** | `pytest tests/test_settings.py -x` |
| **Full suite command** | `pytest` (repo root) |
| **Estimated runtime** | ~6 seconds (full suite; in-process against `tmp_path` sqlite) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_settings.py -x` (plus the touched cog's existing test file when a cog's config read path is affected)
- **After every plan wave:** Run `pytest` (full suite — no slow/integration markers to exclude)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~6 seconds

---

## Per-Task Verification Map

Task IDs are assigned by the planner (PLAN.md). Rows below map each phase requirement to its
automated verification; the planner attaches these to concrete task IDs.

| Requirement | Wave | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|------|----------|-----------|-------------------|-------------|--------|
| STORE-01 | 1 | `get`/`set`/`all_for_ui` round-trip through the `settings` table | unit | `pytest tests/test_settings.py -k round_trip -x` | ❌ W0 | ⬜ pending |
| STORE-02 | 1 | `settings` table created via `init_settings()` (CREATE TABLE IF NOT EXISTS idiom) | unit | `pytest tests/test_settings.py -k init_table -x` | ❌ W0 | ⬜ pending |
| STORE-03 | 1 | Per-type validation: accept valid, reject invalid ID/interval/TZ; raises `SettingRejected`, writes nothing | unit | `pytest tests/test_settings.py -k validation -x` | ❌ W0 | ⬜ pending |
| STORE-04 | 1 | `get` never raises — missing row, missing table, corrupt JSON all fall back to seed | unit | `pytest tests/test_settings.py -k fallback -x` | ❌ W0 | ⬜ pending |
| STORE-05 | 1 | Idempotent seed — running the seed twice is a no-op, matches `.env` values | unit | `pytest tests/test_settings.py -k seed_idempotent -x` | ❌ W0 | ⬜ pending |
| CONF-01 | 2 | A migrated cog re-reads a changed value at its next use (not cached from import) | unit | `pytest tests/test_reminders_cog.py tests/test_gallery_cog.py tests/test_jinxxy_cog.py -k staff_gate_or_channel -x` | ⚠️ W0 (extend existing) | ⬜ pending |
| CONF-02 | 2 | Secrets/structural values unaffected — existing `monkeypatch.setattr(config, ...)` regression tests still pass | unit | `pytest` (full suite regression) | ✅ existing | ⬜ pending |
| CONF-03 | 2 | Staff-role fallback-to-`GALLERY_STAFF_ROLE_IDS` holds when the specific list is empty in the DB | unit | `pytest tests/test_settings.py -k staff_role_fallback -x` | ❌ W0 | ⬜ pending |
| CONC-01 | 1 | WAL mode active after `_get_conn()`'s first call; two connections read+write without "database is locked" | integration | `pytest tests/test_settings.py -k wal -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_settings.py` — new file covering STORE-01/02/03/04/05, CONF-03 fallback composition, and CONC-01 WAL, mirroring `tests/test_editors_model.py`'s structure (plain `assert`/`pytest.raises`; isolate the DB via `monkeypatch.setattr(config, "DB_PATH", tmp_path/...)` matching `tests/test_counter_app.py:23`)
- [ ] Extend `tests/test_reminders_cog.py`, `tests/test_gallery_cog.py`, `tests/test_jinxxy_cog.py`, `tests/test_reviews_cog.py` — ONE new read-at-use test each (change the DB row/`settings.get` between two staff-gate calls, assert the second reflects it)
- [ ] No framework install needed — `pytest` already present.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Byte-identical behavior on a real deploy (seed runs, bot behaves identically until an edit) | STORE-05 | Full end-to-end deploy behavior on the `cinema` host is environmental | On a staging copy: start the bot with an existing `.env`, confirm the `settings` table seeds and no cog behavior changes; then edit one row and confirm the change is picked up at next use |

*All unit/integration behaviors above have automated verification; only the real-deploy no-op is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`tests/test_settings.py` + cog test extensions, created in 01-01)
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

> Strategy approved at planning; `wave_0_complete` flips to `true` once 01-01 executes and the Wave 0 tests exist (RED).

**Approval:** approved 2026-07-21
