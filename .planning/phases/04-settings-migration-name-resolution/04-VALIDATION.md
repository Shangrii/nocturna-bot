---
phase: 04
slug: settings-migration-name-resolution
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-22
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.0.0 + `fastapi.testclient.TestClient` |
| **Config file** | none — `tests/conftest.py` puts repo root on `sys.path`; no `pytest.ini` |
| **Quick run command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_discord_names.py tests/test_discord_names_cog.py -x` |
| **Full suite command** | `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` |
| **Estimated runtime** | ~15 seconds |

**Env note:** Use the conda python for pytest (project memory — PowerShell's `Python314` has no pytest).
The `client` fixture in `tests/test_app_settings.py` (dummy OAuth config + `DB_PATH`→tmp +
`settings.seed_defaults()` + `dependency_overrides[require_owner]`) is the reusable harness. The
`_use_tmp_db` helper in `tests/test_settings.py` is the db-layer isolation idiom.

---

## Sampling Rate

- **After every task commit:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_discord_names.py tests/test_discord_names_cog.py -x`
- **After every plan wave:** Run `C:\Users\Shangri\miniconda3\python.exe -m pytest -q` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | SETT-02 | T-04-02 / T-04-05 | discord_names id stored TEXT; full-replace drops deleted rows; get tolerates empty | unit | `pytest tests/test_discord_names.py -x` | ❌ W0 (this task creates it) | ⬜ pending |
| 04-01-02 | 01 | 1 | SETT-01 / SETT-02 | T-04-03 | Two-pass regression + snowflake precision stay green; SETT render scaffolds RED | integration | `pytest tests/test_app_settings.py -k "two_pass or mixed_valid or precision" -x` | ✅ (extends existing) | ⬜ pending |
| 04-02-01 | 02 | 2 | SETT-02 | T-04-01 | ChannelType→subtype / Colour→hex pure mapping; @everyone skipped | unit | `pytest tests/test_discord_names_cog.py -x` | ❌ W0 (this task creates it) | ⬜ pending |
| 04-02-02 | 02 | 2 | SETT-02 | T-04-01 / T-04-04 | Cog reads gateway cache only (no REST); sole writer via replace_discord_names | unit (import smoke + grep) | `python -c "import cogs.discord_names"` + `pytest tests/test_discord_names_cog.py -x` | ✅ (Task 1 file) | ⬜ pending |
| 04-02-03 | 02 | 2 | SETT-02 | — | Cog always-loaded (not in optional try/except) | grep | `grep -n 'load_extension("cogs.discord_names")' bot.py` | N/A (source assert) | ⬜ pending |
| 04-03-01 | 03 | 2 | SETT-01 / SETT-02 | T-04-01 / T-04-02 / T-04-05 | String-keyed names map + names_fresh; require_owner/save_settings unchanged; lifespan init | integration | `pytest tests/test_app_settings.py -k "read_name_cache or two_pass or mixed_valid or precision" -x` | ✅ (Plan 01) | ⬜ pending |
| 04-03-02 | 03 | 2 | SETT-01 / SETT-02 | T-04-01 / T-04-03 | In-shell render, resolved names/chips, cold-cache banner; Manager still 403 | integration | `pytest tests/test_app_settings.py -x && pytest tests/test_app_dashboard.py -k settings -x` | ✅ (Plan 01) | ⬜ pending |
| 04-04-01 | 04 | 3 | SETT-01 / SETT-02 | T-04-03 / T-04-04 | Human visual + no-loss + owner-gate verification | manual | see Manual-Only Verifications | N/A (checkpoint) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_discord_names.py` — db triad contract (init/replace/get; deleted-row drop; empty→[]) — created in Plan 01 Task 1
- [ ] `tests/test_app_settings.py` (extend) — in-shell render, name resolution, cold-cache banner (D-06/D-07), string-keyed map, `_read_name_cache` helper, plus the preserved two-pass + snowflake-precision regression locks — created in Plan 01 Task 2 (render tests RED until Plan 03; forward-referenced symbols imported inside test bodies so collection stays clean)
- [ ] `tests/test_discord_names_cog.py` — pure `_map_channel_kind` / `_role_hex` unit tests — created in Plan 02 Task 1
- [ ] No framework install needed — pytest + TestClient already present.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Variant-A shell visual fidelity of the migrated Settings section (dark SaaS, Inter, per-module accents, one Save action, Access group last) | SETT-01 | Perceptual visual match cannot be asserted by a DOM test | Plan 04 checkpoint steps 1-2 |
| Role chips tinted with the actual per-role Discord color; channel type cues render correctly | SETT-02 | Color-bar tint and glyph correctness are perceptual | Plan 04 checkpoint steps 3-4 |
| Live client-side name lookup updates as the owner types/pastes an id before saving (D-09) | SETT-02 | Interactive Alpine behavior in a real browser | Plan 04 checkpoint step 5 |
| Cold-cache banner vs per-field markers distinction with a real stopped bot (D-07) | SETT-02 | Requires toggling the live bot process | Plan 04 checkpoint step 6 |
| End-to-end no-loss save + mixed valid/invalid atomicity as seen by the owner | SETT-01 | Confirms perceived parity with the v1 panel beyond the unit assertion | Plan 04 checkpoint step 7 |
| Non-owner sees the styled in-shell forbidden page (not the login page) | SETT-01 | Requires a real Manager session | Plan 04 checkpoint step 8 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (checkpoint 04-04 is manual by design)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test_discord_names.py, test_discord_names_cog.py, test_app_settings.py extensions)
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
