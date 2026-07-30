---
phase: 10
slug: editors-section-integration
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-30
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

This phase spans two codebases: the FastAPI bot (`nocturna-bot`, pytest) and the
static site (`Website`, Astro — no JS test harness; `npm run build` is the only
automated gate). Both are sampled below.

---

## Test Infrastructure

### `nocturna-bot` side (Python / pytest)

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing `tests/` suite) — run via the conda python, NOT PowerShell's Python314 (no pytest there; per project memory) |
| **Config file** | none (no `pytest.ini` / `pyproject.toml` pytest section) — rootdir discovery |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_editor.py tests/test_app_dashboard.py tests/test_editors_model.py -x` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/` |
| **Estimated runtime** | quick ~20s · full ~60s |

### `Website` side (Astro)

| Property | Value |
|----------|-------|
| **Framework** | None — no vitest/jest/playwright. The build IS the test: a malformed `getStaticPaths`/route fails `astro build` loudly |
| **Config file** | n/a |
| **Quick run command** | `cd "C:/Users/Shangri/Pictures/Nocturna Avatars/Coding/Website" && npm run build` |
| **Full suite command** | same — `npm run build` is the only automated gate this repo has |
| **Estimated runtime** | ~30–60s (cold) |

---

## Sampling Rate

- **After every task commit (bot side):** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_editor.py tests/test_app_dashboard.py tests/test_editors_model.py -x`
- **After every task commit (site side, plan 10-06 only):** `npm run build` in the Website repo
- **After every plan wave:** full `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/` (+ `npm run build` when a Wave touched the Website)
- **Before `/gsd:verify-work`:** full bot suite green AND `npm run build` green AND the 10-07 human-verify checkpoint approved
- **Max feedback latency:** ~20s (bot quick run); ~60s (site build)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | EDIT-01 | T-10-01 | Locked-nav GET /editor → 403 forbidden.html, session NOT cleared | unit (RED) | `pytest tests/test_app_dashboard.py -k "locked_editor_nav" -x` | ✅ extend | ⬜ pending |
| 10-01-02 | 01 | 1 | EDIT-01 | — | GET /editor renders in-shell (sidebar + /logout markers) | integration (RED) | `pytest tests/test_app_editor.py -k "renders_in_shell" -x` | ✅ extend | ⬜ pending |
| 10-01-03 | 01 | 1 | EDIT-02 | T-10-02 | resolve_slug rejects en/es/gallery/store/fonts/build | unit (RED) | `pytest tests/test_editors_model.py -k "reserved" -x` | ✅ extend | ⬜ pending |
| 10-01-04 | 01 | 1 | EDIT-01 | T-10-01 | Two pre-existing GET /editor tests override `_resolve_roles` → stay green across 10-02's gate switch | regression (forward-compat) | `pytest tests/test_app_dashboard.py::test_editor_only_locked_out_of_dashboard tests/test_app_editor.py::test_editor_page_renders_slug_field -x` | ✅ edit | ⬜ pending |
| 10-02-01 | 02 | 2 | EDIT-01 | T-10-01 / T-10-04 | GET /editor gates on `_resolve_roles` + `TierForbidden(editor)`; no session clear; identity from session only | unit/integration (GREEN) | `pytest tests/test_app_dashboard.py -k "locked_editor_nav" tests/test_app_editor.py -x` | ✅ | ⬜ pending |
| 10-02-02 | 02 | 2 | EDIT-02 | T-10-02 | RESERVED_SLUGS widened; namespace shadowing blocked | unit (GREEN) | `pytest tests/test_editors_model.py -k "reserved" -x` | ✅ | ⬜ pending |
| 10-03-01 | 03 | 1 | EDIT-01 | — | `--accent-editor` token + `.status-badge.pending` present | static/grep | `grep -q -- '--accent-editor:' app/static/dashboard.css && grep -q '\.status-badge\.pending' app/static/dashboard.css` | ✅ | ⬜ pending |
| 10-03-02 | 03 | 1 | EDIT-01 | T-10-06 | editor.css retinted onto dashboard tokens; preview canvas preserved verbatim | static/grep | `grep -q '\.editor-subhead' app/static/editor.css && grep -q 'data-kind="loading"' app/static/editor.css && grep -q 'var(--color-' app/static/editor.css` | ✅ | ⬜ pending |
| 10-04-01 | 04 | 2 | EDIT-01 | T-10-01 | 8th sidebar `sections[]` entry with uniform `is_editor` lock branch | integration | `pytest tests/test_app_dashboard.py tests/test_app_editor.py -k "editor" -x` | ✅ | ⬜ pending |
| 10-04-02 | 04 | 2 | EDIT-01 | — | Unconditional "Back to editor" topbar link removed | integration | `! grep -q 'Back to editor' app/templates/_dashboard_base.html && pytest tests/test_app_dashboard.py -x` | ✅ | ⬜ pending |
| 10-05-01 | 05 | 3 | EDIT-01 | — | editor.html extends shell (10-01-02 goes GREEN) | integration | `pytest tests/test_app_editor.py -k "renders_in_shell" -x` | ✅ | ⬜ pending |
| 10-05-02 | 05 | 3 | EDIT-01 | — | Sticky `.editor-subhead`; `/e/` vanity segment dropped | integration/grep | `grep -q 'editor-subhead' app/templates/editor.html && ! grep -q "'/e/'" app/templates/editor.html && pytest tests/test_app_editor.py -x` | ✅ | ⬜ pending |
| 10-06-01 | 06 | 1 | EDIT-02 | T-10-02 | Profile page at root vanity route; Astro build succeeds | build-gate | `cd .../Website && npm run build` | ✅ move | ⬜ pending |
| 10-06-02 | 06 | 1 | EDIT-02 | T-10-03 | `e/[slug].astro` is a build-time redirect stub (`define:vars` literal, no `?next=`) | build-gate/grep | `grep -q 'location.replace' src/pages/e/[slug].astro && grep -q 'define:vars' src/pages/e/[slug].astro && npm run build` | ✅ | ⬜ pending |
| 10-07-01 | 07 | 4 | EDIT-01, EDIT-02 | all | Full bot suite green (phase gate) | regression | `pytest tests/` | ✅ | ⬜ pending |
| 10-07-02 | 07 | 4 | EDIT-01, EDIT-02 | T-10-01 | End-to-end human-verify (OAuth→edit→publish→vanity URL→legacy redirect→locked-nav no-logout) | manual (checkpoint) | see Manual-Only Verifications | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity check:** no run of 3 consecutive tasks lacks an automated
`<verify>`. The only non-automated task (10-07-02) is a blocking human-verify checkpoint
that follows an automated phase gate (10-07-01), so the Nyquist floor holds.

---

## Wave 0 Requirements

All Wave 0 gaps are NEW CASES added to EXISTING test files (no new file or framework to
install) — created by plan 10-01 (Wave 1, RED-first) before any implementation lands:

- [ ] `tests/test_editors_model.py` — reserved-word cases for `en`/`es`/`gallery`/`store`/`fonts`/`build` (10-01 Task 3)
- [ ] `tests/test_app_dashboard.py` — `test_locked_editor_nav_click_keeps_session`: owner/Manager clicking the locked "Editor" nav gets `forbidden.html` (403, `required_tier == "editor"`) with an INTACT session (10-01 Task 1)
- [ ] `tests/test_app_editor.py` — `test_editor_page_renders_in_shell`: GET `/editor` body carries shell markers (`_sidebar.html` + topbar `/logout`) (10-01 Task 2)
- [ ] `tests/test_app_dashboard.py` + `tests/test_app_editor.py` — forward-compat the two pre-existing GET `/editor` tests to override `app.deps._resolve_roles` so they survive 10-02's gate switch (10-01 Task 4)

**Website side:** no JS/Astro test framework exists; the Wave 0 gap there is procedural —
run `npm run build` locally (or rely on CI's `deploy.yml`), not a missing test file.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end editor experience across both surfaces | EDIT-01, EDIT-02 | Visual/interactive: real Discord OAuth, live GitHub publish, browser render of the retinted in-shell editor, and DNS/CDN-served vanity URL resolution cannot be asserted headlessly | 10-07 Task 2: sign in via Discord → edit a profile → publish → confirm `nocturna-avatars.site/{slug}` resolves → confirm legacy `/e/{slug}` redirects to `/{slug}` → as an owner/Manager click the locked "Editor" nav item and confirm you are NOT logged out (forbidden page, session intact). Type "approved" when all five pass. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (10-07-02 is the lone manual checkpoint, gated behind automated 10-07-01)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (all three test files' new cases owned by 10-01)
- [x] No watch-mode flags (all commands are one-shot; `-x` fail-fast, `npm run build` is non-watch)
- [x] Feedback latency < 60s (bot quick ~20s; site build ~60s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-30
