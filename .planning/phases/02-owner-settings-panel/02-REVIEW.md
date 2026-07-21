---
phase: 02-owner-settings-panel
reviewed: 2026-07-21T12:34:29Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - app/deps.py
  - app/main.py
  - app/static/editor.css
  - app/templates/editor.html
  - app/templates/settings.html
  - core/settings.py
  - tests/test_app_auth.py
  - tests/test_app_settings.py
  - tests/test_settings.py
  - tests/test_settings_template.py
findings:
  critical: 2
  warning: 4
  info: 5
  total: 11
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-07-21T12:34:29Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the owner settings panel implementation: the `require_owner` gate (`app/deps.py`), the `GET`/`POST /admin/settings` routes (`app/main.py`), the panel template (`app/templates/settings.html`), the sqlite-backed settings store (`core/settings.py`), the owner-link addition to `editor.html`, the panel CSS additions, and the four test files.

The auth boundary is solid: `require_owner` fails closed on the `0`/unset owner id, normalizes the str/int type mismatch, reads identity from the session only, and the `_SCHEMA` allowlist genuinely prevents secrets from reaching either the render or the write path. The two-pass validate-then-write POST correctly rejects mixed valid/invalid payloads without writing.

However, two data-corruption bugs survive the tests because the tests never exercise the browser-side hydration round-trip: (1) Discord snowflake IDs are serialized as JSON **numbers** into an Alpine `x-data` expression, where JavaScript's 53-bit float mantissa silently corrupts every 17-20-digit ID before it is displayed — and the corrupted ID validates and persists on Save; (2) the panel posts **all 19 keys** on every save, so the fallback-resolved staff-role lists (`REVIEWS/REMINDERS/JINXXY_STAFF_ROLE_IDS`) get baked into their own keys, permanently destroying the CONF-03 read-time cascade the store went to explicit lengths to preserve.

## Critical Issues

### CR-01: Snowflake and role IDs lose precision in JavaScript and the corrupted values are silently persisted

**File:** `core/settings.py:377` (value serialization in `all_for_ui`), `app/templates/settings.html:22,47,53,138-151`
**Issue:** `all_for_ui()` returns snowflake values as Python `int` (e.g. `PHOTO_CHANNEL_ID` default `1416329356426481717`) and role lists as `list[int]`. `settings.html` embeds this via `x-data='settingsApp({{ groups | tojson }})'`, which Alpine evaluates as a **JavaScript expression** — every integer literal becomes an IEEE-754 double. Discord snowflakes (17-20 digits, up to ~9.2e18) far exceed `Number.MAX_SAFE_INTEGER` (9007199254740992 ≈ 9.0e15), so `1416329356426481717` is silently rounded (spacing between representable doubles at 1.4e18 is 256). The corrupted number is what the owner sees in the input, and `serialize()` (`settings.html:138-140`) posts it back. Server-side, `_validate_channel_id` (`core/settings.py:43-56`) only checks `str(value).isdigit()` — the corrupted-but-still-numeric ID **validates and persists**. One innocent "Save settings" click with no edits at all rewrites every channel/forum/role ID in the store to a wrong value, and the bot then targets nonexistent channels/roles. `editor.html` already handles this class of bug by keeping `discordId` a string; the settings panel does not. The tests miss this because they only exercise the server round-trip (`tests/test_app_settings.py`) and the static render (`tests/test_settings_template.py`), never JS number semantics.
**Fix:** Serialize ID-typed values as strings in `all_for_ui()` — the validators already accept digit strings, so the POST round-trip needs no other change:
```python
value = get(descriptor.key)
if descriptor.type_tag == "snowflake":
    value = str(value)
elif descriptor.type_tag == "role_list":
    value = [str(v) for v in value]
entry = {"key": descriptor.key, "type": descriptor.type_tag, "value": value, ...}
```
For `role_list`, also have the template join to `"111, 222"` for the text input (or keep the string-list and join client-side). Add a test asserting `all_for_ui()` emits no bare `int` above 2**53 (or simply that snowflake `value` is a `str`).

### CR-02: Saving the panel bakes fallback-resolved staff-role lists into their own keys, permanently breaking the CONF-03 cascade

**File:** `app/templates/settings.html:109-114,138-151`, `core/settings.py:317-320,375`
**Issue:** `all_for_ui()` populates each setting's `value` via `get(key)`, which applies the empty-list → `GALLERY_STAFF_ROLE_IDS` fallback ("evaluated fresh every call, never baked in" — `core/settings.py:304-320`). The client then flattens **every** setting into `values` (`settings.html:109-114`) and `serialize()` posts the entire map on every save (`settings.html:138-140`). Concretely: gallery = `[111]`, reviews stored as `[]` (its seeded default) → the panel renders reviews as `[111]` → the owner changes an unrelated field (e.g. `JINXXY_POLL_HOURS`) and hits Save → `settings.set("REVIEWS_STAFF_ROLE_IDS", [111])` persists the *resolved* value. From that moment the reviews list no longer follows gallery edits — the read-time cascade the store explicitly documents (and `test_staff_role_fallback_to_gallery` pins) is silently destroyed by normal panel use. This is a logic conflict between D-04 ("post the whole form atomically") and CONF-03 ("never bake the fallback in") that the integration tests never hit because they post hand-built single-key bodies, not the template's full `values` map.
**Fix:** Stop round-tripping fallback-resolved values. Either (a) have `all_for_ui()` expose the *raw stored* value for editing (bypass the fallback when building the panel payload, optionally adding an `effective` field for display), or (b) have the client post only dirty keys (snapshot initial `values` and diff in `serialize()`). Option (a) is smaller and server-authoritative:
```python
# in all_for_ui(): raw stored value, no fallback resolution
"value": _get_raw(descriptor.key),   # like get() but skipping the fallback_key branch
```
Add an integration test: seed gallery roles, GET the panel payload, POST it back unchanged, assert `REVIEWS_STAFF_ROLE_IDS` is still stored empty / still cascades.

## Warnings

### WR-01: `POST /admin/settings` 500s if the admin app starts before the bot has ever created the settings table

**File:** `app/main.py:270-281,479`
**Issue:** The lifespan handler deliberately calls `db.init_presence()`/`db.init_view_counts()` "so /api/presence never 500s if the bot (which normally creates it) hasn't started yet" — but does **not** call `db.init_settings()`. `settings.get` fails soft to defaults, so GET works, but `settings.set` (`core/settings.py:334-338`) executes an `INSERT` with no table guard: on a fresh deploy where the admin app unit starts before `bot.py::main()` has run `seed_defaults()`, every save raises `sqlite3.OperationalError: no such table: settings` → unhandled 500. The lifespan's own comment establishes the standard this misses.
**Fix:** Add `db.init_settings()` to the existing `try` block in `lifespan` (it is `CREATE TABLE IF NOT EXISTS`, idempotent).

### WR-02: Multi-key write is not transactional — a mid-loop failure leaves a partial write and an unhandled 500

**File:** `app/main.py:478-481`, `core/settings.py:323-338`
**Issue:** The docstring sells the handler as "Atomic two-pass validate-then-write" (D-04), but atomicity only holds for *validation* failures. The second pass calls `settings.set(key, value)` once per key, and each call opens its own connection/implicit transaction. If write N fails mid-loop (locked DB, disk error), keys 1..N-1 are committed, keys N.. are not — exactly the mixed-outcome state D-04 forbids — and the exception propagates as an unhandled 500 with no error body the client understands. `test_post_settings_mixed_valid_invalid_returns_422_and_writes_nothing` only covers the validation half.
**Fix:** Perform all upserts in one connection/transaction, e.g. add `settings.set_many(validated: dict)` that validates (already done) and executes every upsert inside a single `with db._get_conn() as conn:` block, and wrap the call in `try/except sqlite3.Error` returning a 502/500 JSON error body.

### WR-03: Blocking sqlite I/O runs directly on the event loop in both settings handlers

**File:** `app/main.py:438-439,478-480`
**Issue:** Every other handler in this file routes blocking work through `run_in_threadpool` (`_fetch_current_entry`, `db.get_presence`, `db.increment_view`, …). `settings_page` calls `settings.all_for_ui()` inline — 19 sequential `SELECT`s (each opening a connection) plus `available_timezones()` (a filesystem scan of the tz database on first call) — and `save_settings` calls `settings.set` inline. Both are `async def`, so these synchronous DB/filesystem calls stall the event loop for every concurrent request (including the public `/api/presence` and `/api/views` endpoints served by the same process).
**Fix:** `groups = await run_in_threadpool(settings.all_for_ui)` and run the write loop via `await run_in_threadpool(...)` (combines naturally with the WR-02 `set_many` fix).

### WR-04: Per-field validation errors surface raw English-only developer strings, violating the D-13 bilingual copy convention

**File:** `app/main.py:471-476`, `core/settings.py:55,67,87,99-101,113,121,129,137`, `app/templates/settings.html:89`
**Issue:** The 422 `errors` map carries `SettingRejected.reason` verbatim, and `settings.html:89` renders it directly into the owner-facing `field-error` element. Reasons are English-only, developer-toned strings — `"must be a positive channel/forum ID"`, `"invalid role ID in list: '12a'"` (with Python `repr` artifacts), `"unknown setting key: 'X'"` — while every other user-facing string in this surface is a bilingual ES·EN pair (the file even defines `_SETTINGS_SAVED_COPY`/`_SETTINGS_ERROR_COPY` for exactly this house style). The store docstring says `reason` exists "so the HTTP layer can surface it without string-matching" — the HTTP layer was expected to translate, not pass through.
**Fix:** Map `reason`/type-tag to bilingual copy at the HTTP layer (or add a `type_tag`-keyed bilingual message table in `main.py`), falling back to the raw reason only for unmapped cases:
```python
errors[key] = _FIELD_ERROR_COPY.get(settings._SCHEMA[key].type_tag, exc.reason)
```

## Info

### IN-01: `_SETTINGS_ERROR_COPY` is defined but never referenced

**File:** `app/main.py:96-98`
**Issue:** Dead constant — the 422 path returns only `{"errors": ...}` and the client hardcodes its own bilingual toast (`settings.html:159`). The 02-04 summary acknowledges this as intentional "for symmetry", but until a consumer exists it is dead code that drifts from the client's duplicated literal.
**Fix:** Either include it in the 422 body (`{"errors": errors, "message": _SETTINGS_ERROR_COPY}`) and have the client prefer `data.message`, or delete it. The WR-04 fix is a natural place to put it to use.

### IN-02: `asset_v` cache-buster computation duplicated verbatim

**File:** `app/main.py:407-410,433-436`
**Issue:** The identical `try: int(os.path.getmtime(...)) except OSError: 0` block appears in both `editor_page` and `settings_page`.
**Fix:** Extract a module-level `_asset_version()` helper (also gives one place to memoize later).

### IN-03: Settings-panel labels are not associated with their inputs

**File:** `app/templates/settings.html:41-87`
**Issue:** `<label class="label" x-text="setting.label">` has no `for`, and the inputs have no `id` — clicking a label does nothing and screen readers announce unlabeled fields. `editor.html` uses `for`/`id` pairs for its core fields. Additionally, `pattern="\d{17,20}"` on the snowflake input (`settings.html:45`) is never enforced because saving goes through `fetch()`, not form submission — it is dead markup that can only mislead.
**Fix:** Bind `:for`/`:id` from `setting.key` (e.g. `:id="'f-' + setting.key"`), or wrap each input inside its `<label>`. Drop the inert `pattern`, or keep it purely as documentation with a comment.

### IN-04: `WEBSITE_BASE_URL` is now owner-editable but CORS captures it once at import

**File:** `app/main.py:305-310`, `core/settings.py:239-244`
**Issue:** `allow_origins=[config.WEBSITE_BASE_URL]` is evaluated when the module imports (via the `config.__getattr__` → `settings.get` shim), then frozen inside the middleware for the process lifetime. An owner who edits `WEBSITE_BASE_URL` in the panel changes read-at-use consumers (e.g. `editor_page`'s `website_base`) immediately, but the CORS allowlist — a security-relevant consumer — keeps the old origin until restart, with no hint in the panel that a restart is needed.
**Fix:** Add a `hint` to the `WEBSITE_BASE_URL` descriptor ("requiere reinicio para CORS · CORS requires restart"), or resolve the origin per-request via a custom `allow_origin_regex`/callable if live updates are desired.

### IN-05: The `0 = unset` sentinel for forum/encoding channels is undiscoverable in the panel

**File:** `core/settings.py:279-290`, `app/templates/settings.html:44-48`
**Issue:** `FORUM_CHANNEL_ID`/`ENCODING_CHANNEL_ID` use `_validate_channel_id_or_zero` (0 is a valid "unset" sentinel), but they render with the generic snowflake input whose placeholder (`123456789012345678`) and pattern imply a real 17-20-digit ID is required. Both descriptors have empty `hint`s, so the owner has no way to know `0` means "disabled" — and no way to know these two accept it while the other snowflake fields reject it.
**Fix:** Add `hint="0 = desactivado · 0 = unset"` to both descriptors (the template already renders `setting.hint`).

---

_Reviewed: 2026-07-21T12:34:29Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
