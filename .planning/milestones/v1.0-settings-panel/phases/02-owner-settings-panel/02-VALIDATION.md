---
phase: 2
slug: owner-settings-panel
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-21
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Formalized from `02-RESEARCH.md` § "Validation Architecture" and the per-task `<verify>`
> blocks in `02-01`…`02-04-PLAN.md`.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing suite: `tests/test_settings.py`, `tests/test_app_auth.py`, `tests/test_app_editor.py`) |
| **Config file** | none — no `pytest.ini`/`pyproject.toml` in repo; pytest runs with defaults, repo root on `sys.path` via `tests/conftest.py` |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_settings.py -x` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest` |
| **Estimated runtime** | ~20 seconds (full suite; quick run < 5s) |

*Per project MEMORY: use the conda python (`C:\Users\Shangri\miniconda3\python.exe -m pytest`),
NOT PowerShell's Python314 (no pytest).*

---

## Sampling Rate

- **After every task commit:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_settings.py -x`
- **After every plan wave:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | PANEL-02 | T-02-02 | all_for_ui() emits label/min/max/options; no secret in output | unit | `…pytest tests/test_settings.py -k all_for_ui -x` | ✅ extend | ⬜ pending |
| 2-01-02 | 01 | 1 | PANEL-03 | T-02-01 | validate_only rejects unknown key + bad value WITHOUT writing | unit | `…pytest tests/test_settings.py -k validate_only -x` | ✅ extend | ⬜ pending |
| 2-02-01 | 02 | 1 | PANEL-01 | T-02-03 / T-02-04 | RED: owner-gate fail-closed on 0, str/int normalization, non-owner 403 | unit | `…pytest tests/test_app_auth.py -k require_owner -x` | ❌ W0 (extend) | ⬜ pending |
| 2-02-02 | 02 | 1 | PANEL-01 | T-02-03 / T-02-05 | GREEN: require_owner session-only, fail-closed guard before compare | unit | `…pytest tests/test_app_auth.py -x` | ✅ (2-02-01) | ⬜ pending |
| 2-03-01 | 03 | 2 | PANEL-02 | T-02-06 / T-02-08 | settings.html renders 7 typed controls; single-quoted hydrate; no secret | integration (render) | `…pytest tests/test_settings_template.py -x` | ❌ W0 (new) | ⬜ pending |
| 2-03-02 | 03 | 2 | PANEL-02 | T-02-06 | owner-only link is `{% if is_owner %}`-guarded; inline-error CSS present | integration (render) | `…pytest tests/test_settings_template.py -x` | ✅ (2-03-01) | ⬜ pending |
| 2-04-01 | 04 | 3 | PANEL-01,02,03,04 | T-02-09 / T-02-13 | RED: gate 403, GET secret-absence, atomic no-partial-write, read-at-use round-trip | integration | `…pytest tests/test_app_settings.py -x` | ❌ W0 (new) | ⬜ pending |
| 2-04-02 | 04 | 3 | PANEL-02 | T-02-03 / T-02-13 | GET 200 grouped + is_owner context; non-owner 403 no data | integration | `…pytest tests/test_app_settings.py -k "get or owner" tests/test_app_editor.py -x` | ✅ (2-04-01) | ⬜ pending |
| 2-04-03 | 04 | 3 | PANEL-03 | T-02-09 / T-02-10 / T-02-11 | POST atomic validate-then-write; invalid → 422 errors, zero writes | integration | `…pytest tests/test_app_settings.py -x` | ✅ (2-04-01) | ⬜ pending |

*Command prefix `…` = `C:\Users\Shangri\miniconda3\python.exe -m`.*
*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**PANEL-04 note:** Already satisfied by Phase-1's read-at-use shim (`config.py.__getattr__` →
`settings.get`). This phase requires no bot-side code; task 2-04-01 confirms it observably with a
round-trip test (valid POST → `settings.get` reflects the new value). The existing
`tests/test_settings.py` round-trip tests remain the unit-level guarantee.

---

## Wave 0 Requirements

Test scaffolding is created RED-first as the FIRST task inside each owning plan (no separate Wave-0
plan for this phase — the plan↔test-file mapping is 1:1, so embedding keeps file ownership clean):

- [ ] `tests/test_app_settings.py` — NEW; gate/GET/atomic-POST/round-trip integration tests (created RED in task 2-04-01; mirrors the `client` fixture from `tests/test_app_editor.py` + `_use_tmp_db`/`seed_defaults` from `tests/test_settings.py`)
- [ ] `tests/test_settings_template.py` — NEW; isolated settings.html render smoke test over a real `all_for_ui()` payload (created in task 2-03-01)
- [ ] `tests/test_app_auth.py` — EXTEND with 4 `require_owner` unit tests (created RED in task 2-02-01, co-located with the existing `require_editor` tests)
- [ ] `tests/test_settings.py` — EXTEND `test_all_for_ui_grouped` for the D-09 metadata keys + add `validate_only` tests (tasks 2-01-01 / 2-01-02)
- No new fixtures/conftest needed — reuse `_use_tmp_db` and the `client` TestClient pattern.

`wave_0_complete: false` — scaffolding is planned as RED-first tasks but not yet built (planning stage;
no code executed). It flips true once the Wave-1 RED tasks land.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Visual layout / bilingual copy / Alpine field-error placement on the live page | PANEL-02 | Rendered look-and-feel and interactive per-field error UX are not asserted by the render smoke test | Log in as the owner, visit `/admin/settings`, confirm grouped fields render, submit an out-of-range value, and confirm the inline `.field-error` appears under the offending field with the bilingual banner |

*All security-critical and functional behaviors (gate, secret-absence, atomic write, round-trip)
have automated coverage; only the subjective visual/interaction polish is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test_app_settings.py, test_settings_template.py, test_app_auth.py + test_settings.py extensions)
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** APPROVED (2026-07-21, gsd-planner — validation architecture transcribed from 02-RESEARCH.md § Validation Architecture and per-task `<verify>` blocks)
