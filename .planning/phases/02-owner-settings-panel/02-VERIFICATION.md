---
phase: 02-owner-settings-panel
verified: 2026-07-21T18:00:00Z
status: gaps_found
score: 2/4 roadmap success criteria verified
overrides_applied: 0
gaps:
  - truth: "GET /admin/settings renders the tunables grouped by feature with typed fields, and no secret ever appears in the form (with the rendered/edited values being data-integrity-preserving, not silently corrupted)"
    status: failed
    reason: >
      core/settings.py::all_for_ui() serializes snowflake (single ID) and role_list
      (list of IDs) values as Python int/list[int] — reproduced directly: PHOTO_CHANNEL_ID's
      default 1416329356426481717 comes back from all_for_ui() as a bare `int`.
      settings.html hydrates via `x-data='settingsApp({{ groups | tojson }})'`, which Jinja's
      `tojson` renders as a bare JSON number literal (confirmed: `1416329356426481717` with no
      quotes). Alpine/JS parses that literal as an IEEE-754 double; Discord snowflakes
      (17-20 digits) exceed Number.MAX_SAFE_INTEGER (9007199254740991) by three orders of
      magnitude, so the value is silently rounded before it is ever shown in the input.
      Server-side validation (`_validate_channel_id` — `str(value).isdigit()`) accepts the
      corrupted-but-still-numeric value, so one "Save settings" click with zero edits can
      rewrite every channel/forum/role ID in the store to a wrong value. This is CR-01 in
      02-REVIEW.md and remains unfixed in the current HEAD (a1fa945) — no follow-up commit
      touches core/settings.py's value serialization or settings.html's snowflake/role_list
      binding since the review was written.
    artifacts:
      - path: "core/settings.py"
        issue: "all_for_ui() emits raw int/list[int] for snowflake/role_list type_tags (line ~373-386) instead of strings; confirmed via direct call: all_for_ui() -> PHOTO_CHANNEL_ID value is <class 'int'> 1416329356426481717"
      - path: "app/templates/settings.html"
        issue: "x-data='settingsApp({{ groups | tojson }})' (line 22) hydrates the raw numeric payload into a JS scope with no string-guard for snowflake/role_list values; x-model on the snowflake/role_list inputs (lines 47, 53) binds directly to the (corrupted) numeric value"
    missing:
      - "Serialize snowflake values as str and role_list entries as list[str] in all_for_ui() (validators already accept digit strings, so the POST round-trip needs no further change)"
      - "A regression test asserting all_for_ui() never emits a bare int/float for a snowflake/role_list value (or, more directly, that no numeric literal above 2**53 appears in the tojson-serialized payload)"

  - truth: "A valid POST persists to the store and re-renders with a success banner; the bot never reads a bad value because a normal save does not silently corrupt unrelated settings (CONF-03's staff-role fallback-to-GALLERY cascade must survive ordinary panel use, per the phase's stated Core Value: 'without exposing secrets or letting a bad value break a cog')"
    status: failed
    reason: >
      Reproduced directly against the live route: seeded GALLERY_STAFF_ROLE_IDS=[111] (so
      REVIEWS_STAFF_ROLE_IDS, which is stored empty, cascades to [111] via the CONF-03
      read-time fallback). Built the payload exactly as settings.html's client does — GET the
      groups via all_for_ui(), flatten to a full key->value map — and POSTed it back UNCHANGED
      (mirrors clicking "Guardar ajustes" with no edits). The POST succeeds (200, {ok:true}).
      After the save, GALLERY_STAFF_ROLE_IDS was changed to [222] and REVIEWS_STAFF_ROLE_IDS
      still returned [111] instead of cascading to [222] — the fallback is permanently broken
      because the resolved value was baked into REVIEWS_STAFF_ROLE_IDS's own row. This is CR-02
      in 02-REVIEW.md, confirmed still present: settings.html::serialize() (lines 138-140)
      posts `{...this.values}` (every key, always) and all_for_ui()'s `value` field
      (core/settings.py line 376) is sourced via get(), which resolves the fallback. This
      directly breaks Phase 1's CONF-03 requirement through completely ordinary use of the
      Phase 2 panel — not an edge case, but the panel's designed always-post-the-whole-form
      behavior.
    artifacts:
      - path: "app/templates/settings.html"
        issue: "serialize() (lines 138-140) returns the full flattened values map on every save; the client has no concept of 'dirty' vs 'untouched' fields"
      - path: "core/settings.py"
        issue: "all_for_ui()'s entry['value'] = get(descriptor.key) (line 376) resolves the CONF-03 fallback before the value ever reaches the editable payload, so an unmodified round-trip bakes it in"
    missing:
      - "all_for_ui() should expose the raw stored value (bypassing the fallback_key resolution) for the editable payload — or the client should diff against the initial snapshot and post only changed keys"
      - "An integration test seeding a gallery role, GETting the panel payload, POSTing it back unchanged, and asserting the dependent (REVIEWS/REMINDERS/JINXXY) staff-role key still cascades from a subsequent gallery edit"
human_verification: []
---

# Phase 2: Owner Settings Panel Verification Report

**Phase Goal:** The owner can view and edit the safe tunables from a web form on the existing admin app, with server-side validation gating every write and secrets never exposed.
**Verified:** 2026-07-21T18:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A non-owner hitting any `/admin/settings` route gets 403 and no data; the owner gets 200. The gate fails closed when `DISCORD_USER_ID` is unset. | VERIFIED | `app/deps.py::require_owner` (lines 69-94) checks `if not owner_id: raise 403` BEFORE the identity comparison, str-normalizes both operands, reads identity from `request.session` only. `app/main.py` wires `Depends(require_owner)` on both GET (line 424) and POST (line 444). `tests/test_app_auth.py` (4 tests) and `tests/test_app_settings.py` (403-no-data tests) pass — ran locally: 52/52 relevant tests pass. |
| 2 | `GET /admin/settings` renders the tunables grouped by feature with typed fields, and no secret ever appears in the form. | FAILED | Renders and groups correctly, and the secret-absence guarantee holds (verified: `_SCHEMA` allowlist, tests assert absence). **However** snowflake/role_list values are corrupted by JS float-precision loss before display — see gap 1 (CR-01, reproduced directly: `all_for_ui()` emits `PHOTO_CHANNEL_ID` as Python `int` 1416329356426481717, serialized by `tojson` as a bare JS number literal that exceeds `Number.MAX_SAFE_INTEGER`). The "typed field" contract is not integrity-preserving for real Discord IDs. |
| 3 | A valid `POST` persists to the store and re-renders with a success banner; an invalid `POST` returns an inline field error and writes nothing. | FAILED | The narrow, tested behavior works (single-field valid POST persists; mixed valid/invalid POST writes nothing — `tests/test_app_settings.py` passes). **However**, because the client always posts the entire form (`serialize()` returns all 19 keys) and `all_for_ui()`'s value is fallback-resolved, a "valid" POST — even an unmodified save — permanently bakes the CONF-03 staff-role cascade into its dependent keys. Reproduced directly (see gap 2): GET+POST-unchanged, then editing `GALLERY_STAFF_ROLE_IDS`, leaves `REVIEWS_STAFF_ROLE_IDS` stuck on the old resolved value instead of cascading. This is exactly the "letting a bad value break a cog" failure mode the milestone's Core Value statement (REQUIREMENTS.md) explicitly rules out. |
| 4 | After a save, the bot picks up the new value on its next relevant use (loop-interval changes on the next cycle). | VERIFIED (narrow), with caveat | `tests/test_app_settings.py` proves `settings.get(key)` reflects a POSTed value immediately — the specific literal truth holds. Caveat: this truth's spirit is undermined by gap 2's cascade-baking bug (a saved value that was never intentionally edited by the owner still overwrites what the bot reads). Also noted as a deployment risk (not blocking this truth): `app/main.py`'s `lifespan` calls `db.init_presence()`/`db.init_view_counts()` but not `db.init_settings()` (WR-01 in 02-REVIEW.md) — on a fresh deploy where the admin app starts before the bot seeds the table, the first POST 500s. Confirmed via `grep`: `init_settings` does not appear in `app/main.py`. |

**Score:** 2/4 roadmap success criteria fully verified (SC1, SC4-narrow); 2/4 have confirmed, reproduced, unfixed critical defects (SC2, SC3).

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/settings.py` (`all_for_ui`, `validate_only`) | D-09 render metadata + dry-run validation | VERIFIED (exists, substantive, wired, tested) | `label`/`min`/`max`/`options` present for all relevant type_tags; `validate_only` is DB-free and preserves the `_SCHEMA` allowlist. 17/17 `tests/test_settings.py` pass. Value-serialization defect (gap 1) is a real bug but does not remove artifact substance. |
| `app/deps.py::require_owner` | Fail-closed owner gate | VERIFIED | Confirmed by direct read: falsy-guard before comparison, str-normalization, session-only identity. `require_editor` untouched. |
| `app/templates/settings.html` | SSR + Alpine hydrate form, 7 typed controls, per-field errors | VERIFIED (exists, substantive, wired) but carries the CR-01/CR-02 data-integrity defects | All 7 `type_tag` controls present; single-quoted `x-data='settingsApp('` present; `.field-error`/`field--invalid` present; `fetch('/admin/settings'` present. |
| `app/templates/editor.html` (owner link) | `{% if is_owner %}`-guarded `/admin/settings` link | VERIFIED | `grep` confirms the guard and link; `app/main.py::editor_page` now computes and passes `is_owner`. |
| `app/static/editor.css` (`.field-error`, `.field--invalid`) | Inline error styling | VERIFIED | Present, references `var(--red-on-ink)`. |
| `app/main.py` (`GET`/`POST /admin/settings`) | Routes gated by `require_owner`, two-pass validate-then-write | VERIFIED at the route-wiring level; FAILED at the data-integrity level (see gaps) | Both routes present, `Depends(require_owner)` on both, `validate_only` precedes `settings.set` in the POST handler body (confirmed by reading `app/main.py:443-481`). No raw SQL. |
| `tests/test_app_settings.py`, `tests/test_app_auth.py`, `tests/test_settings_template.py` | Integration/unit coverage | VERIFIED (exist, run, pass) | 52 tests across these four files + `test_settings.py` pass locally. None of these tests exercise browser-side JS number semantics or a GET→POST-unchanged round trip, which is exactly why CR-01/CR-02 survived to this point (confirmed independently in this verification, not merely restated from the review). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `app/main.py` GET/POST `/admin/settings` | `require_owner` | `Depends(require_owner)` | WIRED | Confirmed in both route decorators. |
| `app/main.py` POST `/admin/settings` | `settings.validate_only` then `settings.set` | two-pass validate-all-then-write-all | WIRED (validation pass), but data fed into pass 2 is fallback-resolved (see gap 2) | `validate_only` loop precedes the `set` loop; confirmed no `set` call inside the validation loop. |
| `app/main.py` GET `/admin/settings` | `settings.all_for_ui()` | server-render into `settings.html` | WIRED, but the payload embeds gap-1/gap-2 defects | `settings_page` passes `settings.all_for_ui()` as `groups` directly to the template context. |
| `settings.html::save()` | `/admin/settings` | `fetch POST application/json` | WIRED | `fetch('/admin/settings', {method: 'POST', ...})` confirmed; response branches on `{ok,message}` vs `{errors}`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|---------------------|--------|
| `settings.html` `groups`/`values` | `settings.all_for_ui()` | Real sqlite-backed `settings` table via `core/settings.py::get()` | Yes (real data) | FLOWING, but the resolved value for snowflake/role_list/fallback-derived fields is either precision-corrupted client-side (gap 1) or destructively re-persisted on save (gap 2) — the flow is real but not integrity-preserving for these two field classes. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `settings.all_for_ui()` snowflake value type | Direct Python call against a real tmp-DB store | `PHOTO_CHANNEL_ID` value is `<class 'int'> 1416329356426481717`, `tojson`-equivalent serialization is the bare literal `1416329356426481717` (no quotes) | FAIL — confirms CR-01 is live in the current codebase |
| GET→POST-unchanged preserves CONF-03 cascade | TestClient round-trip: seed `GALLERY_STAFF_ROLE_IDS=[111]`, GET groups, flatten to values, POST unchanged, then change `GALLERY_STAFF_ROLE_IDS=[222]`, re-check `REVIEWS_STAFF_ROLE_IDS` | POST returns 200 `{ok:true}`; after the gallery edit, `REVIEWS_STAFF_ROLE_IDS` remained `[111]` instead of cascading to `[222]` | FAIL — confirms CR-02 is live in the current codebase |
| `tests/test_app_settings.py tests/test_settings.py tests/test_settings_template.py tests/test_app_auth.py` | `pytest -q` | 52 passed | PASS (but does not cover the two failure modes above — the suite's fixtures always POST a hand-built single/dual-key body, never a full-form GET→POST round trip, and never execute JS) |
| Debt-marker scan (`TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`) on `app/main.py`, `app/deps.py`, `app/templates/settings.html`, `core/settings.py` | `grep -inE` | No matches (the only `placeholder` hits are legitimate HTML attributes / prose) | PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` conventional probes exist in this repository and none are declared in the Phase 2 plans/summaries. SKIPPED — no probes to run.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| PANEL-01 | 02-02-PLAN, 02-04-PLAN | `require_owner` gate, fails closed | SATISFIED | `app/deps.py::require_owner`, `tests/test_app_auth.py` (4 tests), `tests/test_app_settings.py` 403-path tests all pass. |
| PANEL-02 | 02-01-PLAN, 02-03-PLAN, 02-04-PLAN | GET renders typed, grouped, secret-free form | BLOCKED | Renders and is secret-free, but CR-01 (unfixed) corrupts snowflake/role-list display data — see gap 1. REQUIREMENTS.md's traceability table marks this "Complete", which this verification disputes on data-integrity grounds. |
| PANEL-03 | 02-01-PLAN, 02-04-PLAN | POST validates server-side, atomic write, secrets never written bad | BLOCKED | Two-pass validate-then-write is correctly wired and the mixed valid/invalid regression test passes, but CR-02 (unfixed) means an ordinary, fully-valid save silently and permanently corrupts the CONF-03 staff-role cascade — see gap 2. REQUIREMENTS.md marks this "Complete", which this verification disputes. |
| PANEL-04 | 02-04-PLAN | Saved change is read by the bot on next use | SATISFIED (narrow), at-risk (broader) | `settings.get` reflects a POSTed value immediately (tested). At-risk from gap 2 (an untouched field's resolved value gets baked in, so the bot may read a stale/incorrect value after a later gallery edit) and from WR-01 (missing `db.init_settings()` in `lifespan` risks a 500 on first save after a fresh deploy — confirmed absent via grep, not present in `app/main.py`). |

**Orphan check:** `.planning/REQUIREMENTS.md` maps exactly PANEL-01..04 to Phase 2; all four appear in at least one plan's `requirements:` frontmatter (02-01: PANEL-02/03; 02-02: PANEL-01; 02-03: PANEL-02; 02-04: PANEL-01/02/03/04). No orphaned requirements.

**Note:** `REQUIREMENTS.md`'s own traceability table (lines 89-92) currently marks PANEL-02/PANEL-03 "Complete" and PANEL-01/PANEL-04 "Pending" — inconsistent with both this verification's findings (PANEL-01 is solid; PANEL-02/03 have unresolved critical defects) and with 02-REVIEW.md. This table was not updated to reflect the code review's findings.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `core/settings.py` / `app/templates/settings.html` | settings.py:376, settings.html:22,47,53,109-114,138-140 | CR-01: bare-int snowflake/role_list serialization into a JS numeric context | BLOCKER | Confirmed live and unfixed; silently corrupts real Discord IDs on save (see gap 1). |
| `app/templates/settings.html` / `core/settings.py` | settings.html:138-140, settings.py:376 | CR-02: full-form POST bakes fallback-resolved values, breaking CONF-03 | BLOCKER | Confirmed live and unfixed via direct reproduction; breaks the staff-role cascade on ordinary use (see gap 2). |
| `app/main.py` | lifespan (~271-286) | WR-01: `db.init_settings()` missing from the `try` block that pre-creates `init_presence`/`init_view_counts` | WARNING | Fresh-deploy race: first POST 500s if the admin app starts before the bot has seeded the settings table. Confirmed absent via grep. |
| `app/main.py` | ~478-481 | WR-02: multi-key write loop is not transactional; a mid-loop failure leaves a partial write and an unhandled 500 | WARNING | Only manifests under a DB/disk error mid-write; the validation-failure path (the tested path) is correctly atomic. |
| `app/main.py`, `core/settings.py`, `settings.html` | main.py:471-476, settings.py multiple, settings.html:89 | WR-04: raw English-only `SettingRejected.reason` strings surfaced to the owner-facing field-error element, breaking the D-13 bilingual-copy house style | WARNING | Cosmetic/i18n inconsistency, not a functional blocker. |

*(WR-01/WR-02/WR-04 and the five Info-level findings are carried forward from `02-REVIEW.md`; independently confirmed present via direct file inspection during this verification, not merely restated from the review.)*

### Human Verification Required

None. Both critical defects (CR-01, CR-02) were reproduced deterministically via direct code execution (Python `all_for_ui()` output inspection for CR-01's numeric type/JSON literal; a live `TestClient` GET→POST-unchanged→re-check round trip for CR-02) — no browser or visual judgment call is needed to confirm they are real and unfixed.

### Gaps Summary

Both CRITICAL findings from `02-REVIEW.md` (CR-01 snowflake/role-list precision corruption; CR-02 staff-role fallback cascade destruction) were independently reproduced against the current HEAD (`a1fa945`) in this verification and remain unfixed — there is no commit after the review that touches `core/settings.py`'s value serialization, `settings.html`'s snowflake/role_list bindings, or the client's dirty-field tracking. Both bugs are triggered by entirely ordinary use of the panel (viewing a real Discord-ID-bearing field; clicking Save), not by an edge case, and both directly contradict the phase's stated Core Value ("without exposing secrets or letting a bad value break a cog") and Phase 1's CONF-03 requirement, which Phase 2 is required not to break. Because these are the exact mechanisms behind PANEL-02 ("typed fields") and PANEL-03 ("valid POST persists ... the bot never reads a bad value"), those two roadmap success criteria are marked FAILED. PANEL-01 (owner gate) is solid and fully verified. PANEL-04's literal, narrow truth (an immediate save is visible to `settings.get`) is verified, but its broader intent is undermined by CR-02's cascade-baking side effect.

These two gaps are grouped under a single root cause: **the panel always posts the complete, fallback-resolved snapshot of every setting on every save, and the store's rendering layer does not distinguish "raw stored value" from "value with type coercion applied for safe browser transport."** A closure plan addressing both (raw-value exposure in `all_for_ui()` + string-typed IDs, or dirty-key-only posting) would likely resolve both CR-01 and CR-02 together.

This looks like unfinished remediation rather than an intentional deviation — 02-REVIEW.md already prescribes concrete fixes for both. No override is suggested; these are exactly the kind of data-corrupting defects the escalation gate exists to catch before the next phase builds on top of this panel.

---

*Verified: 2026-07-21T18:00:00Z*
*Verifier: Claude (gsd-verifier)*
