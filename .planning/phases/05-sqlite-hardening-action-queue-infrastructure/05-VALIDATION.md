---
phase: 5
slug: sqlite-hardening-action-queue-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-22
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing suite; ~645 tests currently green) |
| **Config file** | none — repo uses pytest defaults with a `tests/` dir |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_action_queue.py tests/test_db_hardening.py -q` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |
| **Estimated runtime** | ~30–60 seconds (full suite) |

> **Interpreter note:** Use the conda Python (`C:\Users\Shangri\miniconda3\python.exe -m pytest`) — PowerShell's Python314 has no pytest. Test file names above are placeholders the planner finalizes.

---

## Sampling Rate

- **After every task commit:** Run the quick command
- **After every plan wave:** Run the full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> The planner assigns concrete task IDs; this map is filled as PLAN.md files are
> created. Every task touching the queue state machine or the retry/hardening path
> MUST carry an automated `<verify>` command.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | INFRA-01 / INFRA-02 | — | Manager-only enqueue; queue never double-dispatches | unit | `python -m pytest tests/test_action_queue.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave-0 RED scaffolds must exist before implementation (mirrors the Phase 1–4 test-first idiom):

- [ ] `tests/test_action_queue.py` — INFRA-01: `enqueue` / `claim_next` / `complete` / `fail` / `recover_stale_claims` / `retry` state-machine contract, keep-last-N purge scoped to `done`/`failed` only, at-least-once + stale-claim recovery, no double-dispatch.
- [ ] `tests/test_db_hardening.py` — INFRA-02: `busy_timeout` present on every `_get_conn()`; `_retry_on_locked` wrapper retries `OperationalError "database is locked"` then succeeds/raises.
- [ ] **Concurrent-load test (D-12 gate)** — INFRA-02: threaded bot-write-loop + panel-write-burst against a real `tmp_path` sqlite file asserts **zero unhandled "database is locked"**. Extends the existing `tests/test_settings.py::test_wal_concurrent_read_write` (CONC-01) precedent.

*Existing infrastructure (pytest suite) covers the harness; these files are the new RED scaffolds.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Inline pending→✓/✗ auto-refresh in the panel; "bot offline — will run on reconnect" state | INFRA-01 | Requires the running FastAPI app + a live/stopped bot process sharing the sqlite file; Alpine polling is a browser behavior | Enqueue the `noop` proof-action from the panel with the bot up (expect ✓ within ~1–2s without reload); stop the bot, enqueue again (expect "bot offline" state), restart the bot (expect it dispatches on reconnect). |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test_action_queue.py, test_db_hardening.py, concurrent-load test)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
