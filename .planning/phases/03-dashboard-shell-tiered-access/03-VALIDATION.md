---
phase: 3
slug: dashboard-shell-tiered-access
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-21
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Populated from 03-RESEARCH.md "Validation Architecture" and the 8 phase plans.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (no `pytest.ini`/`pyproject.toml`; bare `tests/conftest.py` adds repo root to `sys.path`) |
| **Config file** | none — Wave 0 (Plan 03-01) adds `tests/test_app_dashboard.py`; `tests/test_settings.py` extended |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_dashboard.py tests/test_app_auth.py tests/test_settings.py -x` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest` |
| **Estimated runtime** | ~30 seconds (quick) / ~60-90 seconds (full) |

> Use the conda Python (`C:\Users\Shangri\miniconda3\python.exe`) — PowerShell's default Python has no pytest installed (project memory).

---

## Sampling Rate

- **After every task commit:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_dashboard.py tests/test_app_auth.py tests/test_settings.py tests/test_jinxxy_cog.py tests/test_gallery_cog.py tests/test_reviews_cog.py -x`
- **After every plan wave:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | SHELL/ACCESS (all) | T-03-01 | Six behavioral tests exist + collect (RED) | scaffold | `... -m pytest tests/test_app_dashboard.py --collect-only` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | ACCESS-04 | T-03-01 | manager_roles/editor_roles schema cases exist (RED) | scaffold | `... -m pytest tests/test_settings.py --collect-only` | ❌ W0 | ⬜ pending |
| 3-02-01 | 02 | 1 | ACCESS-04 | T-03-03/04/05/06 | Mapping keys seed byte-identical; no fallback; invalid IDs rejected | unit | `... -m pytest tests/test_settings.py -x` | ❌ W0 | ⬜ pending |
| 3-02-02 | 02 | 1 | ACCESS-04 | T-03-03 | Access group legend renders; role_list input reused | source | `grep -c "access:" app/templates/settings.html` | ✅ | ⬜ pending |
| 3-03-01 | 03 | 1 | SHELL-02 | T-03-07/08 | 3 tables init/round-trip; activity_log bounded | unit | `... -c "from core import db; db.init_heartbeat(); db.init_activity_log(); ..."` | ✅ | ⬜ pending |
| 3-03-02 | 03 | 1 | SHELL-02 | T-03-08 | Heartbeat cog parses + loads; writes latency/uptime/cogs | source | `... -c "import ast; ast.parse(open('cogs/heartbeat.py').read())"` | ✅ | ⬜ pending |
| 3-04-01 | 04 | 2 | SHELL-02 | T-03-10 | Sync records status + `jinxxy_sync` activity row (D-11); failure isolated | unit | `... -m pytest tests/test_jinxxy_cog.py -x` | ✅ | ⬜ pending |
| 3-04-02 | 04 | 2 | SHELL-02 | T-03-10 | gallery/reviews/meeting append activity rows; action never aborts | unit | `... -m pytest tests/test_gallery_cog.py tests/test_reviews_cog.py -x` | ✅ | ⬜ pending |
| 3-05-01 | 05 | 2 | ACCESS-01/03 | T-03-14/15/16 | Callback admits any tier; bot-token-only; session stores no tier; per-tier redirect | unit/integration | `... -m pytest tests/test_app_auth.py -x` | ✅ | ⬜ pending |
| 3-05-02 | 05 | 2 | ACCESS-01/02/03/04 | T-03-12/13/17 | require_manager gates owner+Manager; owner independent of mapping; one REST read | unit | `... -c "from app import deps; assert hasattr(deps,'require_manager') ..."` | ✅ | ⬜ pending |
| 3-06-01 | 06 | 1 | SHELL-01 | T-03-18 | Sidebar lock state server-computed; no toggles; accent set present | source | `grep -c "accent-gallery..." app/static/dashboard.css` | ❌ new | ⬜ pending |
| 3-06-02 | 06 | 1 | SHELL-01/02 | T-03-19/20 | Overview polls /api/overview/status; forbidden.html tier copy; no quick-actions | source | `grep -l "/api/overview/status" overview.html && grep -l required_tier forbidden.html` | ❌ new | ⬜ pending |
| 3-07-01 | 07 | 3 | ACCESS-02 | T-03-24/25 | Lifespan defensive init; TierForbidden + /admin/settings 403 -> forbidden.html in-shell | integration | `... -c "import app.main"` + settings-403 body assertion | ❌ W0 | ⬜ pending |
| 3-07-02 | 07 | 3 | SHELL-01, ACCESS-01/02/03 | T-03-21/22 | 6 routes require_manager; owner 200 all, Manager 6+Settings403, editor locked | integration | `... -m pytest tests/test_app_dashboard.py::test_owner_full_access tests/test_app_dashboard.py::test_manager_operational_access_settings_403 tests/test_app_dashboard.py::test_editor_only_locked_out_of_dashboard tests/test_app_dashboard.py::test_sidebar_renders_seven_sections -x` | ❌ W0 | ⬜ pending |
| 3-07-03 | 07 | 3 | SHELL-02 | T-03-23/24 | /api/overview/status require_manager; graceful on empty tables | integration | `... -m pytest tests/test_app_dashboard.py::test_overview_shows_status_tiles -x` | ❌ W0 | ⬜ pending |
| 3-08-01 | 08 | 4 | SHELL-01/02, ACCESS-01/02/03/04 | T-03-26 | Human confirms tier matrix + variant-A fidelity live | manual | see Manual-Only Verifications | n/a | ⬜ pending |

*Command prefix `...` = `C:\Users\Shangri\miniconda3\python.exe`. Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_app_dashboard.py` — new file: SHELL-01/02 + ACCESS-01/02/03/04 stubs (Plan 03-01, Task 1); import `require_manager`/`require_owner` INSIDE test bodies so collection succeeds before Plan 05 lands
- [ ] `tests/test_settings.py` — extend with `manager_roles`/`editor_roles` schema cases incl. the no-fallback assertion (Plan 03-01, Task 2)
- [ ] Fake/mock for `auth._fetch_member_roles` returning a configurable role-id set (mirror `tests/test_app_auth.py`'s `_FakeAsyncClient`) for callback tier-resolution tests
- [ ] `tests/conftest.py` — no new shared fixture required; reuse the existing per-test `TestClient` + `app.dependency_overrides` pattern from `tests/test_app_settings.py`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Variant-A visual fidelity (accents, spacing, Inter, brand-red logo-only, lock-icon placement, status-tile emphasis) | SHELL-01, SHELL-02 | Visual fidelity to the locked UI-SPEC cannot be asserted by string tests | Plan 03-08 checkpoint steps 2-3, 6 — compare against `.planning/sketches/001-dashboard-shell/index.html` |
| End-to-end tier UX across owner / Manager / editor logins (in-shell 403 experience, editor link, Overview live refresh) | ACCESS-01/02/03/04, SHELL-02 | Requires real Discord logins + running bot heartbeat; automated suite proves status codes, not lived flow | Plan 03-08 checkpoint steps 2-5 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (03-08 is the sole manual checkpoint, backed by automated 200/403 tests in 03-07)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test_app_dashboard.py, test_settings.py extension, _fetch_member_roles fake)
- [x] No watch-mode flags
- [x] Feedback latency < 90s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
