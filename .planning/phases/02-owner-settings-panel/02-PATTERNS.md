# Phase 2: Owner Settings Panel - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 8 (2 new, 5 modified, 1 new test file)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|---------------|
| `app/deps.py` (add `require_owner`) | middleware (auth dependency) | request-response | `app/deps.py::require_editor` (same file) | exact |
| `app/main.py` (add `GET /admin/settings`) | route/controller | request-response (SSR) | `app/main.py::editor_page` | exact |
| `app/main.py` (add `POST /admin/settings`) | route/controller | request-response (atomic validate-then-write) | `app/main.py::save_editor` (`/editor/save`) | exact |
| `app/main.py` (extend `editor_page` context) | route/controller | request-response | `app/main.py::editor_page` (same function, D-12 `is_owner` flag) | exact |
| `app/templates/settings.html` (NEW) | component (Jinja2 template) | request-response (SSR + Alpine hydrate) | `app/templates/editor.html` | exact |
| `app/templates/editor.html` (add owner-only link) | component | request-response | same file, topbar section | exact |
| `core/settings.py` (extend `_Setting`/`all_for_ui`, add `validate_only`) | model/store | CRUD | `core/settings.py` (same file — additive to existing descriptor + API) | exact |
| `tests/test_app_settings.py` (NEW) | test | request-response (integration) | `tests/test_app_editor.py` + `tests/test_app_auth.py` | exact |
| `tests/test_settings.py` (extend `test_all_for_ui_grouped`) | test | CRUD (unit) | `tests/test_settings.py` (same file) | exact |

## Pattern Assignments

### `app/deps.py` — add `require_owner` (middleware, request-response)

**Analog:** `app/deps.py::require_editor` (lines 1-50, full file — read in full, no re-read needed)

**Imports pattern** (lines 22-24):
```python
from fastapi import HTTPException, Request

from app.auth import _FORBIDDEN_COPY, has_editor_role
```
For `require_owner`, swap the second import for `config` (owner id lives in `config.DISCORD_USER_ID`, not in an auth-role check):
```python
from fastapi import HTTPException, Request

import config
```

**Core auth-gate pattern** (lines 27-49):
```python
async def require_editor(request: Request) -> dict:
    """Return the session-scoped editor identity, or raise 401/403. ..."""
    discord_id = request.session.get("discord_id")
    if not discord_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Re-prove the role on every protected action ...
    if not await has_editor_role(discord_id):
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    # Identity from the SESSION only — never from the request body (D-08 IDOR choke point).
    return {"discord_id": discord_id, "slug": request.session.get("slug")}
```

`require_owner` mirrors this shape but narrows to `session.discord_id == config.DISCORD_USER_ID`,
returns 403 (not 401 — PANEL-01's exact wording), and must fail closed on the `0` default
(RESEARCH.md Pattern 1 / Pitfall 1 / Pitfall 4 give the exact target implementation — copy from
there, it is the load-bearing contract for D-10):
```python
async def require_owner(request: Request) -> dict:
    discord_id = request.session.get("discord_id")
    owner_id = config.DISCORD_USER_ID
    if not owner_id:                                   # fail closed: unset/0 owner id
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    if not discord_id or str(discord_id) != str(owner_id):
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    return {"discord_id": discord_id}
```

**Docstring convention:** `require_editor`'s module/function docstrings (lines 1-20, 28-37) name
the invariant they guarantee ("Identity from the session ONLY", "fails closed") and cite the
decision ID (D-08, Pitfall 2). `require_owner`'s docstring should cite D-10/PANEL-01 the same way.

---

### `app/main.py` — `GET /admin/settings` (route, request-response SSR)

**Analog:** `app/main.py::editor_page` (lines 382-408)

**Imports already present** (lines 42-57) — no new imports needed beyond what `app/main.py`
already has (`Depends`, `HTMLResponse`, `templates`, `os`, `Path`); add `from core import settings`
and `from app.deps import require_owner` alongside the existing `from app.deps import require_editor`.

**Core SSR pattern** (lines 382-408):
```python
@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request, ident: dict = Depends(require_editor)):
    entry = await _fetch_current_entry(ident["discord_id"])
    if entry is None:
        entry = {...}
    # Cache-buster for /static/editor.css: the file's mtime. ...
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "editor.css"))
    except OSError:
        asset_v = 0
    return templates.TemplateResponse(
        request, "editor.html",
        {"entry": entry, "website_base": config.WEBSITE_BASE_URL, "asset_v": asset_v},
    )
```

`GET /admin/settings` copies this shape exactly: `Depends(require_owner)` instead of
`require_editor`, `settings.all_for_ui()` instead of `_fetch_current_entry`, and
`templates.TemplateResponse(request, "settings.html", {"groups": ..., "asset_v": ...})`.
Same `?v=<mtime>` cache-buster idiom (D-02 / D-anything about template file naming is
Claude's discretion, but the cache-buster mechanism itself is not — copy verbatim).

Also extend `editor_page`'s own context per D-12 (the owner-only link needs `is_owner` in
`editor.html`'s Jinja context):
```python
owner_id = config.DISCORD_USER_ID
is_owner = bool(owner_id) and str(ident["discord_id"]) == str(owner_id)
return templates.TemplateResponse(
    request, "editor.html",
    {"entry": entry, "website_base": config.WEBSITE_BASE_URL,
     "asset_v": asset_v, "is_owner": is_owner},
)
```

---

### `app/main.py` — `POST /admin/settings` (route, atomic validate-then-write)

**Analog:** `app/main.py::save_editor` (lines 627-681) — the closest existing "validate fully
before any write" pattern in this codebase (validates the FULL `EditorPage` via pydantic before
`sync_editors` commits), even though it is single-shot pydantic validation rather than the
per-field two-pass this phase needs.

**Request body + error handling pattern** (lines 637-642):
```python
try:
    body = await request.json()
except Exception:
    raise HTTPException(status_code=400, detail="Invalid JSON body")
if not isinstance(body, dict):
    raise HTTPException(status_code=400, detail="Invalid JSON body")
```
Copy verbatim for `POST /admin/settings` — this is the exact 400-on-bad-JSON guard the new
handler needs too.

**Validate-then-commit-then-respond shape** (lines 663-681, condensed):
```python
merged = _apply_session_identity(body, ident, slug=slug, media_id=media_id, published=True)
try:
    entry = EditorPage(**merged).model_dump()
except ValidationError as exc:
    return JSONResponse(status_code=422, content={"error": str(exc)})
try:
    await github_publish.sync_editors(entry, prune=True)
except github_publish.GitHubPublishError:
    log.exception("editor save commit failed")
    return JSONResponse(status_code=502, content={"error": _SAVE_FAILED_COPY})
request.session["slug"] = slug
return {"message": _PUBLISH_SUCCESS_COPY, "published": True}
```
The new handler's shape (per D-03/D-04/D-05, and RESEARCH.md Pattern 3 which is the one
genuinely novel piece — no direct existing analog for the PER-FIELD multi-error dry-run loop,
only for the "validate everything before writing anything" discipline):
```python
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
            validated[key] = settings.validate_only(key, raw_value)  # dry-run, no write
        except settings.SettingRejected as exc:
            errors[key] = exc.reason

    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    for key, value in validated.items():
        settings.set(key, value)

    return {"ok": True, "message": _SETTINGS_SAVED_COPY}
```

**Bilingual copy constant convention** (mirror `_PUBLISH_SUCCESS_COPY`/`_SAVE_FAILED_COPY`,
lines 81-92): every new user-facing string is one bilingual literal, ES first, `—` or `·`
separator, EN second — add `_SETTINGS_SAVED_COPY` and any settings-specific error copy in the
same block near the top of `app/main.py` (lines 76-92 is where the existing ones live).

---

### `app/templates/settings.html` (NEW template, SSR + Alpine hydrate)

**Analog:** `app/templates/editor.html` (head lines 1-15, `x-data` lines 16-21, topbar
lines 23-35, save/toast wiring lines 1262-1319)

**Head + single-quoted x-data pattern** (lines 1-21):
```html
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="robots" content="noindex, nofollow" />
  <title>Nocturna · Editor de perfil</title>
  <link rel="stylesheet" href="/static/editor.css?v={{ asset_v | default(0) }}" />
</head>
<body>
  {#- x-data MUST be single-quoted: `entry | tojson` emits double-quoted JSON, and
      Jinja escapes ' -> ', so a single-quoted attribute can never be broken by
      the data. -#}
  <div x-data='editorApp({{ entry | tojson }})' x-cloak>
```
`settings.html` copies this exactly, swapping `entry | tojson` for `groups | tojson` and
`editorApp(...)` for a new `settingsApp(...)` function (RESEARCH.md Pattern 2 gives this exact
target: `<div x-data='settingsApp({{ groups | tojson }})' x-cloak>`).

**Topbar pattern** (lines 24-35) — reuse verbatim, replacing the publish/unpublish buttons with
a single Save button and a back-to-editor link:
```html
<header class="topbar">
  <h1 class="wordmark">Nocturna</h1>
  <span class="spacer"></span>
  <button class="btn btn--accent" type="button" @click="save()" :disabled="saving"
          x-text="saving ? 'Guardando…' : 'Guardar · Save'"></button>
  <a class="btn btn--ghost" href="/logout">Salir · Sign out</a>
</header>
```

**Fetch-JSON save pattern** (lines 1262-1290, `publish()`):
```javascript
async publish() {
  this.saving = true;
  this.toast = '';
  try {
    const r = await fetch('/editor/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.serialize()),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok) {
      this.toastKind = 'ok';
      this.toast = data.message || '...';
    } else {
      this.toastKind = 'error';
      this.toast = data.error || '...';
    }
  } catch (e) {
    this.toastKind = 'error';
    this.toast = "...";
  } finally {
    this.saving = false;
  }
},
```
The new `save()` for settings copies this shape but posts to `/admin/settings` and, per D-03,
must branch on `{errors: {KEY: reason}}` vs `{ok, message}` to populate BOTH the toast banner
AND a per-field error map (new — no existing per-field error UI in this codebase; this is the
one piece of Alpine state/rendering that must be built fresh, not copied):
```javascript
async save() {
  this.saving = true;
  this.toast = '';
  this.fieldErrors = {};
  try {
    const r = await fetch('/admin/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.serialize()),
    });
    const data = await r.json().catch(() => ({}));
    if (r.ok && data.ok) {
      this.toastKind = 'ok';
      this.toast = data.message || '...';
    } else {
      this.toastKind = 'error';
      this.fieldErrors = data.errors || {};
      this.toast = 'Revisa los campos marcados · Check the highlighted fields';
    }
  } catch (e) {
    this.toastKind = 'error';
    this.toast = 'Error de red · Network error';
  } finally {
    this.saving = false;
  }
},
```

**Toast markup** (lines 653-655) — reuse verbatim:
```html
<div class="toast" x-show="toast" x-cloak :data-kind="toastKind" x-text="toast"
     @click="toast=''" role="status" aria-live="polite"></div>
```

**Script tag ordering** (lines 658-660, 1319-1323) — settingsApp must be defined BEFORE Alpine
parses `x-data`, and Alpine is vendored (not CDN), loaded `defer` at the very end:
```html
<script>
  function settingsApp(initial) { ... return {...}; }
</script>
<style>[x-cloak] { display: none !important; }</style>
<script defer src="/static/alpine.min.js"></script>
```
(No `Sortable.min.js` needed for settings.html — that is editor.html-specific for block
drag-reorder, not used here.)

---

### `app/templates/editor.html` — add owner-only settings link (D-12)

**Analog:** same file's topbar (lines 24-35), specifically the existing `<a class="btn
btn--ghost" href="/logout">` pattern for a plain link button.

**Target insertion** (topbar, near line 34, before the sign-out link):
```html
{% if is_owner %}
<a class="btn btn--ghost" href="/admin/settings">⚙ Ajustes · Settings</a>
{% endif %}
```
(RESEARCH.md's own Code Examples section gives this exact snippet.)

---

### `core/settings.py` — extend `_Setting` + `all_for_ui()`, add `validate_only` (D-09)

**Analog:** same file, `_Setting` dataclass (lines 148-156) and `all_for_ui()` (lines 319-342)
— additive changes to already-read code, no re-read needed.

**Current `_Setting` descriptor** (lines 148-156):
```python
@dataclass(frozen=True)
class _Setting:
    key: str
    group: str
    type_tag: str
    default: object
    validate: Callable[[object], object]
    fallback_key: str | None = None
    hint: str = ""
```
Add per D-09 / RESEARCH.md Pattern 4:
```python
    label: str = ""          # NEW — human-readable field label, bilingual string
    min: int | None = None   # NEW — only set for int_range entries
    max: int | None = None   # NEW — only set for int_range entries
```
Every `int_range` construction site (`REMINDERS_CATCHUP_GRACE_HOURS` line 196-200,
`JINXXY_POLL_HOURS` line 207-211, both `_make_int_range(1, 168)`) needs `min=1, max=168` added
to its `_Setting(...)` call, and all 19 entries need a `label=` filled in (mechanical, additive
diff — no removed fields).

**Current `all_for_ui()`** (lines 319-342) — the exact function to extend, per-entry dict shape
at lines 334-341:
```python
bucket["settings"].append(
    {
        "key": descriptor.key,
        "type": descriptor.type_tag,
        "value": get(descriptor.key),
        "hint": descriptor.hint,
    }
)
```
Extend to (RESEARCH.md Pattern 4 gives the exact target):
```python
entry = {
    "key": descriptor.key,
    "type": descriptor.type_tag,
    "value": get(descriptor.key),
    "hint": descriptor.hint,
    "label": descriptor.label or descriptor.key,
}
if descriptor.type_tag == "int_range":
    entry["min"] = descriptor.min
    entry["max"] = descriptor.max
if descriptor.type_tag == "timezone":
    entry["options"] = sorted(available_timezones())
bucket["settings"].append(entry)
```
Requires `from zoneinfo import available_timezones` added to the existing
`from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` import (line 22).

**New `validate_only` — mirror `set()`'s validation half without the write** (lines 299-316,
`set()`):
```python
def set(key: str, value) -> None:
    if key not in _SCHEMA:
        raise SettingRejected(f"unknown setting key: {key!r}")
    validated = _SCHEMA[key].validate(value)  # raises SettingRejected on failure, before any SQL
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(validated)),
        )
```
`validate_only` extracts the allowlist-check + validate-call (the first two lines of `set`'s
body) into its own public function, never touching the database — this is the dry-run hook
D-05/Pattern 3's POST handler calls in a loop:
```python
def validate_only(key: str, value):
    """Validate ``value`` for ``key`` WITHOUT persisting — raises SettingRejected, never writes.
    The dry-run half of ``set()``, extracted so the panel's atomic multi-field POST (D-04/D-05)
    can validate every submitted field before committing any of them."""
    if key not in _SCHEMA:
        raise SettingRejected(f"unknown setting key: {key!r}")
    return _SCHEMA[key].validate(value)
```
`set()` can then optionally delegate to it (`validated = validate_only(key, value)`) — same
behavior, one less duplicated allowlist check.

**Docstring/comment convention:** every function in this module opens with a one-line summary
naming the STORE-/CONF- requirement ID it satisfies (e.g. "STORE-03", "CONF-03" — see lines
271-280, 299-307). `validate_only` and the `_Setting` additions should cite D-09/D-05 the same
way for consistency with the rest of the module.

---

### `tests/test_app_settings.py` (NEW test file)

**Analog:** `tests/test_app_auth.py` (require_owner-style dependency unit tests, `_FakeRequest`
pattern, lines 77-83, 283-319) + `tests/test_app_editor.py` (TestClient fixture + dependency
override pattern, lines 1-35)

**`_FakeRequest` + async-dependency test pattern** (test_app_auth.py lines 77-83, 283-319):
```python
class _FakeRequest:
    def __init__(self):
        self.session = {}
        self.query_params = {"next": "https://evil.example/pwn"}

def test_require_editor_401_without_session():
    from app import deps
    req = _FakeRequest()  # empty session
    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_editor(req))
    assert ei.value.status_code == 401
```
Use the same `_FakeRequest` + `asyncio.run(deps.require_owner(req))` shape for `require_owner`
unit tests — RESEARCH.md's own Code Examples section (lines 622-648) already gives 3
ready-to-adapt test bodies: `test_require_owner_403_when_owner_id_unset`,
`test_require_owner_200_for_matching_owner`, `test_require_owner_403_for_non_owner_session`.

**TestClient + `dependency_overrides` fixture pattern** (test_app_editor.py lines 13-35):
```python
_IDENT = {"discord_id": "555", "slug": "aria"}

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    app.dependency_overrides[require_editor] = lambda: _IDENT
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(require_editor, None)
```
`tests/test_app_settings.py`'s `client` fixture copies this exactly, overriding
`require_owner` instead of `require_editor`, and additionally pointing `config.DB_PATH` at a
`tmp_path` sqlite file (per `tests/test_settings.py::_use_tmp_db`, lines 27-29) since the
settings endpoints read/write through `core.settings`/`core.db` for real (unlike the editor
endpoints, which mock `github_publish.sync_editors` — the settings store IS the sqlite DB, no
external API to mock).

**PANEL-03 partial-write regression test** — RESEARCH.md's Pitfall 2 names the exact test
shape needed: submit one valid + one invalid key in the same POST body and assert the valid
key was NOT persisted (query `settings.get` for it afterward and confirm it is still the
default/unwritten value).

---

### `tests/test_settings.py` — extend `test_all_for_ui_grouped` (D-09 / Pitfall 3)

**Analog:** same file, `test_all_for_ui_grouped` (lines 144-151):
```python
def test_all_for_ui_grouped(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    grouped = settings.all_for_ui()
    assert isinstance(grouped, list) and grouped
    blob = repr(grouped)
    for secret in ("BOT_TOKEN", "GITHUB_PAT", "JINXXY_API_KEY", "SESSION_SECRET", "DB_PATH"):
        assert secret not in blob
```
Add assertions for the new `min`/`max`/`label`/`options` keys per RESEARCH.md's Pitfall 3
example:
```python
    settings_by_key = {s["key"]: s for g in grouped for s in g["settings"]}
    jinxxy = settings_by_key["JINXXY_POLL_HOURS"]
    assert jinxxy["min"] == 1 and jinxxy["max"] == 168
    tz = settings_by_key["REMINDERS_TZ"]
    assert "America/Mexico_City" in tz["options"]
    assert all(s.get("label") for s in settings_by_key.values())
```

## Shared Patterns

### Owner/editor auth dependency shape
**Source:** `app/deps.py::require_editor` (lines 27-49)
**Apply to:** `require_owner` in `app/deps.py`
Session-only identity (`request.session.get("discord_id")`), never request body/query. Raise
`HTTPException` with a bilingual `_copy` constant, never a bare string for a user-facing 401/403.

### Bilingual copy constants
**Source:** `app/main.py` lines 76-92 (`_PUBLISH_SUCCESS_COPY`, `_SAVE_FAILED_COPY`, etc.),
`app/auth.py` lines 58-62 (`_FORBIDDEN_COPY`)
**Apply to:** All new user-facing strings in `app/main.py` and `app/deps.py` for this phase
(`_OWNER_FORBIDDEN_COPY`, `_SETTINGS_SAVED_COPY`, any settings-validation-failure banner text).
Format: one Python string literal, Spanish first, `—` separator, English second.

### `_auth_html_or_json` exception handler (already exists, no change needed)
**Source:** `app/main.py` lines 306-321
**Apply to:** `require_owner` — since it raises plain `HTTPException(403)` exactly like
`require_editor`, the existing handler already renders `login.html` for a browser navigation
hit and JSON for `Accept: application/json` fetch calls. No new exception handler needed.

### Server-render + Alpine single-quoted `x-data` hydrate
**Source:** `app/templates/editor.html` lines 16-21, `app/main.py::editor_page` lines 401-408
**Apply to:** `settings.html` / `GET /admin/settings`. The single-quote requirement is
load-bearing (documented in the template comment) — a double-quoted `x-data` breaks on the
JSON payload's first embedded `"`.

### `?v=<mtime>` CSS cache-buster
**Source:** `app/main.py::editor_page` lines 401-404
**Apply to:** `GET /admin/settings` handler — identical `os.path.getmtime` + `try/except OSError`
fallback-to-0 idiom.

### fetch/JSON POST + toast/banner UX
**Source:** `app/templates/editor.html::publish()` lines 1262-1290
**Apply to:** `settings.html`'s `save()` — same try/fetch/catch/finally shape, `Content-Type:
application/json` header, `r.ok` branch on success vs error, `.toast`/`data-kind` UI element.
NEW addition beyond this analog: per-field `errors` map handling (D-03) has no existing analog
in this codebase — built fresh per the JSON contract `{errors: {KEY: reason}}`.

### Schema allowlist + parameterized SQL (already exists, no change needed)
**Source:** `core/settings.py::set()` lines 299-316
**Apply to:** Nothing new — `validate_only`/`set` already gate every write through
`if key not in _SCHEMA: raise`; the panel must route every write through these functions,
never construct raw SQL against the `settings` table (RESEARCH.md Anti-Patterns section).

### `_use_tmp_db` sqlite isolation for tests
**Source:** `tests/test_settings.py` lines 27-29
```python
def _use_tmp_db(monkeypatch, tmp_path, name="settings.db"):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)
```
**Apply to:** `tests/test_app_settings.py` — any test exercising real `POST /admin/settings`
writes needs this pointed at a tmp_path DB before the request, same as every existing
`test_settings.py` test.

## No Analog Found

None. Every file in this phase's scope has a direct or near-direct existing analog — this
phase's own RESEARCH.md concludes the same ("almost entirely pattern-mirroring"). The one
piece with no prior in-repo precedent is the per-field multi-error validation loop
(`validate_only` called per key, collecting a `{key: reason}` map) — RESEARCH.md Pattern 3
supplies the target shape directly since no existing endpoint needed atomic multi-field
validation before this phase (`save_editor`'s pydantic validation is single-shot over the
whole payload, not per-field with a collected error map).

## Metadata

**Analog search scope:** `app/` (deps.py, auth.py, main.py, templates/, static/), `core/settings.py`,
`tests/` (test_app_auth.py, test_app_editor.py, test_settings.py)
**Files scanned:** 9 (all fully read; editor.html read in two non-overlapping ranges due to size —
lines 1-1083 then a targeted grep + read of lines 1195-1324 for the fetch/save functions)
**Pattern extraction date:** 2026-07-21
