---
phase: 9
slug: meetings-browser-re-publish
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-29
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (no `pytest.ini`/`[tool.pytest]` section; `tests/conftest.py` only adds repo root to `sys.path`) |
| **Config file** | none |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_db_meetings.py tests/test_action_queue_dedupe.py tests/test_meeting_cog.py tests/test_action_queue_cog.py tests/test_app_meetings.py -x` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/ -q` |
| **Estimated runtime** | ~30–60 seconds full suite |

> Interpreter note (MEMORY): use the conda python (`C:\Users\Shangri\miniconda3\python.exe -m pytest`), NOT PowerShell's `Python314` (no pytest installed there).

---

## Sampling Rate

- **After every task commit:** Run the targeted new/changed test file(s) for that task.
- **After every plan wave:** Run the full suite command.
- **Before `/gsd:verify-work`:** Full suite must be green.
- **Max feedback latency:** ~60 seconds.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | MEET-01, MEET-03 | T-09-01 | Per-entity dedupe; different meeting_ids never collapse | unit | `pytest tests/test_db_meetings.py tests/test_action_queue_dedupe.py -x` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | MEET-03 | T-09-02 | `kind` literal preserved; dedupe keyed on dedupe_key column | unit | `pytest tests/test_action_queue_dedupe.py -x` | ✅ (extended) | ⬜ pending |
| 09-01-03 | 01 | 1 | MEET-01 | — | Full record round-trips + survives fresh connection | unit | `pytest tests/test_db_meetings.py -x` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | MEET-02 | T-09-03 | No `\| safe`; autoescape neutralizes stored XSS | source-grep | list-page grep gate | ❌ W0 | ⬜ pending |
| 09-02-02 | 02 | 1 | MEET-02, MEET-03 | T-09-03 | No `\| safe`; D-14 hides button when no forum post | source-grep | detail-page grep gate | ❌ W0 | ⬜ pending |
| 09-03-01 | 03 | 2 | MEET-01, MEET-03 | T-09-02 | Republish reads ids from DB, not payload | unit (mocked discord) | `pytest tests/test_meeting_cog.py tests/test_action_queue_cog.py -x` | ❌ W0 | ⬜ pending |
| 09-03-02 | 03 | 2 | MEET-01 | — | Persist both paths; publish never aborts on DB error | unit | `pytest tests/test_meeting_cog.py -k "publish or attendee" -x` | ❌ W0 | ⬜ pending |
| 09-03-03 | 03 | 2 | MEET-03 | T-09-02, T-09-05 | Archived unarchive→edit→restore; ids from DB | unit | `pytest tests/test_meeting_cog.py tests/test_action_queue_cog.py -x` | ❌ W0 | ⬜ pending |
| 09-04-01 | 04 | 2 | MEET-02, MEET-03 | T-09-01 | Non-Manager 403; per-meeting dedupe_key | integration (TestClient) | `pytest tests/test_app_meetings.py -x` | ❌ W0 | ⬜ pending |
| 09-04-02 | 04 | 2 | MEET-02, MEET-03 | T-09-01, T-09-04 | require_manager on all routes; no `import discord` | integration | `pytest tests/test_app_meetings.py -k "list or detail or gate or 404" -x` | ❌ W0 | ⬜ pending |
| 09-04-03 | 04 | 2 | MEET-02 | — | Stub deleted; app imports clean; single /meetings route | integration | `pytest tests/test_app_meetings.py -x` + `python -c "import app.main"` | ❌ W0 | ⬜ pending |
| 09-05-01 | 05 | 3 | MEET-01/02/03 | — | Full suite green before human verify | suite | `pytest tests/ -q` | n/a | ⬜ pending |
| 09-05-02 | 05 | 3 | MEET-01/02/03 | T-09-05, T-09-08 | Live no-duplicate + archived + MANAGE_THREADS | manual | human-verify | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_db_meetings.py` — NEW, meetings CRUD + cross-connection persistence (MEET-01). No prior precedent for meeting-table CRUD.
- [ ] `tests/test_meeting_cog.py` — NEW, `_publish` both-path persistence + attendee union + archived-thread `_republish` (MEET-01/MEET-03). `cogs/meeting.py` has ZERO tests today — genuine pre-existing coverage gap.
- [ ] `tests/test_app_meetings.py` — NEW, list/detail/404/gate/enqueue (MEET-02/MEET-03). Follows `test_app_jinxxy.py` fixture shape.
- [ ] `tests/test_action_queue_dedupe.py` — EXTEND with a per-entity `dedupe_key` case (same id collapses, different ids do not) + jinxxy no-dedupe_key regression. Existing cases only exercise kind-only dedupe.
- [ ] `tests/test_action_queue_cog.py` — EXTEND `_DISPATCH_CASES` with a `meeting_republish` case.
- Framework install: none — pytest already the project runner.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Re-publish edits the existing forum starter post, no duplicate, incl. double-click | MEET-03 | Requires a live Discord forum round-trip (no mock proves the real PATCH edits in place) | Plan 05 Task 2 steps 7–9 |
| Archived-thread edit (unarchive→edit→restore) against real auto-archived thread | MEET-03 | Real archived state + MANAGE_THREADS grant only exist on the live server | Plan 05 Task 2 step 10 |
| MANAGE_THREADS present on the bot's role | MEET-03 | Discord server permission config, out-of-band | Plan 05 Task 2 step 1 |
| Meetings survive a real bot process restart | MEET-01 | Restart durability is only observable against the live process | Plan 05 Task 2 steps 2–4 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (checkpoint tasks are manual by design)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-29
