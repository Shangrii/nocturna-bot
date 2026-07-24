---
phase: 8
slug: jinxxy-manual-sync
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-24
updated: 2026-07-24
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `08-RESEARCH.md` § Validation Architecture. Task IDs filled in by the planner
> against `08-01-PLAN.md` … `08-08-PLAN.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest. Two idioms coexist and must be matched per file: `tests/test_*_cog.py` (except `test_action_queue_cog.py`) drive async code with `asyncio.run()` directly; `tests/test_action_queue_cog.py` uses `@pytest.mark.anyio` with a local `anyio_backend` fixture. `pytest-asyncio` is NOT installed and must never be introduced. |
| **Config file** | none — `tests/conftest.py` only adds the repo root to `sys.path` |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_jinxxy_cog.py tests/test_action_queue_cog.py -v` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -v` |
| **Estimated runtime** | ~5 s quick / ~40 s full |

Use the conda python explicitly — PowerShell's `Python314` has no pytest installed.

---

## Sampling Rate

- **After every task commit:** Run the quick command above
- **After every plan wave:** Run the full suite — this phase touches shared infrastructure
  (`core/db.py`, `core/action_queue.py`, `cogs/action_queue_worker.py`, `app/main.py`,
  `app/deps.py`) that other modules' tests exercise
- **Before `/gsd:verify-work`:** Full suite green **plus** the overlap-guard test explicitly
  demonstrating exactly one `sync_store` and one `_announce` call under concurrent dispatch
  (`08-08-PLAN.md` Task 1 runs this gate)
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-01-T3 | 08-01 | 1 | Pitfall 2 (migration) | T-08-03 | Pre-existing 5-column `jinxxy_sync_status` + `init_jinxxy_sync_status()` → new columns queryable (`ALTER TABLE ADD COLUMN` idiom, not `CREATE TABLE IF NOT EXISTS`) | unit | `pytest tests/test_db_jinxxy_status.py -k migration -x` | ❌ W1 (new) | ⬜ pending |
| 08-01-T3 | 08-01 | 1 | D-09 | — | Widened `jinxxy_sync_status` round-trips added/updated/removed counts; a last-run write never clobbers the running mirror | unit | `pytest tests/test_db_jinxxy_status.py -x` | ❌ W1 (new) | ⬜ pending |
| 08-01-T3 | 08-01 | 1 | D-04 (queue layer) | T-08-05 | `enqueue_deduped` returns the existing pending/claimed id and inserts no second row | unit | `pytest tests/test_action_queue_dedupe.py -x` | ❌ W1 (new) | ⬜ pending |
| 08-02-T2 | 08-02 | 1 | D-07/D-12 (name source) | T-08-04 | Session `username` comes only from the OAuth-verified `_fetch_user(token)`; `roles["username"]` is None-safe for legacy sessions | unit | `pytest tests/test_app_auth.py -k username -v` | ✅ extend | ⬜ pending |
| 08-03-T3 | 08-03 | 2 | JINX-01 (SC2, core) | T-08-11, T-08-13 | Concurrent dispatch during an in-flight sync yields exactly ONE `sync_store` + ONE `_announce`, resolving `{"already": True}` as a success | unit (async race via `asyncio.Event`) | `pytest tests/test_jinxxy_cog.py -k overlap -v` | ✅ extend | ⬜ pending |
| 08-03-T3 | 08-03 | 2 | JINX-01 (SC2, D-03) | T-08-11 | Poll tick during a manual sync skips silently — no sync, no announce, log line only | unit | `pytest tests/test_jinxxy_cog.py -k poll_skips -v` | ✅ extend | ⬜ pending |
| 08-03-T3 | 08-03 | 2 | Pitfall 1 (double-announce) | T-08-12 | `_announce` is awaited exactly once per sync; `cogs/jinxxy.py` has exactly one non-comment `self._announce(` call site | unit + grep | `pytest tests/test_jinxxy_cog.py -k announces_exactly_once -v` | ✅ extend | ⬜ pending |
| 08-03-T3 | 08-03 | 2 | D-06 (bot side) | T-08-15 | `JinxxyCog.__init__` clears `running` on boot; the mirror is cleared in `finally` even when the sync raises | unit | `pytest tests/test_jinxxy_cog.py -k startup_clear -v` | ✅ extend | ⬜ pending |
| 08-04-T3 | 08-04 | 3 | D-10 | T-08-02 | `JinxxyAPIError` / `GitHubPublishError` / generic each map to their exact bilingual category — never raw `str(exc)` | unit | `pytest tests/test_jinxxy_cog.py -k error_category -v` | ✅ extend | ⬜ pending |
| 08-04-T3 | 08-04 | 3 | D-09 / D-12 | T-08-17 | Every run persists its counts and writes an activity line naming the trigger source and actor | unit | `pytest tests/test_jinxxy_cog.py -k "activity_line or counts" -v` | ✅ extend | ⬜ pending |
| 08-05-T2 | 08-05 | 4 | JINX-01 (dispatch), D-01, D-10 | T-08-02, T-08-19 | The `jinxxy_sync` kind dispatches to `_run_sync_guarded`, stores a small count dict, records a collision as `done`/`already`, and records a failure as a fixed category with no upstream URL or status code | unit (anyio) | `pytest tests/test_action_queue_cog.py -k jinxxy -v` | ✅ extend | ⬜ pending |
| 08-06-T3 | 08-06 | 2 | JINX-01 (SC1) | T-08-01 | Manager POST enqueues `jinxxy_sync`; the status endpoint reflects never-synced / running / last-run counts; every `/jinxxy` route rejects a non-Manager | integration | `pytest tests/test_app_jinxxy.py -x` | ❌ W2 (new) | ⬜ pending |
| 08-06-T3 | 08-06 | 2 | D-04 | T-08-05, T-08-06 | Second POST while one `jinxxy_sync` is `pending`/`claimed` returns the SAME action id — no second row; `jinxxy_sync` is absent from `_ALLOWED_KINDS` so the generic endpoint cannot bypass the dedupe | integration | `pytest tests/test_app_jinxxy.py::test_dedupe_at_enqueue -x` | ❌ W2 (new) | ⬜ pending |
| 08-06-T3 | 08-06 | 2 | D-06 (app side) | T-08-15 | The app voids the mirror when `bot_heartbeat` is stale; `never_synced` is detected via `last_run_utc is None`, not row presence | integration | `pytest tests/test_app_jinxxy.py -k stale_heartbeat -v` | ❌ W2 (new) | ⬜ pending |
| 08-07-T3 | 08-07 | 3 | D-15 | — | No `jinxxy_sync_status` row + empty `store_snapshot` → the page renders the never-synced empty copy, not a dash | integration | `pytest tests/test_app_jinxxy.py::test_never_synced_empty_state -x` | ❌ W3 (extend) | ⬜ pending |
| 08-07-T3 | 08-07 | 3 | D-13/D-14/D-16 | T-08-26 | `/jinxxy` renders `store_snapshot` rows with the locked five-column set (no image/description/editor), name-ascending, `rel="noopener"` on every external link, and no confirm dialog | integration | `pytest tests/test_app_jinxxy.py::test_product_table_columns -x` | ❌ W3 (extend) | ⬜ pending |
| 08-08-T1 | 08-08 | 5 | INFRA-02 (regression) | T-08-08 | New write paths (dedupe query + widened mirror writes) don't reintroduce "database is locked" | integration | `pytest tests/test_action_queue_concurrency.py -v` | ✅ exists | ⬜ pending |
| 08-08-T2 | 08-08 | 5 | JINX-01 (SC1, manual) | T-08-12 | Live disabled/spinner/elapsed/attribution transition and a real Jinxxy round-trip | manual checkpoint | see § Manual-Only Verifications | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 scaffolding is not a separate wave in this phase — each plan creates or extends the test
file its own tasks depend on, in the same wave, so no plan can land unverified.

- [ ] `tests/test_db_jinxxy_status.py` — NEW, created by `08-01-T3`. Migration safety + widened
      round-trip + the D-15 null-`last_run_utc` case. Follows
      `tests/test_db_reminders_crud.py::test_init_reminders_migrates_paused_version_onto_existing_table`.
- [ ] `tests/test_action_queue_dedupe.py` — NEW, created by `08-01-T3`. D-04 at the queue layer.
- [ ] `tests/test_app_auth.py` — EXTENDED by `08-02-T2`. Session `username` persistence and the
      None-safe `roles["username"]`.
- [ ] `tests/test_jinxxy_cog.py` — EXTENDED by `08-03-T3` (guard, overlap race, reverse
      collision, announce-once, startup clear) and `08-04-T3` (counts, attribution, error
      categories). The file's existing `cog` / `_wire` fixtures are directly reusable; the `cog`
      fixture must be updated because `__init__` now also calls `init_jinxxy_sync_status()` and
      `clear_jinxxy_sync_running()`.
- [ ] `tests/test_action_queue_cog.py` — EXTENDED by `08-05-T2`. Uses the file's own
      `@pytest.mark.anyio` idiom, NOT `asyncio.run`.
- [ ] `tests/test_app_jinxxy.py` — NEW, created by `08-06-T3` (routes, authz, dedupe, status
      shape, stale heartbeat) and extended by `08-07-T3` (rendered empty states, table columns,
      sort order, no-confirm). Follows `tests/test_app_gallery.py`'s `_configure_app` /
      `_manager_override` / `client` fixture pattern, with a `"username"` key added to the
      override.
- [ ] No framework or config install needed — pytest is already the project's only test runner.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Spinner / disabled-button transition on the live panel | JINX-01 (SC1) | Visual state timing against a real in-flight sync is not meaningfully assertable in pytest; the underlying status transitions ARE covered automatically by `test_app_jinxxy.py` | `08-08-PLAN.md` Task 2, steps A and B |
| Real Jinxxy API round-trip | JINX-01 | Requires live upstream credentials and mutates the real store snapshot | `08-08-PLAN.md` Task 2, steps C and D |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 45s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-confirmed 2026-07-24
