---
phase: 02-owner-settings-panel
verified: 2026-07-21T19:30:00Z
status: passed
score: 4/4 roadmap success criteria verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 2/4
  gaps_closed:
    - "GET /admin/settings renders the tunables grouped by feature with typed fields, and no secret ever appears in the form (CR-01 snowflake precision loss)"
    - "A valid POST persists to the store and re-renders with a success banner; an invalid POST returns an inline field error and writes nothing (CR-02 CONF-03 fallback baking on unchanged save)"
  gaps_remaining: []
  regressions: []
human_verification: []
---

# Phase 2: Owner Settings Panel Verification Report

**Phase Goal:** The owner can view and edit the safe tunables from a web form on the existing admin app, with server-side validation gating every write and secrets never exposed.
**Verified:** 2026-07-21T19:30:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plan 02-05, commits 7699ccc/c88c728/f713571)

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A non-owner hitting any `/admin/settings` route gets 403 and no data; the owner gets 200. The gate fails closed when `DISCORD_USER_ID` is unset. | VERIFIED (regression check — unchanged since prior PASS) | `app/deps.py::require_owner` (lines 69-94) unchanged: `if not owner_id: raise 403` runs BEFORE the identity comparison, both operands `str()`-normalized, identity read from `request.session` only. `app/main.py` wires `Depends(require_owner)` on both GET (line 424) and POST (line 444). `tests/test_app_auth.py` + the two 403-path tests in `tests/test_app_settings.py` pass. |
| 2 | `GET /admin/settings` renders the tunables grouped by feature with typed fields, and no secret ever appears in the form. | VERIFIED (gap closed) | `core/settings.py::all_for_ui()` (lines 379-423) now sources every entry's value from the new `_get_raw()` (lines 323-344) and string-serializes `snowflake` → `str(value)` and `role_list` → comma-joined `str` before the value is placed on the entry. Independently reproduced (not just re-reading the review): direct call after `seed_defaults()` — `PHOTO_CHANNEL_ID` value is `'1416329356426481717'` of type `str`; `json.dumps(all_for_ui())` (the `tojson`-equivalent payload) contains zero bare integer literals ≥ 16 digits. Secret-absence guarantee unchanged (`_SCHEMA` allowlist; `tests/test_app_settings.py::test_get_settings_owner_renders_grouped_no_secret` passes). |
| 3 | A valid POST persists to the store and re-renders with a success banner; an invalid POST returns an inline field error and writes nothing. | VERIFIED (gap closed) | The narrow atomicity behavior (unchanged, still passing) plus the CR-02 defect is fixed: `all_for_ui()`'s payload now carries the RAW (unresolved) staff-role value via `_get_raw()`, which omits the `fallback_key` branch. Independently reproduced end-to-end via `TestClient`: seeded `GALLERY_STAFF_ROLE_IDS=[111]`, flattened `all_for_ui()` (mirroring `settingsApp`'s exact client-side flatten in `settings.html:104-114`), POSTed the payload UNCHANGED to `/admin/settings` → 200 `{ok:true}`; `REVIEWS_STAFF_ROLE_IDS` remained `[111]` (still cascading, not baked); a subsequent gallery-only edit to `[222]` cascaded to `REVIEWS_STAFF_ROLE_IDS`/`REMINDERS_STAFF_ROLE_IDS`/`JINXXY_STAFF_ROLE_IDS`, all now `[222]`. This is the exact CR-02 repro from the prior verification, now inverted. `get()` itself is byte-identical (confirmed by direct read of `core/settings.py:295-320`) — the bot's read-time CONF-03 cascade is untouched. |
| 4 | After a save, the bot picks up the new value on its next relevant use (loop-interval changes on the next cycle). | VERIFIED | `settings.get(key)` reflects a POSTed value immediately (`tests/test_app_settings.py::test_post_settings_round_trip_visible_to_settings_get`, `::test_post_settings_valid_change_persists_and_returns_ok`). CONF-01 read-at-use wiring in `config.py::__getattr__` (routes `_SAFE_TUNABLE_KEYS` through `settings.get`) is unchanged from Phase 1 and untouched by this gap-closure plan. The gap-2 concern (an untouched field's resolved value silently overwriting what the bot reads) no longer applies now that `all_for_ui()` exposes the raw, unresolved value. |

**Score:** 4/4 roadmap success criteria verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/settings.py` (`all_for_ui`, `_get_raw`, `get`, `validate_only`) | Raw-value reader + string-serializing UI payload, byte-identical `get()` | VERIFIED (exists, substantive, wired, tested) | `_get_raw()` (lines 323-344) duplicates `get()`'s SELECT+json.loads+fallback-to-default resolution but omits the `fallback_key` branch; `all_for_ui()` (line 405) calls `_get_raw(descriptor.key)` and coerces snowflake/role_list to `str` (lines 406-409). `get()` (lines 295-320) is unchanged from the pre-gap-closure version. |
| `app/deps.py::require_owner` | Fail-closed owner gate | VERIFIED (unchanged, regression-checked) | Confirmed by direct read: falsy-guard before comparison, str-normalization, session-only identity. |
| `app/templates/settings.html` | SSR + Alpine hydrate form, typed controls | VERIFIED (unchanged, confirmed no template edit was needed) | `x-model="values[setting.key]"` on `type="text"` inputs for snowflake/role_list (lines 47, 53) already bind strings; `tojson` now emits quoted strings for those fields since the source data changed, requiring zero template changes — confirmed by direct read. |
| `tests/test_settings.py` | Unit regression: snowflake/role_list are strings, no bare int > 2**53, raw value bypasses fallback | VERIFIED | Contains `_get_raw`/`all_for_ui`-targeted tests; 22 tests in this file pass. |
| `tests/test_app_settings.py` | Integration regression: full-form GET→POST-unchanged preserves snowflake precision and the CONF-03 cascade | VERIFIED | `test_post_settings_unchanged_save_preserves_snowflake_precision` and `test_post_settings_unchanged_save_preserves_staff_role_cascade` (using a `_flatten()` helper that mirrors `settingsApp`'s client-side flatten exactly) both present and passing. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `app/main.py` GET/POST `/admin/settings` | `require_owner` | `Depends(require_owner)` | WIRED | Confirmed in both route decorators, unchanged. |
| `core/settings.py::all_for_ui` | `core/settings.py::_get_raw` | raw stored value, no fallback resolution | WIRED | `all_for_ui()` line 405 calls `_get_raw(descriptor.key)`, not `get(`. Confirmed by direct read. |
| `core/settings.py::all_for_ui` | `app/templates/settings.html` tojson payload | `str()`/comma-join serialization → tojson emits quoted strings | WIRED | `settings_page` passes `settings.all_for_ui()` directly as `groups`; template's `x-data='settingsApp({{ groups | tojson }})'` (line 22) unchanged; snowflake/role_list values are now pre-quoted strings by the time they reach `tojson`. |
| `settings.html::save()` | `/admin/settings` | `fetch POST application/json` | WIRED | `fetch('/admin/settings', {method: 'POST', ...})` confirmed; `serialize()` posts `{...this.values}` — every key, current (now string-safe) value. |
| `app/main.py` POST `/admin/settings` | `settings.validate_only` then `settings.set` | two-pass validate-all-then-write-all | WIRED | Unchanged; `validate_only` loop precedes the `set` loop. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `settings.html` `groups`/`values` | `settings.all_for_ui()` | Real sqlite-backed `settings` table via `core/settings.py::_get_raw()` | Yes (real, raw, unresolved data) | FLOWING and integrity-preserving — independently reproduced via direct Python call and via a live `TestClient` GET-payload → POST-unchanged round trip; snowflake precision and the CONF-03 cascade both survive. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `settings.all_for_ui()` snowflake value type/precision | Direct Python call against a real tmp-DB store (independently executed, not re-reading prior evidence) | `PHOTO_CHANNEL_ID` value is `<class 'str'> '1416329356426481717'`; `json.dumps(all_for_ui())` contains zero bare int literals ≥ 16 digits | PASS — CR-01 fix confirmed live |
| GET→POST-unchanged preserves CONF-03 cascade | Direct Python round trip: seed `GALLERY_STAFF_ROLE_IDS=[111]`, call `all_for_ui()`, confirm `REVIEWS_STAFF_ROLE_IDS` raw value is `""`, confirm `settings.get("REVIEWS_STAFF_ROLE_IDS")` still cascades to `[111]` | Raw payload value `""`; `get()` cascade `[111]` | PASS — CR-02 fix confirmed live |
| `pytest tests/test_settings.py tests/test_app_settings.py tests/test_settings_template.py tests/test_app_auth.py -q` | Direct execution | 59 passed | PASS |
| `pytest -q` (full repo suite, regression check) | Direct execution | 645 passed | PASS — no regressions introduced by the gap-closure plan |
| Debt-marker scan (`TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`) on `core/settings.py`, `tests/test_settings.py`, `tests/test_app_settings.py` | `grep -inE` | One match: `core/settings.py:352` "parameterized `?` placeholder" — a legitimate reference to a SQL placeholder, not a debt marker | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` conventional probes exist in this repository and none are declared in the Phase 2 plans/summaries. SKIPPED — no probes to run.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| PANEL-01 | 02-02-PLAN, 02-04-PLAN | `require_owner` gate, fails closed | SATISFIED | `app/deps.py::require_owner` unchanged since the prior verified PASS; `tests/test_app_auth.py` + 403-path tests pass. |
| PANEL-02 | 02-01-PLAN, 02-03-PLAN, 02-04-PLAN, 02-05-PLAN | GET renders typed, grouped, secret-free form | SATISFIED | Renders, is secret-free, and now (post gap-closure) preserves Discord ID precision through the `tojson`/JS boundary — CR-01 independently reproduced as fixed. |
| PANEL-03 | 02-01-PLAN, 02-04-PLAN, 02-05-PLAN | POST validates server-side, atomic write, secrets never written bad | SATISFIED | Two-pass validate-then-write correctly wired; CR-02 independently reproduced as fixed — an ordinary unchanged save no longer bakes the CONF-03 fallback into dependent keys. |
| PANEL-04 | 02-04-PLAN | Saved change is read by the bot on next use | SATISFIED | `settings.get` reflects a POSTed value immediately (tested); the gap-2 cascade-baking risk that undermined this truth's broader intent is resolved. |

**Orphan check:** `.planning/REQUIREMENTS.md` maps exactly PANEL-01..04 to Phase 2; all four appear in at least one plan's `requirements:` frontmatter (02-01: PANEL-02/03; 02-02: PANEL-01; 02-03: PANEL-02; 02-04: PANEL-01/02/03/04; 02-05 gap-closure: PANEL-02/03). No orphaned requirements.

**Note (documentation bookkeeping, not a code gap):** `REQUIREMENTS.md`'s own traceability table (lines 89-92) still marks PANEL-02/PANEL-03 "Complete" and PANEL-01/PANEL-04 "Pending" — this table was written before Phase 2 execution and was never updated to reflect either the original code review or this gap closure. It does not affect the code-level verdict above (all four requirements are independently SATISFIED against the current codebase), but the table should be refreshed for accuracy.

### Anti-Patterns Found

None blocking. No `TBD`/`FIXME`/`XXX`/unreferenced debt markers in the gap-closure files (`core/settings.py`, `tests/test_settings.py`, `tests/test_app_settings.py`). The two previously-BLOCKER findings (CR-01, CR-02) are resolved and independently confirmed fixed in this verification.

Carried-forward WARNING/INFO items from `02-REVIEW.md` (robustness/consistency, not data-integrity blockers, and out of scope for the CR-01/CR-02 gap-closure plan — confirmed still present via direct inspection):

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/main.py` | lifespan (~271-286) | WR-01: `db.init_settings()` still missing from the `try` block that pre-creates `init_presence`/`init_view_counts` | WARNING | Fresh-deploy race: first POST 500s if the admin app starts before the bot has seeded the settings table. Confirmed absent via grep — unchanged from the prior verification, not addressed by 02-05 (out of scope for that plan). |
| `app/main.py` | ~478-481 | WR-02: multi-key write loop is not transactional; a mid-loop failure leaves a partial write and an unhandled 500 | WARNING | Only manifests under a DB/disk error mid-write; unchanged from prior verification. |
| `app/main.py` | ~305-310 | WR-04: CORS origin bakes the panel-tunable `WEBSITE_BASE_URL` at import time | WARNING | Unchanged; cosmetic/documentation risk, not a data-integrity defect. |
| `app/deps.py` | 69-94 | WR-06: `/admin/settings` skips the live role re-check that `require_editor` performs elsewhere | WARNING | Unchanged; small blast radius (only the single configured owner ID can ever pass). |

These four warnings do not block phase goal achievement — none of them concern the roadmap success criteria (owner gate correctness, typed/secret-free render, valid-POST-persists/invalid-POST-rejects, bot-reads-next-use). They were already present and accepted as non-blocking at the time of the original code review; the gap-closure plan correctly scoped itself to CR-01/CR-02 only, per its own `<objective>`.

### Human Verification Required

None. Both previously-failed roadmap success criteria (SC2/PANEL-02, SC3/PANEL-03) were reproduced as FIXED via direct, independent code execution in this verification session — a fresh Python `all_for_ui()` call (type/precision check for CR-01) and a fresh `TestClient` GET→POST-unchanged→gallery-edit round trip (cascade-survival check for CR-02) — not by re-reading 02-REVIEW.md's or 02-05-SUMMARY.md's claims. No browser or visual judgment call is needed to confirm they are real and fixed.

### Gaps Summary

None. Both CRITICAL findings from `02-REVIEW.md` (CR-01 snowflake/role-list precision corruption; CR-02 staff-role fallback cascade destruction), which drove the prior `gaps_found` verdict, were closed by gap-closure plan 02-05 (commits `7699ccc`, `c88c728`, `f713571`) and are independently confirmed resolved in this re-verification via direct code execution against the current HEAD, not by trusting the plan's SUMMARY or the code review's re-check. `core/settings.py::get()` remains byte-identical, so Phase 1's CONF-03 cascade is unaffected. The full Phase 2 test surface (59 tests) and the full repository suite (645 tests) both pass with no regressions.

All four roadmap success criteria are now VERIFIED. All four requirement IDs (PANEL-01..04) are SATISFIED. The phase goal — "The owner can view and edit the safe tunables from a web form on the existing admin app, with server-side validation gating every write and secrets never exposed" — is achieved in the current codebase.

Four non-blocking WARNING-level robustness/consistency findings from the original code review (WR-01, WR-02, WR-04, WR-06) remain open but were out of scope for this gap-closure plan and do not affect any roadmap success criterion. They may be worth a future hardening pass but are not escalation-worthy for this phase.

---

*Verified: 2026-07-21T19:30:00Z*
*Verifier: Claude (gsd-verifier)*
