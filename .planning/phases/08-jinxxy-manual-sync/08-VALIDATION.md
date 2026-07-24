---
phase: 8
slug: jinxxy-manual-sync
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-24
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `08-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (no `pytest-asyncio` — async tests call `asyncio.run()` directly, per this repo's idiom in every `test_*_cog.py`) |
| **Config file** | none — `tests/conftest.py` only adds the repo root to `sys.path` |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_jinxxy_cog.py tests/test_action_queue_cog.py -v` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -v` |
| **Estimated runtime** | ~5 s quick / ~40 s full |

Use the conda python explicitly — PowerShell's `Python314` has no pytest installed.

---

## Sampling Rate

- **After every task commit:** Run the quick command above
- **After every plan wave:** Run the full suite — this phase touches shared infrastructure
  (`core/db.py`, `cogs/action_queue_worker.py`) that other modules' tests exercise
- **Before `/gsd:verify-work`:** Full suite green **plus** the overlap-guard test explicitly
  demonstrating exactly one `sync_store` and one `_announce` call under concurrent dispatch
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

> Task IDs are filled in by the planner; the requirement/behavior rows below are the contract
> each task must map onto.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | JINX-01 | — | N/A — test scaffolding | unit | `pytest tests/test_jinxxy_cog.py -v` | ✅ extend | ⬜ pending |
| TBD | TBD | 1 | JINX-01 (SC2, core) | T-8-overlap | Concurrent dispatch during an in-flight sync yields exactly ONE `sync_store` + ONE `_announce`, resolving `{"already": True}` | unit (async race via `asyncio.Event`) | `pytest tests/test_jinxxy_cog.py -k overlap -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | JINX-01 (SC2, D-03) | T-8-overlap | Poll tick during a manual sync skips silently — no sync, no announce, log line only | unit | `pytest tests/test_jinxxy_cog.py -k poll_skips -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | D-09 | — | Widened `jinxxy_sync_status` round-trips added/updated/removed counts | unit | `pytest tests/test_db_jinxxy_status.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | Pitfall 2 (migration) | — | Pre-existing 5-column `jinxxy_sync_status` + `init_jinxxy_sync_status()` → new columns queryable (`ALTER TABLE ADD COLUMN` idiom, not `CREATE TABLE IF NOT EXISTS`) | unit | `pytest tests/test_db_jinxxy_status.py -k migration -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 1 | D-10 | T-8-leak | `JinxxyAPIError` / `GitHubPublishError` / generic each map to their exact bilingual category — never raw `str(exc)` to the panel | unit | `pytest tests/test_jinxxy_cog.py -k error_category -v` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | JINX-01 (SC1) | T-8-authz | Manager POST enqueues `jinxxy_sync`; status endpoint reflects pending/running/done; non-Manager is rejected | integration | `pytest tests/test_app_jinxxy.py -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | D-04 | T-8-overlap | Second POST while one `jinxxy_sync` is `pending`/`claimed` returns the SAME action id — no second row | integration | `pytest tests/test_app_jinxxy.py::test_dedupe_at_enqueue -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | D-06 | — | `JinxxyCog.__init__` clears `running` on boot; app voids the mirror when `bot_heartbeat` is stale | unit + integration | `pytest tests/test_jinxxy_cog.py -k startup_clear` / `pytest tests/test_app_jinxxy.py -k stale_heartbeat` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | D-15 | — | No `jinxxy_sync_status` row + empty `store_snapshot` → app renders the never-synced empty copy | integration | `pytest tests/test_app_jinxxy.py::test_never_synced_empty_state -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | D-13/D-14 | — | `/jinxxy` renders `store_snapshot` rows with the locked column set — no image/description/editor column | integration | `pytest tests/test_app_jinxxy.py::test_product_table_columns -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | 2 | INFRA-02 (regression) | — | New write paths (dedupe query + widened mirror writes) don't reintroduce "database is locked" | integration | `pytest tests/test_action_queue_concurrency.py -v` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_app_jinxxy.py` — new file covering the `/jinxxy` route, POST enqueue, dedupe,
      authz rejection, and empty states. Follow `tests/test_app_gallery.py`'s session-signing
      fixture pattern (`_set_session` / `_manager_override`).
- [ ] Extend `tests/test_jinxxy_cog.py` — guarded-wrapper, overlap-race, reverse-collision,
      startup-clear, and error-category cases. The file's existing `cog` / `_wire` fixtures are
      directly reusable.
- [ ] DB round-trip coverage for the widened `jinxxy_sync_status` columns, **plus** a
      migration-safety case. During planning, run `grep -r jinxxy_sync_status tests/` to decide
      whether to extend an existing db test file or add `tests/test_db_jinxxy_status.py`.
- [ ] No framework or config install needed — pytest is already the project's only test runner.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Spinner / disabled-button transition on the live panel | JINX-01 (SC1) | Visual state timing against a real in-flight sync is not meaningfully assertable in pytest; the underlying status transitions ARE covered automatically by `test_app_jinxxy.py` | Log in as a Manager, open `/jinxxy`, click Sync. Confirm the button disables and a spinner shows immediately, then resolves to the last-sync line with counts and the triggering Manager's name. |
| Real Jinxxy API round-trip | JINX-01 | Requires live upstream credentials and mutates the real store snapshot | With real credentials configured, trigger one manual sync and confirm the product table matches the live store. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
