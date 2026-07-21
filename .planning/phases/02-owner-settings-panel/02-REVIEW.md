---
phase: 02-owner-settings-panel
reviewed: 2026-07-21T13:21:10Z
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
  critical: 0
  warning: 6
  info: 8
  total: 14
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-07-21T13:21:10Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Fresh adversarial review of the owner settings panel surface (routes, dependency gates, store, templates, CSS, tests) after gap-closure plan 02-05.

**Prior findings verified RESOLVED:**

- **CR-01 (snowflake precision loss in `all_for_ui`) — RESOLVED.** `core/settings.py:405-409` now serializes `snowflake` values to `str` and `role_list` values to a comma-joined `str` before they reach the `tojson` payload; no bare int > 2**53 can reach the browser. Pinned by `tests/test_settings.py::test_all_for_ui_snowflake_is_string`, `::test_all_for_ui_no_precision_losing_literal`, and the full server-side round trip `tests/test_app_settings.py::test_post_settings_unchanged_save_preserves_snowflake_precision` (asserts `settings.get("PHOTO_CHANNEL_ID") == 1416329356426481717` after an unmodified full-form save).
- **CR-02 (CONF-03 fallback baking on unchanged save) — RESOLVED.** `all_for_ui` now reads through the new `_get_raw` (`core/settings.py:323-344`), which skips the empty-list → `fallback_key` branch, so an unmodified save re-persists the raw empty list and the read-time cascade in `get()` (`core/settings.py:317-319`) stays live. Pinned by `tests/test_settings.py::test_all_for_ui_raw_value_bypasses_fallback` and `tests/test_app_settings.py::test_post_settings_unchanged_save_preserves_staff_role_cascade` (including the later gallery-only edit still cascading).

The security core is sound: `require_owner` fails closed on the `0`/unset owner id before the identity comparison, identity is session-only, all SQL is parameterized behind the `_SCHEMA` allowlist, no secret key can reach the panel payload, and all dynamic template values render via `x-text`/`tojson` (no XSS path found). Tests are meaningful and pin the load-bearing invariants.

Remaining issues are robustness/consistency defects: the admin app never creates the `settings` table it writes to (deployment-order 500), the multi-key write is not transactional under DB failure (contradicting the documented D-04 atomicity), synchronous sqlite I/O runs on the event loop, the CORS origin bakes a panel-tunable value at import time, the URL validator accepts values that silently break that same CORS origin, and `/admin/settings` skips the Pitfall-2 live role re-check every other protected route performs.

## Warnings

### WR-01: Admin app writes to the `settings` table but never ensures it exists

**File:** `app/main.py:270-281` (lifespan), `core/settings.py:357-362`
**Issue:** The lifespan handler calls `db.init_presence()` and `db.init_view_counts()` precisely so those endpoints "never 500 if the bot (which normally creates it) hasn't started yet" — but it does NOT call `db.init_settings()`. The `settings` table is only created by `seed_defaults()`, whose single call site is `bot.py::main()` in the *other* process. If the admin app starts against a DB the bot has never initialized (fresh deploy, DB file moved/reset), every `POST /admin/settings` raises `sqlite3.OperationalError: no such table: settings` inside `settings.set` → unhandled 500 for the entire save surface, while GET silently renders defaults. The exact deployment-order hazard the lifespan comment already names for presence applies verbatim here.
**Fix:**
```python
    try:
        db.init_presence()
        db.init_view_counts()
        db.init_settings()  # the settings POST writes here; don't depend on bot startup order
    except Exception:
        log.exception("no pude inicializar las tablas de presencia/vistas/ajustes")
```

### WR-02: Multi-key save is not atomic under DB failure, and sqlite errors surface as bare 500s

**File:** `app/main.py:478-479`, `core/settings.py:347-362`
**Issue:** The two-pass design (D-04) only guarantees atomicity against *validation* failures. The second pass calls `settings.set(key, value)` in a Python loop where each call opens its own connection and commits its own transaction. If a write fails mid-loop (locked DB past the busy timeout, disk full, missing table per WR-01), the earlier keys are already committed, the later ones are not, and the exception propagates as an unhandled 500 with no bilingual error copy — a partial write that directly contradicts the handler's own docstring ("a mixed valid/invalid POST must write nothing"). Every other commit path in this file (`/editor/save`, uploads) catches its failure mode and returns a copy-bearing 502.
**Fix:** Add a single-transaction batch writer and use it from the handler:
```python
# core/settings.py
def set_many(values: dict) -> None:
    """Validate every key, then persist ALL of them in one transaction (all-or-nothing)."""
    validated = {k: validate_only(k, v) for k, v in values.items()}
    with db._get_conn() as conn:  # one transaction: any failure rolls back every key
        for key, val in validated.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(val)))
```
```python
# app/main.py save_settings — replace the write loop
    try:
        await run_in_threadpool(settings.set_many, validated)
    except Exception:
        log.exception("settings save failed")
        return JSONResponse(status_code=502, content={"error": _SETTINGS_ERROR_COPY})
```

### WR-03: Synchronous sqlite I/O on the event loop in the settings handlers

**File:** `app/main.py:439` (`settings.all_for_ui()`), `app/main.py:471-479` (`settings.validate_only` / `settings.set` loop)
**Issue:** Every other DB touch in this file goes through `run_in_threadpool` (`db.get_presence`, `db.increment_view`, `github_publish._fetch_json`). The settings handlers call the sqlite-backed store directly inside `async def`. `settings.set` is a write: under WAL, concurrent writers still serialize, and Python's sqlite default busy timeout is 5 s — a concurrent bot-process write can stall the *entire* event loop (including the public `/api/presence` and `/api/views` endpoints) for up to 5 s per key. `all_for_ui` additionally calls `available_timezones()`, which scans the tzdata directory on disk. Not flagged as a performance nit — this is a robustness inconsistency with the file's own established discipline.
**Fix:** `groups = await run_in_threadpool(settings.all_for_ui)` in `settings_page`; route the write batch through `run_in_threadpool` (folds into the WR-02 fix above). `validate_only` is pure and may stay inline.

### WR-04: CORS origin bakes the panel-tunable `WEBSITE_BASE_URL` at import time

**File:** `app/main.py:305-310`
**Issue:** `WEBSITE_BASE_URL` is one of the 19 safe tunables — `config.__getattr__` routes it to `settings.get` read-at-use (CONF-01), and the panel offers it for editing. But `allow_origins=[config.WEBSITE_BASE_URL]` is evaluated exactly once, at module import, and frozen into `CORSMiddleware`. After the owner edits the base URL in the panel, the public site at the new origin silently loses CORS access to `/api/presence` and `/api/views` until the admin app process is restarted — a read-at-use violation with no feedback anywhere (fetches just fail in visitors' browsers). The panel presents the value as fully live, which is untrue for this consumer.
**Fix:** Minimum viable: declare the restart requirement in the schema so the panel says so —
```python
    "WEBSITE_BASE_URL": _Setting(
        "WEBSITE_BASE_URL", "jinxxy", "url",
        os.getenv("WEBSITE_BASE_URL", "https://nocturna-avatars.site"),
        _validate_url,
        hint="changing this requires an editor-app restart to update CORS",
        label="URL base del sitio web · Website base URL",
    ),
```
Better: replace the static list with a small custom middleware that compares the request `Origin` against `config.WEBSITE_BASE_URL` per request.

### WR-05: `_validate_url` accepts degenerate URLs that silently break their consumers

**File:** `core/settings.py:125-130`
**Issue:** The validator only checks the string prefix. `"https://"` (no host) passes; so does `"https://nocturna-avatars.site/"` (trailing slash). Both are consumed as *origins*: the CORS `allow_origins` entry (WR-04) is matched byte-for-byte against the browser's `Origin` header, which never carries a trailing slash or a path — so a saved value with a trailing slash breaks presence/views CORS on the next restart with zero validation feedback, and `"https://"` breaks it outright. `config.py`'s own docs require `WEBSITE_BASE_URL` "sin barra final"; the store's validation gate (STORE-03's whole purpose) does not enforce it.
**Fix:**
```python
from urllib.parse import urlsplit

def _validate_url(value) -> str:
    """A non-empty http:// or https:// URL with a host; trailing slash stripped."""
    s = str(value).strip().rstrip("/")
    parts = urlsplit(s)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise SettingRejected("must be an http:// or https:// URL with a host")
    return s
```

### WR-06: `/admin/settings` skips the live role re-check; `require_owner`'s stated precondition is false

**File:** `app/deps.py:69-94`, `app/main.py:423-424,443-444`
**Issue:** The `require_owner` docstring justifies its 403-never-401 policy with "by the time a caller reaches this dependency they are already an authenticated editor" — but both `/admin/settings` routes depend on `require_owner` *alone*, so no `require_editor` (and therefore no `has_editor_role`) check ever runs on this surface. Two consequences: (1) the documented precondition is untrue for the only routes that use this dependency; (2) the Pitfall-2 invariant this codebase pins hard everywhere else ("an offboarded editor's still-valid cookie can no longer act, re-proved on every call") does not hold for the highest-privilege surface — an owner whose editor role is revoked keeps full settings read/write for up to the 6 h cookie TTL. The blast radius is small (only the single configured `DISCORD_USER_ID` can ever pass, and the session was originally minted through the role-gated OAuth callback), but the inconsistency is real and undocumented.
**Fix:** Re-prove the role inside `require_owner` before the identity comparison, mirroring `require_editor`:
```python
async def require_owner(request: Request) -> dict:
    ident = await require_editor(request)   # 401/403 + live role re-check (Pitfall 2)
    owner_id = config.DISCORD_USER_ID
    if not owner_id or str(ident["discord_id"]) != str(owner_id):
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    return {"discord_id": ident["discord_id"]}
```
(If ID-based-not-role-based owner access is the intended D-10 semantics, instead delete the false docstring claim and record the exemption explicitly.)

## Info

### IN-01: `get()` and `_get_raw()` duplicate the entire DB-read block

**File:** `core/settings.py:295-320` vs `core/settings.py:323-344`
**Issue:** The try/select/`json.loads`/fallback-to-default block is copy-pasted between the two functions; only the log prefix differs. Divergence risk on the next store change.
**Fix:** `get()` should be `value = _get_raw(key)` followed by the CONF-03 fallback branch.

### IN-02: `get()`/`_get_raw()` raise a bare `KeyError` on unknown keys despite "NEVER raises (STORE-04)"

**File:** `core/settings.py:307`, `core/settings.py:335`
**Issue:** `_SCHEMA[key]` sits outside the try block, so an unknown key raises `KeyError`, contradicting the docstring's never-raises contract. Currently unreachable in practice (all callers use literal keys and `config.__getattr__` allowlists via `_SAFE_TUNABLE_KEYS`), but the contract and the code disagree.
**Fix:** Either raise `SettingRejected(f"unknown setting key: {key!r}")` explicitly (documented), or scope the docstring's guarantee to schema keys.

### IN-03: `_make_int_range` silently truncates floats and accepts bools

**File:** `core/settings.py:92-104`
**Issue:** `int(6.9)` → 6 (a JSON float from the panel is silently truncated and saved as a different number than submitted), while the string `"6.9"` is rejected — inconsistent strictness. `int(True)` → 1 also validates. Low impact (the panel's number input mostly sends ints).
**Fix:** Reject non-integral input: `if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()): raise SettingRejected(...)`.

### IN-04: Per-field validation errors are English-only, breaking the D-13 bilingual house style

**File:** `app/templates/settings.html:89`, `core/settings.py` validators (e.g. lines 55, 101, 113)
**Issue:** `SettingRejected.reason` strings ("must be between 1 and 168 (got 0)") are rendered verbatim as the inline field error. Every other user-facing string in this surface is the ES·EN pair; the field errors are the only monolingual copy.
**Fix:** Either bilingual reason strings in the validators, or a client-side reason→copy map in `settingsApp` with the raw reason as fallback.

### IN-05: `pattern="\d{17,20}"` on snowflake inputs is dead markup that would reject valid values if enforced

**File:** `app/templates/settings.html:45`
**Issue:** The save path is a `fetch()` from a button click — there is no form submission, so the HTML `pattern` constraint never runs (cosmetic). Worse, `FORUM_CHANNEL_ID`/`ENCODING_CHANNEL_ID` legitimately hold the `"0"` unset sentinel and share this input; if the pattern ever became enforced (e.g. the panel is wrapped in a `<form>`), the valid `"0"` would fail it. Server-side validators are also deliberately lenient on ID width, which this pattern contradicts.
**Fix:** Drop the `pattern` attribute (keep `inputmode="numeric"`), or widen it to `\d+`.

### IN-06: `_fetch_current_entry` annotated `-> dict` but returns `None` on a miss

**File:** `app/main.py:232-242`
**Issue:** `next((...), None)` can return `None`; every caller correctly checks for it, but the annotation lies.
**Fix:** Annotate `-> dict | None`.

### IN-07: `editor_page` re-implements `require_owner`'s fail-closed owner check inline

**File:** `app/main.py:413-415`
**Issue:** The `is_owner` computation duplicates the `0`/unset guard + `str()` comparison from `app/deps.py:89-91`. If the owner-identification rule ever changes (e.g. WR-06's fix), the settings-link visibility and the actual gate can drift apart.
**Fix:** Extract a shared `is_owner(discord_id) -> bool` helper in `app/deps.py` and use it in both places.

### IN-08: `JINXXY_POLL_HOURS` band contradicts config.py's documented D-03 band

**File:** `core/settings.py:219-225` (schema: 1–168) vs `config.py` comment ("banda 6–12h, D-03")
**Issue:** The schema, panel `min`/`max`, and tests all pin 1–168, while config.py's comment claims the D-03 decision was a 6–12 h band. One of the two is stale; if D-03 really mandates 6–12, the panel currently lets the owner set a 1 h poll cadence against the Jinxxy API.
**Fix:** Reconcile against the D-03 decision record — either update the config.py comment or tighten to `_make_int_range(6, 12)` + matching schema `min`/`max`.

---

_Reviewed: 2026-07-21T13:21:10Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
