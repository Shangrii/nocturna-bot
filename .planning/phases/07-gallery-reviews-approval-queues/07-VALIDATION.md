---
phase: 07
slug: gallery-reviews-approval-queues
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-23
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-anyio (conda python — `C:\Users\Shangri\miniconda3\python.exe -m pytest`) |
| **Config file** | none at repo root — anyio backend fixture defined per test file (`anyio_backend()` returns "asyncio") |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest` |
| **Estimated runtime** | ~20–40 seconds |

---

## Sampling Rate

- **After every task commit:** Run the task's `<automated>` command (single test file, `-x`)
- **After every plan wave:** Run the wave-merge command (see below)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~40 seconds (full suite)

Wave-merge command:
`C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_gallery_reviews_cache_cog.py tests/test_action_queue_cog.py tests/test_app_gallery.py tests/test_app_reviews.py -x`

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | GAL-01 / REV-01 | T-07-02 / T-07-04 | Parameterized SQL only; queue helpers roundtrip; upsert preserves poster/author | unit | `pytest tests/test_gallery_reviews_cache_cog.py -k "queue_row or roundtrip or upsert" -x` | ❌ W0 (this task) | ⬜ pending |
| 07-01-02 | 01 | 1 | GAL-01 / REV-01 | T-07-01 / T-07-03 | Anon review never stores real name; bounded scan; classify via reused helpers | unit | `pytest tests/test_gallery_reviews_cache_cog.py -x` | ❌ W0 (this task) | ⬜ pending |
| 07-02-01 | 02 | 1 | GAL-02 / GAL-03 / REV-01 / REV-02 | T-07-05 / T-07-06 / T-07-07 | Pre/post 🟢 transition derives success; channel-scoped fetch; no direct transport | unit | `pytest tests/test_action_queue_cog.py -x` | ❌ W0 (extend existing) | ⬜ pending |
| 07-02-02 | 02 | 1 | GAL-02 / GAL-03 / REV-01 / REV-02 | T-07-06 / T-07-07 | Fresh/moot success + genuine failure per kind (D-11); deleted-message → ✗ | unit | `pytest tests/test_action_queue_cog.py -k "gallery_publish or gallery_remove or review_publish or review_remove" -x` | ❌ W0 (extend existing) | ⬜ pending |
| 07-03-01 | 03 | 2 | GAL-01/02/03 / REV-01/02 | T-07-09 / T-07-10 | Manager-gated routes; message_id int; 404 on stale; enqueue correct kind | unit (import) | `python -c "import app.routers.gallery, app.routers.reviews"` | ❌ W0 (this task) | ⬜ pending |
| 07-03-02 | 03 | 2 | GAL-02/03 / REV-01/02 | T-07-11 | _ALLOWED_KINDS matched pair with dispatcher; stubs removed | unit (import) | `python -c "import app.main; assert {'gallery_publish','gallery_remove','review_publish','review_remove'} <= app.main._ALLOWED_KINDS"` | n/a (existing) | ⬜ pending |
| 07-03-03 | 03 | 2 | GAL-01/02/03 / REV-01/02 | T-07-09 / T-07-10 / T-07-12 | 403 non-Manager; 404 stale; 422 non-int; JSON refresh; anon-safe /queue | integration | `pytest tests/test_app_gallery.py tests/test_app_reviews.py -x` | ❌ W0 (this task) | ⬜ pending |
| 07-04-01 | 04 | 3 | GAL-01 / REV-01 | — | Closed-token CSS; only pre-locked 12px exception | unit (asset) | `python -c "css=open('app/static/dashboard.css',encoding='utf-8').read(); assert '.gcard' in css and 'minmax(220px' in css"` | n/a (existing) | ⬜ pending |
| 07-04-02 | 04 | 3 | GAL-01/02/03 | T-07-14 / T-07-15 / T-07-16 | Jinja autoescape; confirm-gated remove; view-only lightbox; D-02 refresh | integration | `pytest tests/test_app_gallery.py -k "render or page" -x` | ✅ (07-03) | ⬜ pending |
| 07-04-03 | 04 | 3 | REV-01 / REV-02 | T-07-13 | Anon card renders only "Anónimo"; no star UI | integration | `pytest tests/test_app_reviews.py -k "render or page or anon" -x` | ✅ (07-03) | ⬜ pending |
| 07-04-04 | 04 | 3 | GAL-01 / REV-01 | T-07-13 | GET-render + anonymity at the HTML boundary | integration | `pytest tests/test_app_gallery.py tests/test_app_reviews.py -x` | ✅ (07-03) | ⬜ pending |
| 07-05-01 | 05 | 4 | all | — | Full suite green before live checkpoint | suite | `pytest -q` | ✅ | ⬜ pending |
| 07-05-02 | 05 | 4 | all | T-07-06 / T-07-13 | Live no-double-publish + anonymity (human-verify) | manual | human checkpoint | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Test files are created RED-first inside their owning plan's first task (no separate Wave-0 plan):

- [ ] `tests/test_gallery_reviews_cache_cog.py` — created in 07-01 Task 1 (db roundtrip/upsert) + extended in Task 2 (classification, poster resolution, anonymity). Covers GAL-01 / REV-01 read side.
- [ ] `tests/test_action_queue_cog.py` — EXTENDED in 07-02 with four `kind` test groups (fresh/moot/failure + deleted-message). Covers GAL-02 / GAL-03 / REV-01 / REV-02.
- [ ] `tests/test_app_gallery.py`, `tests/test_app_reviews.py` — created in 07-03 Task 3 (gate/enqueue/404/422/JSON refresh) + extended in 07-04 Task 4 (GET-render + anonymity).
- [ ] Framework install: none — pytest + pytest-anyio already present and used (test_action_queue_cog.py precedent).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live approve publishes to the real website with ✅-flow parity; concurrent reaction does NOT double-publish | GAL-02 | Requires a live Discord message + live cross-repo GitHub commit; the no-double-publish race only fully manifests against real reaction state | 07-05 Task 2 steps 2–3 (approve + simultaneously add ✅; confirm exactly one publish + one 🟢, panel shows calm D-11 success) |
| Live remove takes a photo/review off the site (🌙 parity) | GAL-03 / REV-02 | Live cross-repo commit | 07-05 Task 2 steps 4–5 |
| Anonymous review shows only "Anónimo" in the live panel | REV-01 / D-13 | End-to-end identity discard is only fully observable with real submitted reviews | 07-05 Task 2 step 6 |
| Bot-offline durability: click enqueues, runs on reconnect without a re-click | D-09 | Requires stopping/starting the live bot process | 07-05 Task 2 step 7 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or a manual-checkpoint justification
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (RED-first inside each owning plan)
- [x] No watch-mode flags
- [x] Feedback latency < 40s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
