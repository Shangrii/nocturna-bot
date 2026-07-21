---
phase: 02
slug: owner-settings-panel
status: verified
threats_open: 0
asvs_level: 1
created: 2026-07-21
---

# Phase 02 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|----------------|
| panel handler → settings store | The POST handler calls `validate_only`/`set` with owner-supplied keys+values | owner-edited tunable values |
| store serialization → HTTP response | `all_for_ui()` output is serialized into the rendered form | grouped tunables (must never carry a secret) |
| browser session → require_owner | The session cookie asserts an identity; `require_owner` must trust ONLY the signed session, never the body | discord_id |
| config → authorization | `DISCORD_USER_ID`'s `0` default doubles as "unset"; must never authorize | owner id |
| server render → browser | `groups` payload is serialized into the page via Jinja `tojson` | allowlisted 19 tunables |
| client JS → server | `save()` posts owner-edited values; server is the validation authority, not the JS | POST body |
| browser → GET/POST /admin/settings | untrusted request; `require_owner` gates identity, `settings.set` gates values | HTTP request |
| POST body → settings store | owner-supplied key/value pairs cross into the shared sqlite the bot reads | tunable values |
| error/success payload → browser | must never echo a secret or a structural value | JSON response |
| server render → browser JS (02-05) | `all_for_ui()` output is embedded via `tojson` into an Alpine `x-data` expression | snowflake/role_list values (precision-sensitive) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-02-01 | Tampering / EoP | `core/settings.py::validate_only(key,...)` | mitigate | `if key not in _SCHEMA: raise SettingRejected` is the first line of `validate_only` (settings.py:374-375), identical allowlist to `set()`. Pinned by `tests/test_settings.py::test_validate_only_rejects_unknown_key`. | closed |
| T-02-02 | Information Disclosure | `core/settings.py::all_for_ui()` metadata | mitigate | Entry dict built only from `_Setting` descriptor fields (key/type/value/hint/label/min/max/options); no `config.py` secret/structural constant referenced. Pinned by `tests/test_settings.py::test_all_for_ui_grouped` secret-absence assertions (BOT_TOKEN/GITHUB_PAT/JINXXY_API_KEY/SESSION_SECRET/DB_PATH). | closed |
| T-02-03 | EoP | `app/deps.py::require_owner` fail-open on `0` default | mitigate | `if not owner_id: raise HTTPException(403, ...)` (deps.py:89-90) runs BEFORE the identity comparison. Pinned by `tests/test_app_auth.py::test_require_owner_403_when_owner_id_unset`. | closed |
| T-02-04 | EoP | `str(session)` vs `int(config)` type confusion | mitigate | `str(discord_id) != str(owner_id)` (deps.py:91) normalizes both operands. Pinned by `tests/test_app_auth.py::test_require_owner_200_for_matching_owner` (int 555 config + str "555" session → admitted). | closed |
| T-02-05 | Spoofing / IDOR | identity from request body | mitigate | `require_owner` reads `request.session.get("discord_id")` only (deps.py:87); no `request.json()`/`request.query_params`/body access in the function body. | closed |
| T-02-06 | Information Disclosure | `settings.html` render | mitigate | Template iterates only the `groups` payload (`x-for="group in groups"` / `x-for="setting in group.settings"`, settings.html:35-92); `settingsApp()` flattens only `group.settings` (settings.html:108-114). Pinned by `tests/test_settings_template.py::test_settings_html_never_leaks_secrets`. | closed |
| T-02-07 | Tampering | client-side validation as authority | accept | Client `min`/`max`/`pattern` attributes (settings.html:45-58) are UX hints only; `app/main.py::save_settings` re-validates every field server-side via `settings.validate_only` before any write — no security decision is made in JS. See Accepted Risks Log. | closed |
| T-02-08 | XSS via `x-data` | `settings.html` hydrate | mitigate | Single-quoted `x-data='settingsApp({{ groups \| tojson }})'` idiom (settings.html:22), documented rationale in the template comment (lines 18-21) matching editor.html's established pattern. | closed |
| T-02-09 | Tampering | partial write on multi-field POST | mitigate | `app/main.py::save_settings` is a two-pass loop: `validate_only` for every key into `validated`/`errors` first (main.py:469-473); `settings.set` is only called in a second loop, and only when `errors` is empty (main.py:475-479). Pinned by `tests/test_app_settings.py::test_post_settings_mixed_valid_invalid_returns_422_and_writes_nothing`. | closed |
| T-02-10 | Tampering / EoP | arbitrary-key write | mitigate | All writes route through `settings.set`, which delegates to `validate_only`'s `_SCHEMA` allowlist check (settings.py:356, 374-376); no raw SQL (`INSERT`/`conn.execute`) in `app/main.py`'s new handlers (confirmed via grep, 0 matches). | closed |
| T-02-11 | Spoofing / IDOR | identity from request body | mitigate | `save_settings(request, ident: dict = Depends(require_owner))` — `ident` is session-sourced identity used only for the auth dependency; the POST body (`body.items()`, main.py:469) supplies only WHAT changes, never WHO asks. | closed |
| T-02-12 | Tampering (CSRF) | state-changing POST | accept | `SameSite=Lax` session cookie (`app/main.py:298`, confirmed by `tests/test_app_auth.py::test_session_middleware_configured_with_secure_flags`) + session-only identity — same existing accepted mitigation as `/editor/save`. No hand-rolled CSRF token. See Accepted Risks Log. | closed |
| T-02-13 | Information Disclosure | GET body / POST error payload | mitigate | `GET /admin/settings` renders only `settings.all_for_ui()` (main.py:439); POST error map carries only `SettingRejected.reason` (main.py:472-473), never a secret. Pinned by `tests/test_app_settings.py::test_get_settings_owner_renders_grouped_no_secret`. | closed |
| T-02-SC | Tampering (supply chain) | package installs | accept | Zero new packages this phase — `requirements.txt`/`pyproject.toml` untouched by any Phase-2 commit (git history confirms last touch was Phase 10/08/05). See Accepted Risks Log. | closed |
| T-02-05-01 | Tampering (Integrity) | snowflake/role_list serialization → `tojson` JS payload | mitigate | `all_for_ui()` coerces `snowflake` → `str(value)` and `role_list` → `", ".join(str(v) for v in value)` (settings.py:406-409) before assignment, so `tojson` emits quoted strings. Pinned by `tests/test_settings.py::test_all_for_ui_snowflake_is_string`, `test_all_for_ui_role_list_is_comma_joined_string`, `test_all_for_ui_no_precision_losing_literal`. | closed |
| T-02-05-02 | Tampering (Integrity) | fallback baking on unchanged save | mitigate | `_get_raw()` (settings.py:323-344) skips the `fallback_key` branch entirely and is the source `all_for_ui()` reads (settings.py:405); `get()` is untouched. Pinned by `tests/test_settings.py::test_all_for_ui_raw_value_bypasses_fallback` and integration test `tests/test_app_settings.py::test_post_settings_unchanged_save_preserves_staff_role_cascade`. | closed |
| T-02-05-03 | EoP | GET/POST `/admin/settings` | accept (unchanged) | Both routes remain gated by `Depends(require_owner)` (main.py:424, 444) — confirmed unchanged by this plan's diff scope (core/settings.py + tests only). Re-verified via `tests/test_app_settings.py::test_get_settings_non_owner_gets_403_no_data` / `test_post_settings_non_owner_gets_403_no_data`. | closed |
| T-02-05-04 | Tampering (Input) | POSTed setting values | accept (unchanged) | `validate_only` still validates every field before any write (main.py:471, two-pass atomicity intact); string IDs accepted by existing validators (`_validate_channel_id`, `_validate_role_id_list` both do `str(value).strip()`/`.split(",")`). No validator loosened. | closed |
| T-02-05-SC | Tampering (Supply chain) | pip/npm/cargo installs | n/a | This plan edited `core/settings.py` and two test files only — no packages installed. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|--------------|------|
| AR-02-01 | T-02-07 | Client-side `min`/`max`/`pattern` HTML attributes are UX affordances only; `app/main.py::save_settings` re-validates every submitted field server-side via `settings.validate_only` before any write is made, so a bypassed/forged client cannot write an invalid value. | 02-03-PLAN.md / 02-04-PLAN.md authors | 2026-07-21 |
| AR-02-02 | T-02-12 | State-changing POST `/admin/settings` has no hand-rolled CSRF token; CSRF is mitigated by the existing `SameSite=Lax` session cookie (app/main.py:298) plus session-only identity resolution (`require_owner` never trusts the body) — the same accepted mitigation already in place for `/editor/save`. Consistent with the project's "don't hand-roll CSRF" research finding. | 02-04-PLAN.md authors | 2026-07-21 |
| AR-02-03 | T-02-SC | Zero new packages installed in Phase 2 (plans 02-01 through 02-05) — `requirements.txt`/`pyproject.toml` are untouched since Phase 10/08/05; no supply-chain legitimacy audit is required for this phase. | 02-01/02-02/02-04-PLAN.md authors | 2026-07-21 |
| AR-02-04 | T-02-05-03 | GET/POST `/admin/settings` access control is inherited unchanged from 02-02/02-04's `require_owner` fail-closed gate; 02-05 (gap-closure) touched only `core/settings.py`'s serialization logic and tests, not the auth gate. | 02-05-PLAN.md authors | 2026-07-21 |
| AR-02-05 | T-02-05-04 | POSTed setting values remain gated by the unchanged `validate_only`-then-`set` two-pass atomicity from 02-04; 02-05 added string-accepting coercion at the serialization boundary only, without loosening any validator. | 02-05-PLAN.md authors | 2026-07-21 |
| AR-02-06 | T-02-05-SC | 02-05 (gap-closure) plan installed no packages — `core/settings.py` and two test files only. | 02-05-PLAN.md authors | 2026-07-21 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|----------------|--------|------|--------|
| 2026-07-21 | 19 | 19 | 0 | gsd-security-auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-21
