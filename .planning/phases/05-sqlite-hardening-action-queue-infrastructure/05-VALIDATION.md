---
phase: 5
slug: sqlite-hardening-action-queue-infrastructure
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-22
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Finalized against the five committed PLAN.md files (05-01 … 05-05).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing suite; ~685 tests currently green) |
| **Config file** | none — repo uses pytest defaults with a `tests/` dir |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue.py tests/test_db_hardening.py -q` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |
| **Estimated runtime** | ~30–60 seconds (full suite; the concurrency gate adds several seconds by design) |

> **Interpreter note:** Use the conda Python (`C:\Users\Shangri\miniconda3\python.exe -m pytest`) — PowerShell's Python314 has no pytest.

---

## Sampling Rate

- **After every task commit:** Run the quick command
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green, with `tests/test_action_queue_concurrency.py` treated as the literal D-12 go/no-go gate
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Final task IDs, one row per task across the five plans. RED tasks expect a NON-ZERO exit
> (code-under-test absent); GREEN tasks expect exit 0. The Wave-3 checkpoint is human-verified.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | INFRA-01 / INFRA-02 | T-05-01/02/03 | RED scaffolds lock the state-machine + busy_timeout contract | unit (RED) | `pytest tests/test_action_queue.py tests/test_db_hardening.py -q` (expect non-zero) | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | INFRA-02 | T-05-02 | busy_timeout on every connection; retry wrapper does NOT leak into core/db.py (D-11) | unit | `pytest tests/test_db_hardening.py tests/test_settings.py -q` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | INFRA-01 / INFRA-02 | T-05-01/02/03 | queue never double-dispatches; purge never drops pending; _retry_on_locked retries/re-raises | unit | `pytest tests/test_action_queue.py tests/test_db_hardening.py -q` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | INFRA-01 | T-05-04 | RED cog dispatch tests (unknown kind never escapes the tick) | unit (RED) | `pytest tests/test_action_queue_cog.py -q` (expect non-zero) | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 2 | INFRA-01 | T-05-04/05/06 | serialized dispatch; unknown kind fails the row cleanly; to_thread-wrapped | unit | `pytest tests/test_action_queue_cog.py -q` | ❌ W0 | ⬜ pending |
| 05-02-03 | 02 | 2 | INFRA-01 | T-05-04 | cog registered in the always-loaded block (not optional-deps) | smoke | `python -c "import sys; sys.exit(0 if 'cogs.action_queue_worker' in open('bot.py').read() else 1)"` | ✅ | ⬜ pending |
| 05-03-01 | 03 | 2 | INFRA-01 | T-05-07/08 | RED route tests (manager-gate, kind 422, retry 409, bot_offline) | integration (RED) | `pytest tests/test_app_actions.py -q` (expect non-zero) | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 2 | INFRA-01 | T-05-07/08/09/11 | manager-gated routes; kind allowlist before enqueue; bot_online field; no Discord cred in app | integration | `pytest tests/test_app_actions.py -q` | ❌ W0 | ⬜ pending |
| 05-03-03 | 03 | 2 | INFRA-01 | T-05-07 | Overview proof card renders inline status/Retry/offline (presentational; routes still gated) | integration | `pytest tests/test_app_dashboard.py -q` | ✅ | ⬜ pending |
| 05-04-01 | 04 | 2 | INFRA-02 | T-05-12 | zero unhandled "database is locked" + zero rows left pending under real contention (D-12 gate) | integration/load | `pytest tests/test_action_queue_concurrency.py -v` | ❌ W0 | ⬜ pending |
| 05-05-01 | 05 | 3 | INFRA-01 | T-05-13 | live inline auto-refresh + Retry + bot-offline/reconnect durability | human-verify | manual (see Manual-Only Verifications) | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave-0 RED scaffolds are written as the first (RED) task of their owning plan before that plan's
implementation tasks (mirrors the Phase 1–4 test-first idiom):

- [ ] `tests/test_action_queue.py` (05-01-01) — INFRA-01: `enqueue` / `claim_next` / `complete` / `fail` / `recover_stale_claims` / `retry` state-machine contract, keep-last-N purge scoped to `done`/`failed` only (Pitfall 1), stale-claim recovery + no mid-flight double-claim (Pitfalls 1/2), retry-only-from-failed (Pitfall 3), AND the `_retry_on_locked` retry/re-raise unit test (D-11, colocated with the module that defines it).
- [ ] `tests/test_db_hardening.py` (05-01-01) — INFRA-02: `busy_timeout` PRAGMA presence ONLY (imports `core.db` only, never `core.action_queue` — satisfiable by 05-01-02 which touches core/db.py alone).
- [ ] `tests/test_action_queue_cog.py` (05-02-01) — INFRA-01: `ActionQueueCog` dispatch via the extracted `_run_once` (Pitfall 5): complete, auto-retry→failed, unknown-kind-never-escapes.
- [ ] `tests/test_app_actions.py` (05-03-01) — INFRA-01: manager-gate 403, kind 422, status shape + `bot_offline` (D-07), retry 409/200.
- [ ] `tests/test_action_queue_concurrency.py` (05-04-01, D-12 gate) — INFRA-02: threaded bot-write-loop + 16×25 panel-write-burst against a real `tmp_path` sqlite file asserts **zero unhandled "database is locked"** and zero rows left pending. Extends the existing `tests/test_settings.py::test_wal_concurrent_read_write` (CONC-01) precedent from reader/writer to real writer/writer contention.

*Existing infrastructure (pytest suite) covers the harness; these files are the new RED scaffolds. Framework install: none — pytest and all dependencies are already present.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Inline pending→✓/✗ auto-refresh in the panel; "bot offline — will run on reconnect" state | INFRA-01 | Requires the running FastAPI app + a live/stopped bot process sharing the sqlite file; Alpine polling is a browser behavior | (Plan 05-05 checkpoint) Enqueue the `noop` proof-action from the Overview card with the bot up (expect ✓ within ~1–2s without reload); force a failure and Retry (expect ✗ + reason then ✓); stop the bot and enqueue (expect "bot offline" state), restart the bot (expect it dispatches on reconnect — no lost click). |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (Wave-3 checkpoint is human-verify by design)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test_action_queue.py, test_db_hardening.py, test_action_queue_cog.py, test_app_actions.py, test_action_queue_concurrency.py)
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-22 (strategy finalized against the five committed plans)
