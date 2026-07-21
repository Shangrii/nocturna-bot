# Phase 2: Owner Settings Panel - Research

**Researched:** 2026-07-21
**Domain:** FastAPI admin-app extension (owner-gated settings CRUD form), Alpine.js JSON save flow, Jinja2 server-render + hydrate
**Confidence:** HIGH

## Summary

This phase adds two routes (`GET`/`POST /admin/settings`) and one new dependency
(`require_owner`) to an **existing, already-audited FastAPI admin app**
(`app/main.py`, `app/deps.py`, `app/auth.py`). Phase 1 already built the entire data
layer this phase renders and writes through — `core/settings.py::get/set/all_for_ui` —
so there is no new persistence, no new auth flow, and no new front-end library to
introduce. The correct approach is almost entirely **pattern-mirroring**: copy
`require_editor` → `require_owner` (narrower identity check, same session-only /
fail-closed discipline), copy `editor_page` → the settings GET handler (server-render
into Jinja2, Alpine hydrates), and copy `/editor/save` → the settings POST handler
(`fetch()` + `Accept: application/json`, JSON error body, same exception-handler-driven
401/403 HTML fallback for navigation).

The one genuinely new piece of engineering is the **atomic multi-error validation**
(D-04/D-05): `settings.set` raises on the *first* bad field, so the POST handler must
validate every field independently (reusing the schema's per-key `validate` callables,
not `set` itself, for the dry-run pass) before calling `set` on any key. The other
substantive new piece is the **additive `all_for_ui()` metadata extension** (D-09) to
carry `int_range` bounds, timezone options, and a human label — needed so the panel
does not duplicate validation logic that already lives in the schema.

No new third-party packages are required. `zoneinfo` (stdlib) + `tzdata` (already a
pinned dependency from Phase 1, required on Windows/some minimal Linux images since the
stdlib module has no bundled IANA data of its own) covers the D-06 timezone `<select>`.

**Primary recommendation:** Extend the existing admin app in place — new routes in
`app/main.py`, new dependency in `app/deps.py`, new template `app/templates/settings.html`
mirroring `editor.html`'s Alpine/JSON idiom — and extend `core/settings.py::all_for_ui()`
additively. Do not introduce a new framework, ORM, or validation library.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Owner identity check (`require_owner`) | API / Backend | — | Session-derived server-side gate; mirrors `require_editor` (D-08 IDOR discipline — identity never from body/query) |
| Render current tunables grouped by feature | API / Backend (SSR) | Browser (Alpine hydrate) | `GET /admin/settings` renders Jinja2 server-side from `settings.all_for_ui()`, same as `editor_page` → `editor.html` |
| Field-level client interactivity (inline errors, banners, timezone `<select>` state) | Browser / Client | — | Alpine.js scope hydrated from the server-rendered initial data — no server round-trip needed for local UI state |
| Server-side validation gate | API / Backend | — | `settings.set`'s per-type validators are the ONLY authority; the panel must never re-implement or loosen this in JS (client-side hints are UX only, not security) |
| Persistence (settings table) | Database / Storage | — | Existing `settings` table (Phase 1); this phase never touches schema, only reads/writes via `core/settings.py` |
| Config propagation to the bot process | Database / Storage (shared sqlite) | — | Read-at-use via `settings.get` at existing Phase-1-migrated call sites — no new IPC, no bot-side code change in this phase |
| Owner-only link visibility on dashboard | Frontend Server (SSR) | — | `editor_page`'s Jinja2 context gains `is_owner`; `editor.html` conditionally renders the link server-side |

## User Constraints (from CONTEXT.md)

<user_constraints>

### Locked Decisions

- **D-01:** The panel uses **Alpine.js + `fetch()`/JSON**, mirroring the existing editor
  surface (`app/templates/editor.html`, `app/static/alpine.min.js`) — NOT the classic
  server-rendered POST from the design spec. Chosen for consistency with the current app's
  interaction feel. This intentionally supersedes the design spec's "POST re-renders the
  whole page" wording; the outcome (validate → write → feedback) is unchanged.
- **D-02:** `GET /admin/settings` renders the **current values server-side** into the Jinja2
  template (values from `settings.all_for_ui()`); Alpine then hydrates and handles save via
  `fetch()`. Same shape as `editor_page` → `editor.html`.
- **D-03:** `POST /admin/settings` accepts a **JSON payload of all fields** and returns JSON:
  `{ok, message}` on success or `{errors: {KEY: reason}}` on failure. The Alpine client shows
  an inline banner and per-field errors. (Follows the editor's `fetch` + `Accept: application/json`
  convention; the existing `_auth_html_or_json` handler already returns JSON for non-navigation.)
- **D-04:** **Atomic all-or-nothing save.** The `POST` handler validates **every** submitted
  field first, collecting all failures; if ANY field is invalid it **writes nothing** and
  returns all errors at once (keyed by setting). Only when every field passes does it persist.
  This is the strict reading of PANEL-03 ("rejected before any write, so the bot never reads a
  bad value") and lets the owner see every problem in a single pass.
- **D-05:** Because `settings.set` raises `SettingRejected` on the **first** bad value, the
  handler must **not** rely on it for multi-error collection — validate each field independently
  (catch `SettingRejected` per field to build the error map), then call `settings.set` for all
  fields only after the whole payload is clean. (Exact mechanism — reuse the schema validators
  vs. per-field try/`set` in a dry-run — is planner discretion; the contract is: no partial writes.)
- **D-06:** **Timezone** (`REMINDERS_TZ`) renders as a `<select>` populated from
  `zoneinfo.available_timezones()` (sorted), current value pre-selected. Round-trips through the
  same `_validate_timezone` gate.
- **D-07:** **Role-ID lists** (`*_STAFF_ROLE_IDS`) render as a single **comma-separated text
  input** (e.g. `123, 456`). Matches how `config.py` parses these today and what
  `_validate_role_id_list` already accepts. Repeatable rows were considered and rejected as
  over-built for v1.
- **D-08:** Field types to render come from the 7 `type_tag`s actually present in the schema:
  `snowflake`, `role_list`, `int_range`, `timezone`, `free_string`, `url`, `lang`. **Note:**
  the current 19 tunables include **no boolean/enum toggles** despite the spec mentioning
  checkboxes — no checkbox rendering is needed for v1. `WHISPER_MODEL`/`OLLAMA_MODEL` are free
  strings with a host-availability hint (already in the schema `hint`).
- **D-09:** **Extend `core/settings.py::all_for_ui()`** to surface structured render metadata
  so the panel is not forced to duplicate validation bounds. Needed extras: `int_range` `min`/`max`
  (currently baked inside the `_make_int_range` closures — must be exposed as data on the
  `_Setting` descriptor), the timezone option source, and a human `label` per setting. This is an
  **additive** change; `get`/`set`/`seed_defaults` contracts are unchanged. **Phase-1 tests for
  `all_for_ui()` (`tests/test_settings.py`) must be updated** to assert the new keys. Keeping the
  schema as the single source of truth avoids drift between the validator ranges and what the form shows.
- **D-10:** **`require_owner` mirrors `require_editor`** (`app/deps.py`) but checks
  `session.discord_id == config.DISCORD_USER_ID`, returning 403 otherwise. It **fails closed**
  when `DISCORD_USER_ID` is unset/`0` (PANEL-01). Identity comes from the **session only**,
  never the request body (same D-08 IDOR discipline as `require_editor`).
- **D-11:** **The owner authenticates through the existing Discord OAuth flow.** Confirmed
  assumption: the owner also holds the **editor role**, so `login` (which 403s non-editors in
  `app/auth.py`) admits them and establishes a session; `require_owner` then narrows to the owner.
  The login gate is **not** modified. (If this ever ceases to be true, making owner login
  independent of the editor role is the fallback — see Deferred.)
- **D-12:** Add an **owner-only `⚙ Ajustes / Settings` link** on the editor dashboard
  (`app/templates/editor.html`), rendered only when the session is the owner
  (pass an `is_owner` flag into the `editor_page` template context). The `/admin/settings`
  route stays gated by `require_owner` regardless of the link's visibility.
- **D-13:** Panel labels, hints, banners, and error messages are **bilingual ES–EN**, matching
  the house style used throughout the app (e.g. `_PUBLISH_SUCCESS_COPY`, `_FORBIDDEN_COPY`).

### Claude's Discretion

- Exact route/template file names and Jinja2 structure for the settings page (mirror
  `editor.html` conventions incl. the `?v=<mtime>` CSS cache-buster).
- The precise multi-error collection mechanism in `POST` (D-05) as long as no partial write occurs.
- The internal shape of the `all_for_ui()` metadata extension (D-09) — dataclass fields vs.
  computed dict — provided the schema remains the single source of truth.
- Whether `POST` writes only changed fields or all fields (upsert is idempotent; either is fine
  given the atomic validation in D-04).
- Bilingual copy wording.

### Deferred Ideas (OUT OF SCOPE)

- **Guild-populated channel/role dropdowns** (fetch names via the bot token) → v2 (POLISH-01);
  v1 stays on validated ID inputs.
- **Making owner login independent of the editor role** — only if the owner ever stops holding
  the editor role (D-11 fallback). Not built now.
- Editing secrets/structural values, ops console/monitoring, multi-admin, live interval hot-swap
  → out of scope permanently per spec/REQUIREMENTS.md.

</user_constraints>

## Phase Requirements

<phase_requirements>

| ID | Description | Research Support |
|----|-------------|------------------|
| PANEL-01 | `require_owner` dependency gates the panel to `session.discord_id == config.DISCORD_USER_ID`, 403 otherwise, fails closed when `DISCORD_USER_ID` unset | See "Don't Hand-Roll" (owner gate) + Code Examples (`require_owner` pattern mirroring `require_editor`); Pitfall 1 (the `0`-default trap) |
| PANEL-02 | `GET /admin/settings` renders a form grouped by feature from `settings.all_for_ui()`, each field typed, secrets never appear | See Architecture Patterns (server-render + Alpine hydrate), Code Examples (`GET` handler + template loop), D-09 metadata extension design |
| PANEL-03 | `POST /admin/settings` validates every field server-side via `settings.set`, writes the table, re-renders with success/error banner; invalid value rejected before any write | See Pitfall 2 (partial-write trap) + Code Examples (atomic dry-run-then-commit pattern) |
| PANEL-04 | A saved change is read by the bot on its next relevant use; loop-interval changes apply next cycle/restart | Already satisfied by Phase 1's read-at-use migration (`config.py.__getattr__` → `settings.get`) — this phase requires NO bot-side code, only confirms via existing behavior; see "State of the Art" row |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` exists in this repository. No project-level directive file to enforce beyond
what is captured in `.planning/` and the codebase's own established patterns (which this
research treats as binding conventions — see Architecture Patterns / Don't Hand-Roll).

No `.claude/skills/` or `.agents/skills/` directory exists either — no project skills to load.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.139.0 (confirmed installed via `pip show fastapi`) [VERIFIED: local environment] | Route handlers, `Depends()` DI for `require_owner` | Already the app's framework (`app/main.py`); no alternative considered |
| Jinja2Templates (via `fastapi.templating`) | bundled with FastAPI/Starlette | Server-render the settings form | Already used for `editor.html`/`login.html` — same `templates.TemplateResponse(request, ...)` call shape |
| Starlette `SessionMiddleware` | bundled with FastAPI | Session cookie carrying `discord_id` | Already configured in `app/main.py` (`https_only=True`, `same_site="lax"`, 6h TTL) — `require_owner` reads from this, no new middleware |
| Alpine.js | 3.15.12 (vendored, `app/static/alpine.min.js`) [VERIFIED: codebase] | Client-side hydrate + `fetch()` save, inline field errors | Already vendored (not CDN) per house policy; D-01 locks this choice for the new page too |
| `zoneinfo` (stdlib) + `tzdata` 2025.2 | stdlib (Python 3.9+) + `tzdata>=2025.2` pinned in `requirements.txt` [VERIFIED: requirements.txt:24] | `available_timezones()` for the D-06 `<select>`, and the existing `_validate_timezone` gate | Already a Phase-1 dependency (`_validate_timezone` uses `ZoneInfo`); `tzdata` is required because the stdlib module ships no bundled IANA data on some platforms (confirmed present via `pip show tzdata` in the project's conda env, 599 zones resolve including `America/Mexico_City`) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `core/settings.py` (in-repo, Phase 1) | n/a | `get`/`set`/`all_for_ui`/`SettingRejected` — the entire data + validation layer | Always — this phase is a thin HTTP/UI layer over it, never bypasses it |
| `core/db.py::_get_conn` (in-repo, Phase 1) | n/a | WAL-mode sqlite connection shared with the bot process | Indirectly, only through `core.settings` — this phase never opens its own connection |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Alpine.js + fetch/JSON (D-01, locked) | Classic full-page `POST` + re-render (the design spec's original wording) | Simpler server code (no client JS), but breaks visual/interaction consistency with `editor.html`; CONTEXT.md explicitly supersedes the spec here — not to be reconsidered |
| Per-field validate-then-`set` dry run (D-05 discretion option A) | A `settings.validate_only(key, value)` helper added to `core/settings.py` returning `(ok, reason)` without writing (option B) | Option A (call the private `_SCHEMA[key].validate` directly) needs no `core/settings.py` API surface change beyond D-09; Option B is slightly cleaner encapsulation but touches the already-completed Phase-1 module's public contract. Either satisfies D-04/D-05; recommend Option A to minimize touching Phase-1's tested public API — the `_Setting.validate` callable is already exposed to the panel via the `all_for_ui()` extension shape (planner's call which fields of `_Setting` become public) |
| `zoneinfo.available_timezones()` sorted client-visible list | A curated shortlist of common zones | The design spec and D-06 explicitly say full list — do not curate; `available_timezones()` is the correct stdlib call (confirmed returns 599 zones locally, including the current default `America/Mexico_City`) |

**Installation:**
No new packages. Nothing to `pip install` for this phase — every dependency above is already
present in `requirements.txt` / vendored in `app/static/`.

**Version verification:** `pip show fastapi` confirms 0.139.0 installed; `pip show tzdata`
confirms 2025.2 installed; both already pinned from prior phases. No registry lookups needed
since no new third-party package is introduced.

## Package Legitimacy Audit

**Not applicable — this phase installs zero new external packages.** Every library used
(FastAPI, Starlette/Jinja2, Alpine.js, `zoneinfo`/`tzdata`) is already installed and pinned
from Phase 1 or the pre-existing editor admin app. The Package Legitimacy Gate protocol is
skipped per its own trigger condition ("whenever this phase installs external packages").

**Packages removed due to slopcheck [SLOP] verdict:** none (no packages evaluated — none introduced)
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Owner's browser
   |
   | 1. GET /admin/settings  (cookie: session)
   v
require_owner (app/deps.py)          -- 403 fail-closed if DISCORD_USER_ID==0 or mismatch
   | (identity ok)
   v
GET handler (app/main.py)
   |-- settings.all_for_ui()  -->  core/settings.py  -->  sqlite `settings` table (WAL)
   |                                                       (shared with bot process)
   v
Jinja2Templates.TemplateResponse("settings.html", {groups, is_owner, asset_v})
   |
   v
Browser renders HTML; Alpine hydrates x-data='settingsApp({{ groups | tojson }})'
   |
   | 2. Owner edits fields locally (no network yet)
   | 3. Owner clicks Save -> fetch('/admin/settings', {method:'POST', json: allFields})
   v
POST handler (app/main.py)
   |-- for each submitted key: schema.validate(key, value) [dry run, no write]
   |     |-- ANY SettingRejected -> collect {key: reason}, do NOT call settings.set for any key
   |     +-- all valid -> settings.set(key, value) for every key  --> sqlite `settings` table
   v
JSON response {ok:true, message} or {errors:{KEY:reason}}  -- Accept: application/json
   |
   v
Alpine shows success banner OR inline per-field errors (no page reload)

                                    ... time passes ...

Bot process (separate systemd unit, same sqlite file)
   |
   | 4. On next relevant use (reaction gate / poll cycle / reminder tick):
   |    config.<SAFE_TUNABLE> --> config.__getattr__ --> settings.get(key)
   v
   Reads the freshly-saved value from the same `settings` table (WAL mode: no lock contention
   with the panel's writes). Loop-INTERVAL changes apply on the loop's next tick/restart —
   no live hot-swap is built (out of scope, PANEL-04 accepted nuance).
```

### Recommended Project Structure

```
app/
├── main.py            # + GET/POST /admin/settings routes, + is_owner in editor_page context
├── deps.py            # + require_owner (mirrors require_editor)
├── templates/
│   ├── editor.html     # + owner-only ⚙ link (is_owner flag, D-12)
│   └── settings.html   # NEW — mirrors editor.html's <head>/topbar/Alpine-hydrate shape
├── static/
│   └── editor.css      # extend (or a small settings-specific stylesheet) — reuse .field/.label/.btn classes already defined for editor.html
core/
└── settings.py         # additive: all_for_ui() gains min/max/label/tz-options; no get/set/seed_defaults contract change
tests/
├── test_settings.py     # extend: assert new all_for_ui() metadata keys
└── test_app_settings.py # NEW — mirrors tests/test_app_auth.py + tests/test_app_editor.py patterns
```

### Pattern 1: `require_owner` — narrow `require_editor`'s shape, don't duplicate its role-check machinery

**What:** A tiny FastAPI dependency reading `request.session.get("discord_id")`, comparing
directly to `config.DISCORD_USER_ID` (an `int`), and raising 403 (never 401 — the owner is
already authenticated as an editor by the time they'd hit this route; treat "authenticated
but not the owner" as strictly 403, matching PANEL-01's exact wording "gets 403", not 401).

**When to use:** Every `/admin/settings` route (both GET and POST).

**Example:**
```python
# Source: pattern mirrors app/deps.py::require_editor (existing, audited code)
from fastapi import HTTPException, Request

import config

_OWNER_FORBIDDEN_COPY = (
    "Solo el propietario puede acceder a esta página. — "
    "Only the owner can access this page."
)


async def require_owner(request: Request) -> dict:
    """Return the session identity iff it is the configured owner, else 403.

    Fails CLOSED when DISCORD_USER_ID is unset (the 0 default): `0 == 0` would
    otherwise "authorize" an unauthenticated/misconfigured session, so 0 is an
    explicit reject regardless of session content (PANEL-01).
    """
    discord_id = request.session.get("discord_id")
    owner_id = config.DISCORD_USER_ID
    if not owner_id or not discord_id or str(discord_id) != str(owner_id):
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    return {"discord_id": discord_id}
```

Note the `str(discord_id) != str(owner_id)` comparison — `config.DISCORD_USER_ID` is an
`int` (`int(os.getenv("DISCORD_USER_ID", "0"))`) while `session["discord_id"]` is stored as
a `str` (set in `auth.py::callback` as `str(user["id"])`). Compare as strings (or cast both
to int) to avoid a type-mismatch false-negative; either is fine as long as the `0`/`""`
sentinel case is checked BEFORE the comparison (not relying on `0 == "0"` being `False` to
accidentally save you — be explicit).

### Pattern 2: Server-render + Alpine hydrate for `GET /admin/settings` (mirrors `editor_page`)

**What:** The GET handler builds the full grouped-settings payload server-side and embeds it
as JSON into the Alpine `x-data` attribute (single-quoted, per the existing `editor.html`
comment explaining why: `entry | tojson` emits double-quoted JSON and a double-quoted host
attribute would be broken by the first `"`).

**When to use:** `GET /admin/settings`.

**Example:**
```python
# Source: pattern mirrors app/main.py::editor_page (existing, audited code)
@app.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request, ident: dict = Depends(require_owner)):
    groups = settings.all_for_ui()
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "editor.css"))
    except OSError:
        asset_v = 0
    return templates.TemplateResponse(
        request, "settings.html",
        {"groups": groups, "asset_v": asset_v},
    )
```
```html
<!-- Source: pattern mirrors app/templates/editor.html's x-data attribute -->
<div x-data='settingsApp({{ groups | tojson }})' x-cloak>
```

### Pattern 3: Atomic dry-run-then-commit POST (the phase's one novel piece, D-04/D-05)

**What:** Validate every submitted key with the schema's validator BEFORE writing any key.
`settings.set(key, value)` cannot be used for the validation pass because it writes on
success — calling it in a loop means earlier keys are already persisted by the time a later
key fails, violating the "writes nothing" contract (D-04).

**When to use:** `POST /admin/settings`.

**Example (illustrative — the exact internal hook into `core/settings.py` is planner
discretion per D-05, but the shape below is the load-bearing contract):**
```python
# Source: pattern is NEW to this phase — no existing code to mirror directly, but the
# discipline (validate fully before any write) mirrors editor.html's save_editor:
# EditorPage(**merged) is validated fully via pydantic BEFORE sync_editors() commits.
@app.post("/admin/settings")
async def save_settings(request: Request, ident: dict = Depends(require_owner)):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    errors: dict[str, str] = {}
    validated: dict[str, object] = {}
    for key, raw_value in body.items():
        try:
            # Dry-run: reuse the schema's validator WITHOUT persisting (D-05).
            validated[key] = settings.validate_only(key, raw_value)
        except settings.SettingRejected as exc:
            errors[key] = exc.reason

    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    for key, value in validated.items():
        settings.set(key, value)  # already validated; set() re-validates (harmless, cheap)

    return {"ok": True, "message": _SETTINGS_SAVED_COPY}
```

The `settings.validate_only(key, value)` helper does not exist yet — it is a **new, additive
function planner discretion may add to `core/settings.py`** (call `_SCHEMA[key].validate(value)`
directly, raising `SettingRejected` for an unknown key exactly like `set` does, but never
touching the database). This keeps the "single source of truth" schema intact (D-09's
stated goal) without needing the panel to duplicate any validator logic. Alternatively, the
handler can reach into `settings._SCHEMA` directly from `app/main.py` — but exposing a public
`validate_only` is cleaner and testable in isolation, consistent with `get`/`set`/`all_for_ui`
being the documented public contract.

### Pattern 4: `all_for_ui()` additive metadata (D-09)

**What:** Add `min`/`max` (from `_make_int_range`'s closure bounds, currently NOT stored as
data — only baked into the closure), a `tz_options` source for the one `timezone`-typed
setting, and a human `label` per setting, without changing `get`/`set`/`seed_defaults`.

**Example:**
```python
# Source: extends the existing core/settings.py::_Setting dataclass (Phase 1 code)
@dataclass(frozen=True)
class _Setting:
    key: str
    group: str
    type_tag: str
    default: object
    validate: Callable[[object], object]
    fallback_key: str | None = None
    hint: str = ""
    label: str = ""          # NEW (D-09) — human-readable field label, bilingual string
    min: int | None = None   # NEW (D-09) — only set for int_range entries
    max: int | None = None   # NEW (D-09) — only set for int_range entries


def _make_int_range(low: int, high: int) -> Callable[[object], int]:
    """Unchanged validator logic; low/high are now ALSO passed to the _Setting(min=, max=)
    call site so the panel can render bounds without re-deriving them (single source of truth)."""
    ...


def all_for_ui() -> list[dict]:
    grouped: dict[str, dict] = {}
    for descriptor in _SCHEMA.values():
        bucket = grouped.setdefault(
            descriptor.group, {"group": descriptor.group, "settings": []}
        )
        entry = {
            "key": descriptor.key,
            "type": descriptor.type_tag,
            "value": get(descriptor.key),
            "hint": descriptor.hint,
            "label": descriptor.label or descriptor.key,   # NEW
        }
        if descriptor.type_tag == "int_range":
            entry["min"] = descriptor.min                  # NEW
            entry["max"] = descriptor.max                  # NEW
        if descriptor.type_tag == "timezone":
            entry["options"] = sorted(available_timezones())  # NEW — D-06
        bucket["settings"].append(entry)
    return list(grouped.values())
```

Every `_Setting(...)` construction site in `_SCHEMA` needs its `min=`/`max=`/`label=` filled
in for the affected entries (`REMINDERS_CATCHUP_GRACE_HOURS` and `JINXXY_POLL_HOURS` are the
two `int_range` entries today, both `(1, 168)`). This is a small, mechanical, additive diff
across the 19 schema entries — no removed fields, no signature change to `get`/`set`.

### Anti-Patterns to Avoid

- **Re-implementing validation in Alpine/JS as the source of truth:** Client-side hints
  (e.g., graying out an out-of-range number) are fine for UX, but the server's
  `settings.set`/`validate_only` call is the ONLY authority — never trust a client-computed
  "this looks valid" flag when deciding whether to write.
- **Calling `settings.set` in a loop as the validation pass:** This partially writes before
  a later key's failure is discovered — the exact bug D-04/D-05 call out. Always
  validate-all-then-write-all.
- **Comparing `session["discord_id"]` (str) to `config.DISCORD_USER_ID` (int) without
  normalizing types**, or worse, treating a falsy/unset `owner_id` (`0`) as "no restriction" —
  both are the PANEL-01 fail-closed trap (see Pitfall 1).
- **Reading a request-body-supplied identity for the owner check:** Exactly the D-08 IDOR
  discipline `require_editor` already enforces — `require_owner` must be equally strict, even
  though there's only one legitimate owner (a crafted body should never be consulted for WHO
  is asking, only for WHAT they're changing).
- **Bypassing `core/settings.py` to read/write the `settings` table directly from
  `app/main.py`:** The schema allowlist in `settings.set` (`if key not in _SCHEMA: raise`) is
  the only thing preventing an arbitrary key from being written — always route through the
  module's public functions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Owner authorization check | A new OAuth scope, a new role, or a separate login flow for the owner | `require_owner` reusing the existing session cookie + `config.DISCORD_USER_ID` comparison | D-11: the owner already holds the editor role and already has a session by the time they'd hit `/admin/settings` — a second auth system is unnecessary complexity for a single, already-authenticated user |
| CSRF protection for the POST | A hand-rolled CSRF token | SameSite=Lax cookie + session-only identity (same mitigation `/editor/save` already relies on, documented in `app/main.py`'s module docstring) | The existing admin app's threat model is already reviewed and accepted; introducing a bespoke CSRF token for one new endpoint would be inconsistent and untested against the rest of the app |
| Timezone validity + listing | A hardcoded list of "common" timezones, or a new tz library | stdlib `zoneinfo.available_timezones()` + the already-existing `_validate_timezone` (uses `ZoneInfo`) | Already the validation gate from Phase 1; `available_timezones()` is the stdlib-correct way to enumerate the full IANA set, confirmed working (599 zones) with the already-pinned `tzdata` dependency |
| Multi-field validation error collection | A generic form-validation micro-framework (e.g., pulling in `wtforms`/`marshmallow`) | The existing `_SCHEMA[key].validate` callables, looped manually in the handler | The schema's per-key validators already exist and are unit-tested (`tests/test_settings.py`); a new validation library would duplicate logic that must stay in sync with `settings.set`'s own gate — the schema must remain the single source of truth (explicit CONTEXT.md rationale for D-09) |
| Rate limiting the settings POST | A new pip dependency (e.g. `slowapi`) | Same accepted decision as the editor app's Phase-10 plan: proxy-level (Caddy `rate_limit` directive) — see `app/main.py`'s module docstring | Already documented as an accepted alternative for this exact app; adding a new dependency mid-phase for one endpoint contradicts the existing precedent and would need its own legitimacy checkpoint |

**Key insight:** This phase has almost nothing to hand-roll because Phase 1 and the earlier
editor-app phases already solved every hard problem (validated store, OAuth session, WAL
concurrency, JSON-fetch save UX, CSRF-via-SameSite). The risk here is *inventing* new
machinery where copying an existing, reviewed pattern would do — every "Don't Hand-Roll" row
above is really "don't re-solve a problem this codebase already solved."

## Common Pitfalls

### Pitfall 1: The `DISCORD_USER_ID` fail-closed trap (PANEL-01's explicit "0 default must never authorize")

**What goes wrong:** `config.DISCORD_USER_ID` defaults to `int(os.getenv("DISCORD_USER_ID", "0"))`
— i.e., `0` when unset. If `require_owner` naively does
`request.session.get("discord_id") == config.DISCORD_USER_ID`, an attacker (or a broken
session) with a falsy/`None`/`0`-ish `discord_id` could incorrectly satisfy `0 == 0` (e.g.
if a `str(discord_id)` conversion elsewhere ever produces `"0"` or an int `0` slips through).
**Why it happens:** Treating "config not set" the same as "config set to a real value" —
classic fail-open-by-default bug when a sentinel default doubles as "disabled."
**How to avoid:** Explicitly guard `if not owner_id: raise HTTPException(403, ...)` BEFORE
comparing, so `DISCORD_USER_ID == 0` always 403s regardless of what's in the session. Write
a dedicated test (mirroring `test_require_editor_401_without_session`): "owner unset (0) +
any session discord_id → 403" as its own assertion, distinct from "wrong owner id → 403."
**Warning signs:** Any comparison of the shape `session_value == config_value` without a
preceding falsy-check on `config_value`.

### Pitfall 2: Partial-write on multi-field POST (violates D-04's "writes nothing" contract)

**What goes wrong:** Looping `for key, value in body.items(): settings.set(key, value)` calls
`set()` — which WRITES on success — for each key in submission order. If the 5th of 10 keys
is invalid, the first 4 are already persisted before `SettingRejected` is raised, and the
`except` swallowing it would leave the store in an inconsistent, partially-updated state
directly contradicting PANEL-03 ("rejected before any write") and D-04 ("atomic all-or-nothing").
**Why it happens:** `settings.set`'s validate-then-write is atomic per-key, but the phase
requires atomicity across the WHOLE payload — a naive per-key loop only gets you per-key
atomicity.
**How to avoid:** Two-pass: validate every key first (a read-only dry run against each
`_Setting.validate` callable, collecting `{key: reason}` for failures), and ONLY if the
error map is empty, loop again calling `settings.set` for every key.
**Warning signs:** A test that submits one valid + one invalid key in the same POST and
asserts the valid key was NOT persisted — if this test is missing, the bug is likely present.

### Pitfall 3: `all_for_ui()` test staleness after the D-09 additive extension

**What goes wrong:** `tests/test_settings.py::test_all_for_ui_grouped` currently asserts
shape/secret-absence but not the new `min`/`max`/`label`/`options` keys. If the planner adds
these fields to `_Setting`/`all_for_ui()` without updating this test, the Phase-1 test suite
stays green while silently under-asserting the new contract — a regression risk for future
phases that might accidentally drop a metadata field.
**Why it happens:** The existing test predates D-09; CONTEXT.md explicitly flags this
("Phase-1 tests for `all_for_ui()` must be updated") but it's easy to miss during
implementation since the existing test still passes unmodified.
**How to avoid:** Add explicit assertions for the new keys (e.g.,
`assert next(s for s in ... if s["key"]=="JINXXY_POLL_HOURS")["min"] == 1`) rather than only
relying on the existing secret-absence check.
**Warning signs:** `git diff` on `core/settings.py` touches `_Setting`/`all_for_ui()` but
`tests/test_settings.py` has no corresponding diff.

### Pitfall 4: Session identity type mismatch (`str` vs `int`) in the owner comparison

**What goes wrong:** `app/auth.py::callback` stores `request.session["discord_id"] = user_id`
where `user_id = str(user["id"])` — always a string. `config.DISCORD_USER_ID` is
`int(os.getenv(...))` — always an int. A naive `session_id == config.DISCORD_USER_ID`
comparison is `"123" == 123` → always `False`, even for the correct owner — a functional bug
(owner locked out), not a security bug, but it would make PANEL-01's "the owner gets 200"
success criterion fail.
**Why it happens:** The two values are typed differently by design elsewhere in the codebase
(`require_editor` never needed to compare discord_id to a config int — it only compares
role membership).
**How to avoid:** Cast both to `str` (or both to `int`) before comparing, and cover this
with a test that sets a real numeric owner id and a session id of the SAME logical value in
its natural stored type (string) to catch a type-mismatch regression.
**Warning signs:** A "the owner is denied access" bug report despite `DISCORD_USER_ID` being
correctly configured — check the comparison's operand types first.

### Pitfall 5: Windows dev machine vs. Linux deployment target for `zoneinfo`

**What goes wrong:** `zoneinfo.available_timezones()` can return an empty set (or the
module can fail to resolve any zone) on a system with neither the OS's IANA tz database nor
the `tzdata` pip package installed. This project already depends on `tzdata>=2025.2` from
Phase 1 (confirmed present in the dev conda env — 599 zones resolve correctly), so this is
a low-risk pitfall here, but worth stating: if the deployment target ("cinema", per the
docstrings) is a minimal container image or a stripped Linux distro missing
`/usr/share/zoneinfo`, and `tzdata` were ever removed from `requirements.txt`, the D-06
`<select>` would silently render empty.
**Why it happens:** `zoneinfo` in the stdlib is a thin wrapper — it needs an actual tz
database from SOMEWHERE (OS package or the `tzdata` pip package as a fallback).
**How to avoid:** Do not remove `tzdata` from `requirements.txt`; the dependency is already
correctly declared. No action needed beyond not accidentally dropping it.
**Warning signs:** An empty timezone `<select>` in the rendered panel, or
`zoneinfo.ZoneInfoNotFoundError` raised even for well-known zones like `America/Mexico_City`.

## Code Examples

### `require_owner` (full, PANEL-01 contract)
```python
# Source: mirrors app/deps.py::require_editor (existing code, adapted)
from fastapi import HTTPException, Request

import config

_OWNER_FORBIDDEN_COPY = (
    "Solo el propietario puede acceder a esta página. — "
    "Only the owner can access this page."
)


async def require_owner(request: Request) -> dict:
    discord_id = request.session.get("discord_id")
    owner_id = config.DISCORD_USER_ID
    if not owner_id:                                   # fail closed: unset/0 owner id
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    if not discord_id or str(discord_id) != str(owner_id):
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    return {"discord_id": discord_id}
```

### `editor_page` context extension for the owner-only link (D-12)
```python
# Source: extends app/main.py::editor_page (existing code)
@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request, ident: dict = Depends(require_editor)):
    ...
    owner_id = config.DISCORD_USER_ID
    is_owner = bool(owner_id) and str(ident["discord_id"]) == str(owner_id)
    return templates.TemplateResponse(
        request, "editor.html",
        {"entry": entry, "website_base": config.WEBSITE_BASE_URL,
         "asset_v": asset_v, "is_owner": is_owner},
    )
```
```html
<!-- Source: extends app/templates/editor.html's topbar -->
{% if is_owner %}
<a class="btn btn--ghost" href="/admin/settings">⚙ Ajustes · Settings</a>
{% endif %}
```

### Test pattern for `require_owner` (mirrors `test_require_editor_*` in `tests/test_app_auth.py`)
```python
# Source: mirrors tests/test_app_auth.py's TestClient-free async-dependency test style
import asyncio
import pytest
from fastapi import HTTPException

import config


def test_require_owner_403_when_owner_id_unset(monkeypatch):
    from app import deps
    monkeypatch.setattr(config, "DISCORD_USER_ID", 0)
    req = _FakeRequest()
    req.session = {"discord_id": "555"}
    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_owner(req))
    assert ei.value.status_code == 403


def test_require_owner_200_for_matching_owner(monkeypatch):
    from app import deps
    monkeypatch.setattr(config, "DISCORD_USER_ID", 555)
    req = _FakeRequest()
    req.session = {"discord_id": "555"}
    ident = asyncio.run(deps.require_owner(req))
    assert ident["discord_id"] == "555"


def test_require_owner_403_for_non_owner_session(monkeypatch):
    from app import deps
    monkeypatch.setattr(config, "DISCORD_USER_ID", 555)
    req = _FakeRequest()
    req.session = {"discord_id": "999"}  # a real editor, but not the owner
    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_owner(req))
    assert ei.value.status_code == 403
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `config.py` module-level constants frozen at import (all settings) | `config.py.__getattr__` (PEP 562) routes 19 safe tunables to `settings.get(...)` read-at-use | Phase 1 (already merged, per `.planning/STATE.md`: "1 of 2 phases complete") | PANEL-04 is ALREADY satisfied by this existing shim — no bot-process code change is needed in Phase 2. The panel writing to the `settings` table is sufficient; the next `config.X` attribute access anywhere in the bot re-resolves through `settings.get` automatically |
| N/A (no settings UI existed before) | `require_owner` / `/admin/settings` (this phase) | This phase | First write-capable surface into the `settings` table other than `seed_defaults()` at startup |

**Deprecated/outdated:** None — this is a young codebase (Phase 1 completed 2026-07-19/21,
per STATE.md); nothing here is legacy.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `settings.validate_only(key, value)` (or equivalent dry-run hook) does not yet exist and must be added as new, additive surface on `core/settings.py` | Pattern 3 / Alternatives Considered | Low — this is a design recommendation, not a verified fact about a shipped API; the planner may instead choose to reach into `_SCHEMA` directly from `app/main.py`, which is functionally equivalent and does not change any behavior, only which module owns the dry-run logic |
| A2 | The owner also currently holds the editor role in the live Discord guild (D-11's "confirmed assumption") | User Constraints (copied from CONTEXT.md D-11) | Medium — if untrue, the owner cannot even reach `/login` (403 at the editor-role gate) and would be fully locked out of `/admin/settings` despite this phase being implemented correctly; CONTEXT.md already flags this as a confirmed assumption with a documented fallback (make owner login independent of editor role), deferred unless it breaks |

**If this table is empty:** N/A — two low/medium-risk assumptions logged above, both already
surfaced and accepted in CONTEXT.md's own decision record (D-05 discretion, D-11 confirmed
assumption) rather than newly discovered here.

## Open Questions (RESOLVED)

1. **Exact template/CSS approach: dedicated `settings.css` vs. reusing `editor.css` classes**
   - What we know: `editor.css` already defines `.field`, `.label`, `.btn`, `.btn--accent`,
     `.topbar`, `.toast` etc. — general-purpose admin-chrome classes, not editor-page-specific
     markup.
   - What's unclear: Whether `editor.css` has enough generic classes to fully style a
     grouped-settings form (fieldsets per feature group) without any new CSS, or whether a
     small `settings.css` addendum (or additions to `editor.css`) is needed for
     group/fieldset layout not currently present.
   - Recommendation: Start by reusing `editor.css` classes verbatim (`.field`, `.label`,
     `.btn`); add a handful of new classes (e.g. `.settings-group`) only if the existing set
     proves insufficient during template implementation — this is a planner/implementer
     judgment call, not a research gap.
   - RESOLVED: Followed — plan 02-03 reuses `editor.css` classes verbatim (`.field`,
     `.label`, `.btn`, `.theme-group`) and appends only the two NEW inline-error classes
     (`.field-error`, `.field--invalid`) to `editor.css`; no separate `settings.css` was
     forked. See 02-03-PLAN.md Task 2 and 02-UI-SPEC.md § New Elements.

2. **Where does the `validate_only` (or equivalent) dry-run function live, and is it public API?**
   - What we know: D-09 explicitly says the internal shape of the metadata extension is
     planner discretion, and D-05 says the exact multi-error mechanism is planner discretion.
   - What's unclear: Whether adding a new public function to `core/settings.py` (beyond the
     documented `get`/`set`/`all_for_ui` contract) is acceptable, or whether the POST handler
     should reach into `settings._SCHEMA` (a "private" module attribute) directly.
   - Recommendation: Prefer adding a small, explicitly-public `validate_only` alongside
     `get`/`set`/`all_for_ui` — it is a natural, minimal, testable addition that keeps
     `app/main.py` from reaching into another module's underscore-prefixed internals, and
     it directly serves the D-04/D-05 atomicity contract this phase's success criteria
     require.
   - RESOLVED: Followed — plan 02-01 adds an explicitly-public `validate_only(key, value)`
     to `core/settings.py` alongside `get`/`set`/`all_for_ui`; the 02-04 POST handler calls
     it in the first (dry-run) pass and never reaches into `settings._SCHEMA`. See
     02-01-PLAN.md Task 2 and 02-04-PLAN.md Task 3.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| FastAPI | GET/POST `/admin/settings` routes | ✓ | 0.139.0 | — |
| Jinja2Templates (via Starlette) | Server-render `settings.html` | ✓ | bundled with FastAPI 0.139.0 | — |
| `zoneinfo` (stdlib) | D-06 timezone `<select>` + existing `_validate_timezone` | ✓ | stdlib (Python 3.9+) | — |
| `tzdata` | Backing IANA data for `zoneinfo` on this dev machine (Windows) | ✓ | 2025.2 (pinned `requirements.txt:24`) | OS-native tz database on Linux deployment target if `tzdata` package were ever absent there |
| Alpine.js (vendored) | Client hydrate + fetch save | ✓ | 3.15.12 (`app/static/alpine.min.js`) | — |
| `pytest` (conda env) | Running the test suite locally | ✓ | Use `C:\Users\Shangri\miniconda3\python.exe -m pytest` (per project MEMORY note — PowerShell's Python314 lacks pytest) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — every dependency is already present and pinned.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing suite: `tests/test_settings.py`, `tests/test_app_auth.py`, `tests/test_app_editor.py`) |
| Config file | none found (no `pytest.ini`/`pyproject.toml` in repo) — pytest runs with defaults from `tests/` |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_settings.py -x` |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest` |

*(Per project MEMORY: use the conda python, not PowerShell's Python314, which has no pytest.)*

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PANEL-01 | Non-owner → 403 no data; owner → 200; fails closed when `DISCORD_USER_ID` unset | unit (async dependency, mirrors `test_require_editor_*`) | `pytest tests/test_app_settings.py -k require_owner -x` | ❌ Wave 0 |
| PANEL-02 | `GET /admin/settings` renders grouped typed fields; no secret in response body | integration (TestClient, mirrors `tests/test_app_editor.py`'s `client` fixture) | `pytest tests/test_app_settings.py -k get_settings -x` | ❌ Wave 0 |
| PANEL-03 | Valid POST persists + success banner; invalid POST → inline error, writes nothing | integration (TestClient + monkeypatched `core.settings`) | `pytest tests/test_app_settings.py -k post_settings -x` | ❌ Wave 0 |
| PANEL-04 | Saved value read by `settings.get` (already covered by Phase 1's `tests/test_settings.py` round-trip tests) | unit (existing) | `pytest tests/test_settings.py -k round_trip -x` | ✅ (Phase 1) |
| D-09 (all_for_ui metadata) | `min`/`max`/`label`/timezone `options` present per type_tag | unit | `pytest tests/test_settings.py -k all_for_ui -x` | ❌ Wave 0 (extend existing test) |

### Sampling Rate
- **Per task commit:** `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_settings.py tests/test_settings.py -x`
- **Per wave merge:** `C:\Users\Shangri\miniconda3\python.exe -m pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_app_settings.py` — new file, covers PANEL-01/02/03 (mirror the `client`
      TestClient fixture pattern from `tests/test_app_editor.py`, and the async-dependency
      pattern from `tests/test_app_auth.py` for `require_owner` in isolation)
- [ ] Extend `tests/test_settings.py::test_all_for_ui_grouped` (or add a new test) to assert
      the D-09 metadata keys (`min`, `max`, `label`, `options`) per type_tag
- [ ] No new fixtures/conftest needed — `_use_tmp_db` (from `tests/test_settings.py`) and the
      `client` fixture pattern (from `tests/test_app_editor.py`) already cover what's needed;
      reuse both.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Indirect (reused) | Already satisfied by the existing Discord OAuth2 flow (`app/auth.py`) — this phase adds no new authentication, only a narrower authorization check on top of an existing session |
| V3 Session Management | Indirect (reused) | Already satisfied by `SessionMiddleware` (`https_only`, `same_site=lax`, 6h TTL) — no new session logic in this phase |
| V4 Access Control | **Yes** | `require_owner` — a single server-side equality check on session-derived identity vs. `config.DISCORD_USER_ID`, fail-closed on unset owner id (PANEL-01); this is the phase's primary security surface |
| V5 Input Validation | **Yes** | `core/settings.py`'s existing per-type validators (`_validate_channel_id`, `_validate_role_id_list`, `_make_int_range`, `_validate_timezone`, `_validate_free_string`, `_validate_url`, `_validate_lang`) — this phase must call these on EVERY field, never trust client-side checks |
| V6 Cryptography | No | No new crypto surface — session signing already handled by `itsdangerous` via `SessionMiddleware`, untouched by this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Owner-gate bypass via type confusion (`int` vs `str` discord_id comparison) | Elevation of Privilege | Normalize both operands to the same type before comparing (Pitfall 4); explicit falsy-check on `config.DISCORD_USER_ID` before any comparison (Pitfall 1) |
| Partial-write leaving the store in a state a bad value could reach the bot from | Tampering | Atomic two-pass validate-then-write (D-04/D-05, Pitfall 2) — never call `settings.set` before every field in the payload has independently passed validation |
| Schema-allowlist bypass (writing an arbitrary sqlite key/value not in `_SCHEMA`) | Tampering / Elevation of Privilege | Already enforced by `settings.set`'s `if key not in _SCHEMA: raise SettingRejected` — this phase must route every write through `settings.set`/the new dry-run helper, never construct raw SQL against the `settings` table |
| CSRF on the state-changing POST | Tampering | SameSite=Lax cookie + session-only identity (no body-supplied identity) — same accepted mitigation as `/editor/save`, not a new decision for this phase |
| Secret leakage via the settings render or error payload | Information Disclosure | `all_for_ui()`'s schema-driven allowlist already guarantees only the 19 safe tunables are ever serialized (test-pinned: `test_all_for_ui_grouped` asserts secrets absent from the repr) — this phase must not add any new field to `all_for_ui()`'s output that reads from `config.py`'s frozen (secret/structural) constants |

## Sources

### Primary (HIGH confidence)
- `core/settings.py` (repo, Phase 1 completed code) — `get`/`set`/`all_for_ui`/`SettingRejected`/`_SCHEMA` read directly
- `app/deps.py`, `app/auth.py`, `app/main.py` (repo, Phase-10 completed code) — `require_editor`, OAuth flow, `editor_page`, `/editor/save`, `_auth_html_or_json` handler read directly
- `app/templates/editor.html`, `app/templates/login.html` (repo) — Alpine hydrate pattern, single-quoted `x-data` rationale, bilingual copy style read directly
- `tests/test_settings.py`, `tests/test_app_auth.py`, `tests/test_app_editor.py` (repo) — existing test patterns and fixtures read directly
- `config.py` (repo) — `DISCORD_USER_ID`, the PEP 562 `__getattr__` shim, the safe-tunable allowlist read directly
- `.planning/phases/02-owner-settings-panel/02-CONTEXT.md` — locked decisions read directly
- `.planning/REQUIREMENTS.md` — PANEL-01..04 exact wording read directly
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — original design spec read directly
- Local environment checks: `pip show fastapi` (0.139.0), `pip show tzdata` (2025.2),
  `python -c "from zoneinfo import available_timezones; ..."` (599 zones, `America/Mexico_City`
  resolves) — all run directly in this session

### Secondary (MEDIUM confidence)
None — no external WebSearch/Context7 lookups were needed; every fact required for this
phase was verifiable directly against the existing, already-audited codebase.

### Tertiary (LOW confidence)
None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every library is already installed/vendored and version-confirmed locally; no new dependency decisions
- Architecture: HIGH — directly mirrors two existing, tested route pairs (`editor_page`/`/editor/save`) in the same file
- Pitfalls: HIGH — each pitfall is derived from a concrete, locked CONTEXT.md decision (D-04/D-05, PANEL-01's exact wording) plus a direct read of the relevant existing code (`config.py`'s int-typed `DISCORD_USER_ID` vs. `auth.py`'s str-typed session value)

**Research date:** 2026-07-21
**Valid until:** 2026-08-20 (30 days — stable, in-repo-only research; no external ecosystem drift risk since no third-party packages are introduced)
