---
phase: 6
slug: reminders-crud
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-23
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (plain discovery via `tests/` + `tests/conftest.py`'s `sys.path` bootstrap — no `pytest.ini`/`pyproject.toml` config section) |
| **Config file** | none — collection is directory-based; `tests/conftest.py` bootstraps `sys.path` |
| **Interpreter** | `C:\Users\Shangri\miniconda3\python.exe` (the conda Python — NOT PowerShell's `Python314`, which has no pytest; per MEMORY.md) |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminders_cog.py tests/test_reminder_schedule.py -q` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |
| **Estimated runtime** | quick subset ~1–2 s; full suite ~27 s (710 passing at phase start, growing with the new phase-6 test files) |

---

## Sampling Rate

- **After every task commit:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminders_cog.py tests/test_reminder_schedule.py -q` (fast — pure-function + mocked-DB tests, no real threading). Add `tests/test_db_reminders_crud.py` / `tests/test_app_reminders.py` once their Wave 0 files exist.
- **After every plan wave:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` (full suite — catches cross-module regressions in the shared `core/db.py` `_get_conn`).
- **Before `/gsd:verify-work`:** Full suite must be green (Plan 06 Task 1 gate).
- **Max feedback latency:** ~30 s (full-suite worst case; the per-commit subset returns in ~1–2 s).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | REM-04 | — | N/A (RED scaffold) | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminder_schedule.py -q` (asserts RED) | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | REM-01 / REM-04 | T-06-01 | Pure module imports without pulling in `discord` (app-process-safe) | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminder_schedule.py tests/test_reminders_cog.py -q` | ❌ W0 (schedule) / ✅ (cog) | ⬜ pending |
| 06-02-01 | 02 | 1 | REM-02 / REM-03 | — | N/A (RED scaffold) | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_db_reminders_crud.py -q` (asserts RED) | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 1 | REM-02 / REM-03 | T-06-03 / T-06-04 / T-06-05 / T-06-06 | Optimistic `version` guard rejects stale writes; `version` server-incremented only; `paused=0` filter; column allowlist | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_db_reminders_crud.py tests/test_reminders_cog.py -q` | ❌ W0 (crud) / ✅ (cog) | ⬜ pending |
| 06-02-02b | 02 | 1 | REM-03 (D-17 LOCKED) | T-06-03 | Scheduler write-back never clobbers a concurrent panel edit (deterministic, no threads) | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_db_reminders_crud.py -k scheduler_writeback_never_clobbers_concurrent_panel_edit -q` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 2 | REM-01 / REM-04 | T-06-10 | biweekly accepts a PAST anchor (no one-off rejection); compute_next dispatches biweekly | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminders_cog.py -k biweekly -q` | ✅ | ⬜ pending |
| 06-03-02 | 03 | 2 | REM-02 / REM-03 | T-06-07 / T-06-08 / T-06-09 | `_process_due` threads `expected_version`, logs-and-continues on lost race, keeps per-row try/except, skips paused | unit | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_reminders_cog.py -q` | ✅ | ⬜ pending |
| 06-04-01 | 04 | 2 | REM-01 / REM-02 / REM-03 | — | N/A (RED scaffold) | integration | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_reminders.py -q` (asserts RED) | ❌ W0 | ⬜ pending |
| 06-04-02 | 04 | 2 | REM-01 / REM-02 / REM-03 | T-06-11 / T-06-12 / T-06-13 / T-06-14 / T-06-16 | Every route `Depends(require_manager)`; server recomputes `next_fire_utc`; stale edit → 409 (not 422); resume recomputes forward | integration | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_reminders.py -q` | ❌ W0 | ⬜ pending |
| 06-05-01 | 05 | 3 | REM-01 / REM-02 | T-06-17 / T-06-18 | Jinja2 auto-escape + `x-text` (no `x-html`); preview fetches server `/reminders/preview`, no client-side schedule math | integration | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_reminders.py -q` | ❌ W0 | ⬜ pending |
| 06-05-02 | 05 | 3 | REM-01 / REM-02 | T-06-19 | Resolved names in happy path; raw ID only on hover for cache-miss; no new CSS token | integration | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_reminders.py -q` (+ token grep) | ❌ W0 | ⬜ pending |
| 06-06-01 | 06 | 4 | REM-01 / REM-02 / REM-03 | T-06-21 | Full suite green incl. the LOCKED D-17 gate before human verify | integration | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` | ✅ (all files exist post-W0) | ⬜ pending |
| 06-06-02 | 06 | 4 | REM-04 | — | N/A (docs bookkeeping) | manual/grep | `grep -c "REM-04" .planning/REQUIREMENTS.md` >= 1 | ✅ | ⬜ pending |
| 06-06-03 | 06 | 4 | REM-01 / REM-02 / REM-03 | T-06-20 / T-06-21 | Live Manager CRUD + biweekly parity + non-Manager 403 + imminent caveats | manual | human-verify checkpoint (see Manual-Only Verifications) | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

New test files the plans create before their implementation tasks can go GREEN (transcribed from RESEARCH.md "Wave 0 Gaps"):

- [ ] `tests/test_reminder_schedule.py` — biweekly anchor math (past-anchor validity, DST) + `is_imminent` thresholds for the extracted `core/reminder_schedule.py` (Plan 01 Task 1 creates it RED). Covers REM-04.
- [ ] `tests/test_db_reminders_crud.py` — `paused`/`version` migration, version-guard behavior, pause filter, and the LOCKED D-17 `test_scheduler_writeback_never_clobbers_concurrent_panel_edit` proof at the `core/db.py` layer (Plan 02 Task 1 creates it RED). Covers REM-02/REM-03.
- [ ] `tests/test_app_reminders.py` — `require_manager`-gated FastAPI CRUD/pause/resume/preview routes with 409-vs-422 distinction (Plan 04 Task 1 creates it RED). Covers REM-01/REM-02/REM-03.

Shared fixtures: reuse existing idioms — the tmp-DB isolation from `tests/test_action_queue_concurrency.py` (`monkeypatch.setattr(config, "DB_PATH", ...)`), the `client` fixture + `require_manager` override from `tests/test_app_settings.py` / `tests/test_app_actions.py`, and the `_row`/`_patch_db` fixtures already in `tests/test_reminders_cog.py`. No new `conftest.py` and no framework install needed — pytest is already the project runner.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full Manager CRUD walkthrough (create/edit/delete/pause/resume) renders and behaves correctly in a live browser | REM-01 / REM-02 | Visual fidelity, toast feel, and live-preview interactivity cannot be fully asserted by route tests | Plan 06 checkpoint steps 1–2, 5–6: sign in as Manager, exercise the table + modal + confirm dialog, confirm badges/toasts/relative-time render correctly |
| Biweekly visual parity (panel summary "Cada 2 semanas · <día> HH:MM" + past-anchor accepted + FUTURE-parity preview) matches Discord `/recordatorio` | REM-04 | Cross-surface (browser + Discord client) visual parity is experiential, not route-assertable | Plan 06 checkpoint steps 3 & 7: create a biweekly reminder with a PAST anchor in the panel, confirm summary + preview, then confirm `biweekly` is a `/recordatorio crear` choice in Discord |
| Imminent-fire caveat timing (D-15 delete warning / D-16 edit caveat appear only within ~90 s of a fire) | REM-03 | Wall-clock-relative UI behavior at a ~90 s boundary is impractical to assert deterministically in an automated browser test | Plan 06 checkpoint steps 4 & 6: edit/delete a reminder within ~90 s of firing and confirm the caveat line appears; confirm it is absent otherwise |
| Non-Manager gate holds for a real forbidden session | REM-01 | Belt-and-suspenders over the automated 403 gate test, in a real signed-in session | Plan 06 checkpoint step 8: sign in as a non-Manager and confirm `/reminders` returns 403 with no data |

*The version-guard integrity itself (REM-03) is NOT manual — the LOCKED D-17 `test_scheduler_writeback_never_clobbers_concurrent_panel_edit` proves it deterministically; the checkpoint only adds an experiential layer.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (the three RED-scaffold tasks depend on their own Wave 0 files; the checkpoint's caveat-timing behaviors are the only manual-only items, all with automated proxies)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every implementation task runs pytest; the sole manual checkpoint is gated by an automated full-suite run in Plan 06 Task 1)
- [x] Wave 0 covers all MISSING references (`tests/test_reminder_schedule.py`, `tests/test_db_reminders_crud.py`, `tests/test_app_reminders.py`)
- [x] No watch-mode flags (all commands are one-shot `-q`)
- [x] Feedback latency < 30 s (full suite ~27 s; per-commit subset ~1–2 s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-23
