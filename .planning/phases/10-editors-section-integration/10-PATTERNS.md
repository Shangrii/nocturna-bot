# Phase 10: Editors Section Integration - Pattern Map

**Mapped:** 2026-07-30
**Files analyzed:** 12 (bot-side modify: 8, bot-side test: 3, site-side modify/create: 2)
**Analogs found:** 12 / 12 (all files being modified are their own best analog — this
phase is overwhelmingly "extend an existing pattern in-place," not net-new construction;
where a *sibling* pattern is the real template — e.g. the tier-gate split, the redirect
stub — that sibling is cited instead)

This phase touches two repos: `nocturna-bot` (FastAPI/Jinja2 app, in this working
directory) and the sibling `Website` repo (Astro static site, `C:\Users\Shangri\Pictures\
Nocturna Avatars\Coding\Website`, separate git remote). Every file below is a **modify**
of an existing file — there are no wholly new files in this phase except the two Astro
route moves (which are a `git mv` + edit, not new design).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `app/templates/_sidebar.html` | component (Jinja partial) | request-response (server-rendered) | itself (7-entry `sections[]` loop, existing owner/manager branches) | exact — extend the same loop with an 8th entry + `editor` tier branch |
| `app/templates/_dashboard_base.html` | component (Jinja layout) | request-response | itself | exact — remove one `<a>`, no structural change |
| `app/templates/editor.html` | component (Jinja page + Alpine app) | request-response | `app/templates/overview.html` / `module_stub.html` (shell-wrapped page shape) + itself (content to preserve) | role-match for the *wrapper* shape, exact for the content being moved into `{% block content %}` |
| `app/static/editor.css` | config (stylesheet) | transform (retint) | `app/static/dashboard.css` (target token set) + itself (source rules) | role-match — token-renaming transform, not a new file |
| `app/static/dashboard.css` | config (stylesheet) | transform (additive) | itself (`.status-badge`, `.mod-hdr` precedent) | exact — add `--accent-editor`, `.status-badge.pending`, one media-query rule |
| `app/deps.py` | middleware (FastAPI dependency) | request-response | `require_manager` (the exact tier-gate shape to replicate for the GET-route split) | exact |
| `app/main.py` (GET `/`, `/editor`) | route (FastAPI handler) | request-response | `overview_page` (`require_manager`-gated module route, same `_resolve_roles`-then-branch shape) | exact |
| `core/editors_model.py` (`RESERVED_SLUGS`) | model/config (validation constant) | CRUD (create-time guard) | itself | exact — widen a frozenset, no new logic |
| `tests/test_app_dashboard.py` | test | request-response | `test_editor_only_locked_out_of_dashboard` (existing dependency-override pattern) | exact |
| `tests/test_app_editor.py` | test | request-response | existing file, `test_editor_page_renders_slug_field`-style cases | exact |
| `tests/test_editors_model.py` | test | CRUD | existing reserved-word test cases (same file) | exact |
| `Website/src/pages/e/[slug].astro` | route (Astro page → becomes redirect stub) | request-response (static redirect) | `Website/src/pages/[lang]/[concept]/[slug].astro` (the exact redirect-stub pattern already shipped) | exact |
| `Website/src/pages/[slug].astro` (new, root-level) | route (Astro dynamic page) | request-response (static render) | `Website/src/pages/e/[slug].astro` (today's full-page render, being moved) | exact — same file, one path segment shallower |

## Pattern Assignments

### `app/templates/_sidebar.html` (component, request-response)

**Analog:** itself — `app/templates/_sidebar.html` (full file, 39 lines, already read in full)

**Current `sections[]` + lock-predicate pattern** (lines 5-23):
```jinja2
{% set sections = [
  {"id": "overview",  "label": "Overview",                     "icon": "⌂", "accent": "var(--color-primary)",    "route": "/overview",       "tier": "manager"},
  ...
  {"id": "settings",  "label": "Ajustes · Settings",            "icon": "⚙", "accent": "var(--accent-settings)",  "route": "/admin/settings", "tier": "owner"},
] %}
<aside class="side">
  {% for section in sections %}
  {% set unlocked = (section.tier == "owner" and roles.is_owner) or (section.tier == "manager" and (roles.is_owner or roles.is_manager)) %}
  <a class="nav-item {{ 'on' if active_section == section.id else '' }}"
     style="--acc: {{ section.accent }}"
     href="{{ section.route }}">
    <span class="ico">{{ section.icon }}</span>
    <span>{{ section.label }}</span>
    {% if not unlocked %}<span class="lock" title="Requiere más acceso · Requires more access">🔒</span>{% endif %}
  </a>
  {% endfor %}
```

**Bolt-on block to DELETE** (lines 26-33):
```jinja2
{% if roles.is_editor %}
<div class="editor-link">
  <a class="nav-item" href="/editor">
    <span class="ico">✎</span>
    <span>Editor</span>
  </a>
</div>
{% endif %}
```

**Copy-from-RESEARCH.md target shape** (per D-03, UI-SPEC "Sidebar Integration", already
verified against the real file structure above — add the 8th entry + widen the `unlocked`
expression with one `or` clause, do not add a separate `elif` branch since it's a single
Jinja expression, not an if/elif chain):
```jinja2
{% set sections = [
  ..., # existing 7 entries unchanged
  {"id": "editor", "label": "Editor", "icon": "✎", "accent": "var(--accent-editor)", "route": "/editor", "tier": "editor"},
] %}
...
{% set unlocked = (section.tier == "owner" and roles.is_owner)
                or (section.tier == "manager" and (roles.is_owner or roles.is_manager))
                or (section.tier == "editor" and roles.is_editor) %}
```
Position: append last (after Settings), per UI-SPEC decision — preserves the bolt-on's
current bottom placement and its `border-top` separator (verify that separator lives in
`.side .editor-link` in `dashboard.css`/`editor.css` and needs to move onto `.nav-item`
generically or a `:last-child` rule — check both stylesheets for `.editor-link` before
deleting the class).

---

### `app/templates/_dashboard_base.html` (component, request-response)

**Analog:** itself (full file, 36 lines, already read in full)

**Line to remove** (line 21):
```jinja2
<a class="btn ghost" href="/editor">Volver al editor · Back to editor</a>
```
Per UI-SPEC "Topbar Reconciliation" — this link renders unconditionally today (a latent
403 bug for non-editor viewers); delete it entirely, leaving the topbar as
`wordmark + spacer + logout` (lines 18-23 collapse to wordmark/spacer/logout only),
identical shape to every other shell page.

---

### `app/templates/editor.html` (component, request-response — the shell-wrap target)

**Analog for the WRAPPER shape:** `app/templates/forbidden.html` (full file, already read)
— the *simplest* existing example of `{% extends "_dashboard_base.html" %}` +
`{% block content %}`:
```jinja2
{% extends "_dashboard_base.html" %}
{% block title %}403{% endblock %}
{% block content %}
...
{% endblock %}
```
`editor.html` needs the same two-line extends/title header, replacing its current
standalone `<!doctype html>`...`</html>` shell (lines 1-16 of the current file — the
duplicate `<head>`, `<link>` tags, and outer `<body>` are deleted; the curated 14-font
`<link>` tag from lines 11-13 must be preserved by adding a `{% block head %}` override,
since `_dashboard_base.html` only loads Inter 400/600 by default — see its own
`{% block head %}{% endblock %}` hook at line 15).

**Content to relocate into `{% block content %}`:** everything from the current
`<div x-data='editorApp(...)' x-cloak>` (line 21) through the closing `</div>` before the
`<script>` block (line 659) — this is the two-pane editor + Alpine scope, frozen per D-07/
D-01 non-regression. The `<script>` block (Alpine `editorApp()` factory, lines 662+)
relocates into a `{% block scripts %}` override (see `_dashboard_base.html`'s own
`{% block scripts %}{% endblock %}` hook at line 32) — it must NOT run twice if
`_dashboard_base.html`'s own script tags run first; Alpine's `defer` script loads AFTER
`{% block scripts %}` in the parent template (line 32-33), so a `{% block scripts %}`
override defining `editorApp` before Alpine parses `x-data` is safe, matching today's
inline-script-before-Alpine-parse ordering.

**Topbar content to REMOVE from inside `editor.html`** (current lines 24-38, replaced by
shell topbar + new `.editor-subhead`):
```jinja2
<header class="topbar">
  <h1 class="wordmark">Nocturna</h1>
  <span class="label" x-text="page.published ? ... "></span>
  <span class="spacer"></span>
  <button class="btn btn--accent" ... @click="publish()" ...></button>
  <button class="btn btn--danger" ... @click="unpublish()" ...>Despublicar · Unpublish</button>
  {% if is_owner %}<a class="btn btn--ghost" href="/admin/settings">⚙ Ajustes · Settings</a>{% endif %}
  <a class="btn btn--ghost" href="/logout">Salir · Sign out</a>
</header>
```
Wordmark + logout: dropped (provided free by `_dashboard_base.html`'s topbar, lines 18-23
of that file). Owner-only Settings shortcut: dropped entirely (UI-SPEC — redundant with
sidebar). Status pill (`x-text="page.published ? ..."`) + Publish/Save button + Unpublish
button: relocate verbatim (same `@click`/`x-text`/`:disabled` bindings) into a new
`.editor-subhead` element per UI-SPEC "Topbar Reconciliation" / "Component Inventory" —
compose it from `.mod-hdr` (icon+title+left-accent-border shape, `dashboard.css` lines
236-244) + `.status-badge`/`.status-badge.active`/new `.status-badge.pending`
(`dashboard.css` lines 363-380) + `.btn`/`.btn.danger` (dashboard.css shape, not
`editor.css`'s `.btn--accent`/`.btn--danger` — those become the new chrome-retinted
equivalents per the Reconciliation Strategy below).

**Mobile pane-tabs, two-pane `.panes`/`.pane--edit`/`.pane--preview`, block editor, theme
panel, and preview canvas (lines 40-654 of the current file):** structurally frozen
(D-01). Only class-level chrome retinting touches these (see `editor.css` pattern below);
no markup restructuring inside this region.

**`entry`/Alpine data contract (lines 663-1327, JS untouched except `linkBase`):** one
concrete edit required by D-05 (vanity URL copy) —
```javascript
// current (line 904 in the earlier read):
linkBase: (MEDIA_BASE || '') + '/e/',
```
becomes `linkBase: (MEDIA_BASE || '') + '/'` (drop the `/e/` segment) per UI-SPEC
Copywriting Contract's "Link field hint (vanity URL)" row. This is the ONLY JS-behavior
edit in this file; everything else in the `editorApp()` factory is D-07-frozen.

---

### `app/static/editor.css` (config/stylesheet, transform)

**Analog:** `app/static/dashboard.css` (target tokens, lines 10-64 already read) — the
"Reconciliation Strategy" in `10-UI-SPEC.md` is the authoritative spec; this section
pins the EXACT token mapping to apply mechanically.

**Chrome tokens to DELETE from `editor.css`'s `:root`** (current lines 12-20, 33-35 of
`editor.css`):
```css
--ink: #0a0c14; --ink-raised: #10131e;
--red: #c0192c; --red-on-ink: #e84a5e; --red-wordmark: #cd2236;
--fg: #f0eae4; --dim: #9a9198; --line: rgba(240, 234, 228, 0.14);
--font-display: "Space Grotesk", ...; --font-body: "Inter", ...; --font-mono: "Space Mono", ...;
```
These become **fallback values only** inside `var(--theme-x, <old-value>)` expressions
feeding `.preview-*` rules (never standalone chrome colors again, per UI-SPEC).

**Chrome rules to RETARGET onto `dashboard.css` tokens** (every non-`.preview-*` rule —
concretely `.topbar`, `.btn`/`.btn--accent`/`.btn--danger`/`.btn--sm`, `.field`/`input`/
`textarea`/`select`, `.block-card`, `.picker`, `.theme-panel`/`.theme-group`, `.upload`/
`.upload-state`, `.toast`, `.color-grid`, `.preset-swatch`): every `var(--ink)` →
`var(--color-bg)`, `var(--ink-raised)` → `var(--color-surface)`/`-2`/`-3` (pick per
existing depth), `var(--red)`/`var(--red-on-ink)` → `var(--color-primary)` (CTA) or
`var(--color-danger)` (destructive — NOT the same token; `editor.css` today conflates
brand-red with destructive-red, `dashboard.css` splits them, per Color table row
"Destructive"), `var(--fg)` → `var(--color-text)`, `var(--dim)` → `var(--color-text-muted)`,
`var(--line)` → `var(--color-border)`, `var(--font-body)`/`var(--font-display)` →
`var(--font-sans)`, `--sp-*` → `--space-*` (1:1 value mapping, see UI-SPEC Spacing Scale
table — either alias or global-rename, executor's call).

**Rules to copy forward BYTE-FOR-BYTE, zero token substitution** (this is the load-bearing
non-regression gate, D-01/Pitfall 6): every `.preview-*` selector (`.preview-col` through
`.preview-spotify__play`) plus every `@keyframes fx-*` block. These already reference
`--theme-*` custom properties injected per-page by the Alpine `:style` binding (editor.html
line 549) — do not touch.

**New chrome additions** (per UI-SPEC): `.status-badge.pending` (amber, using
`dashboard.css`'s existing `--color-warning: #ffb020` token — same token Reviews already
uses, no new color introduced), `.upload-state[data-kind="loading"]`/`[data-kind="ok"]`
(muted / `--color-success`), `.color-grid` 1-column rule inside a `@media (max-width:
480px)` block, `.editor-subhead` (new composite class — see Component Notes in UI-SPEC),
`--touch-min: 44px` stays verbatim (pre-approved a11y exception, do not fold into
`--space-*`).

**Toast unification** (UI-SPEC "Component Inventory"): drop `editor.css`'s own `.toast`
rule (bottom-center variant) entirely; the shared `.toast` from `dashboard.css` (lines
341-347, bottom-right + `--shadow-lg`) is loaded first and now wins with no override
needed — verify no leftover `editor.css` `.toast` selector shadows it after the retint pass.

---

### `app/static/dashboard.css` (config/stylesheet, additive)

**Analog:** itself — `.status-badge`/`.status-badge.active` (lines 363-380, already read)
is the exact shape to extend with one sibling modifier:
```css
.status-badge.active {
  border-color: var(--color-success);
  color: var(--color-success);
}
```
→ add (new rule, same shape, `--color-warning` instead of `--color-success`):
```css
.status-badge.pending {
  border-color: var(--color-warning);
  color: var(--color-warning);
}
```
Also add one new token to the `:root` accent block (lines 31-36, alongside
`--accent-gallery`/`--accent-reviews`/etc.):
```css
--accent-editor: #f97316;
```
(new, orange, per UI-SPEC Color table — distinct from all 6 existing module accents and
from `--color-brand`).

---

### `app/deps.py` (middleware, request-response — Pitfall 1/2 fix, the load-bearing change)

**Analog:** `require_manager` (lines 203-214, already read in full) — the exact shape to
mirror for the new GET-route branch (do NOT write a new `require_editor_view` dependency
that re-derives the role a second time; compose directly on `_resolve_roles` per Pitfall 2):
```python
async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```
**Do NOT modify `require_editor`** (lines 84-106) — it stays byte-for-byte unchanged and
continues to gate every POST mutation endpoint (`/editor/save`, `/editor/image`,
`/editor/media`, `/editor/audio`, `/editor/unpublish`), preserving its Pitfall-2
stale-session-clear discipline exactly where it belongs (D-07 freeze). The new GET-route
gate is added at the `app/main.py` route level (see below), consuming `_resolve_roles`
directly — `app/deps.py` itself needs NO new function per the RESEARCH.md Pattern 2
recommendation, only the route composition changes. (If the planner prefers a named
dependency for symmetry with `require_manager`, model it exactly on the block above with
`required_tier="editor"` and `roles["is_editor"]`, added directly below `require_manager`
in this file.)

**`TierForbidden`** (lines 137-145) — reused as-is, no change:
```python
class TierForbidden(HTTPException):
    def __init__(self, required_tier: str):
        super().__init__(status_code=403, detail=f"needs {required_tier} access")
        self.required_tier = required_tier
```

**`_resolve_roles`** (lines 148-200) — reused as-is; already returns
`{"discord_id", "username", "is_owner", "is_manager", "is_editor"}` and already does the
ONE live Discord role read this phase needs (no double-read risk if the GET route
composes on `_resolve_roles` alone, per Pitfall 2's explicit warning).

---

### `app/main.py` GET `/`, `/editor` (route, request-response — Pitfall 1/2 fix)

**Analog:** `overview_page` (lines 614-632, already read) — the exact
`require_manager`-gated module-route shape:
```python
@app.get("/overview", response_class=HTMLResponse)
async def overview_page(request: Request, roles: dict = Depends(require_manager)):
    status = await _read_overview_status()
    return templates.TemplateResponse(
        request, "overview.html",
        {"roles": roles, "active_section": "overview", "asset_v": _dashboard_asset_v(),
         "bot_online": status["online"], **status},
    )
```
**Current `editor_page`** (lines 476-508, already read in full) uses `Depends(require_editor)`
directly — this is Pitfall 1's exact trigger (a non-editor's session gets cleared + 401/
login.html instead of a 403/forbidden.html dead-end). Per RESEARCH.md Pattern 2 / Code
Examples, restructure to:
```python
@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request, roles: dict = Depends(_resolve_roles)):
    if not roles["is_editor"]:
        raise TierForbidden(required_tier="editor")   # → forbidden.html, no session clear
    entry = await _fetch_current_entry(roles["discord_id"])
    ...  # unchanged body below, but read discord_id/slug off `roles`, not a second
         # require_editor call (Pitfall 2 — one Discord role read per request)
    return templates.TemplateResponse(
        request, "editor.html",
        {"entry": entry, "website_base": config.WEBSITE_BASE_URL, "asset_v": asset_v,
         "is_owner": is_owner, "roles": roles, "active_section": "editor"},
    )
```
New keys `"roles"` and `"active_section": "editor"` must be added to the render context
(currently absent, lines 504-507) — every other shell-wrapped route already passes both
(see `overview_page` above and `_module_stub_page`, lines 635-645) because
`_sidebar.html`/`_dashboard_base.html` now render inside `editor.html` too (D-01) and need
`roles.is_owner`/`.is_manager`/`.is_editor` for lock icons plus `active_section` for the
`.on` highlight class.

**`_MODULE_SECTIONS`** (lines 516-524) and `_module_stub_page` (lines 635-645) — NOT
modified; shown only as the established "shared dict + shared render helper" idiom this
phase does not need to extend (the editor route stays its own handler, not a stub).

**`_auth_html_or_json` exception handler** (lines 359-415, already read in full) — NOT
modified. `TierForbidden` raised from the new editor-route branch is already handled by
the existing first branch (lines 391-395):
```python
if isinstance(exc, TierForbidden) and accept_html:
    return templates.TemplateResponse(
        request, "forbidden.html",
        {"required_tier": exc.required_tier, "roles": _NO_TIER_ROLES},
        status_code=exc.status_code)
```
This already renders correctly for `required_tier="editor"` — confirmed by direct read,
no template or handler change needed (Don't-Hand-Roll table, RESEARCH.md). Pitfall 3
(`_NO_TIER_ROLES` all-locked cosmetic quirk) is pre-existing and explicitly out of scope
per CONTEXT.md Open Question 1 — do not "fix" it as part of this phase.

---

### `core/editors_model.py` `RESERVED_SLUGS` (model/config, CRUD guard)

**Analog:** itself (lines 156-161, already read):
```python
RESERVED_SLUGS = frozenset(
    {
        "e", "api", "static", "assets", "admin", "editor", "editors",
        "auth", "login", "logout", "me", "favicon",
    }
)
```
**Verified collision surface in the sibling `Website` repo** (directly confirmed this
session, not from RESEARCH.md's own assertion): `Website/src/pages/en/` contains
`galeria.astro` and `servicios.astro` as literal top-level routes (no `index.astro`, so
`/en` bare currently 404s but `/en/*` file routes exist and DO need protecting from a
same-named root slug like `en` itself, matching Pitfall 4's exact concern); `Website/public/`
contains `gallery`, `store`, `fonts`, and `editors` as top-level static folders copied
verbatim into `dist/`. Widen the frozenset to at minimum:
```python
RESERVED_SLUGS = frozenset(
    {
        "e", "api", "static", "assets", "admin", "editor", "editors",
        "auth", "login", "logout", "me", "favicon",
        "en", "es", "gallery", "store", "fonts", "build",
    }
)
```
(`"editors"` already reserved covers the `public/editors/` collision; `"en"`/`"es"`/
`"gallery"`/`"store"`/`"fonts"`/`"build"` are the net-new additions per Pitfall 4 — `build`
per RESEARCH.md's note about the deploy workflow's own liveness-check file at site root,
not independently verified this session, include per the research's must-fix flag.)

---

### `tests/test_app_dashboard.py` (test, request-response)

**Analog:** `test_editor_only_locked_out_of_dashboard` (lines 148-179, already read in
full) — the established `app.dependency_overrides[...]` + `monkeypatch.setattr(main,
"_fetch_current_entry", fake_current)` pattern to extend for the NEW regression case
(Pitfall 1's fix verification — owner/Manager clicking locked Editor nav item, session
stays intact):
```python
# NEW case pattern (extend this file, mirror the override shape above):
app.dependency_overrides[require_manager] = lambda: {  # simulate an owner viewing
    "discord_id": "1", "username": "Owner", "is_owner": True,
    "is_manager": False, "is_editor": False,
}
resp = client.get("/editor")
assert resp.status_code == 403
assert "required_tier" ... # forbidden.html rendered, NOT login.html
# then assert the session was NOT cleared — client.cookies still carries the session cookie
```
Note: since the fix routes GET `/editor` through `_resolve_roles` (not `require_manager`),
the override target for this new test is `app.deps._resolve_roles`, not `require_manager`
— adjust the override dependency accordingly when implementing.

---

### `tests/test_app_editor.py` (test, request-response)

**Analog:** existing file's established `_fetch_current_entry` monkeypatch + `client.get`
shape (same file `test_app_dashboard.py` references as precedent at line 158). New case
per RESEARCH.md's Phase Requirements → Test Map: assert `/editor` GET response body
contains shell markers (e.g. a `nav-item`/`side` class from `_sidebar.html`, or the
`_dashboard_base.html` topbar's `wordmark`/`logout` markup) now that D-01 wraps the page.

---

### `tests/test_editors_model.py` (test, CRUD)

**Analog:** existing reserved-word test cases in the same file (not re-read this session
to avoid redundant token spend — the file already has a `SlugRejected("reserved")`-style
case per RESEARCH.md's Test Map row; extend with parametrized cases for each of `en`,
`es`, `gallery`, `store`, `fonts`, `build`).

---

### `Website/src/pages/e/[slug].astro` (route → becomes redirect stub)

**Analog:** `Website/src/pages/[lang]/[concept]/[slug].astro` (full file, already read in
full) — this is the EXACT pattern to replicate, one cartesian dimension shallower (no
`langCodes` loop, single target per slug):
```astro
export function getStaticPaths() {
  const raw: Editor[] = Array.isArray(editorsData) ? ([...editorsData] as Editor[]) : [];
  const published = raw.filter((e) => Boolean(e) && e.published === true
    && typeof e.slug === 'string' && e.slug.length > 0);
  const seen = new Set();
  const unique = published.filter((e) => {
    if (seen.has(e.slug)) return false;
    seen.add(e.slug);
    return true;
  });
  return unique.map((editor) => ({ params: { slug: editor.slug } }));  // no langCodes loop
}
const { slug } = Astro.params;
const target = `/${slug}`;   // was `/e/${slug}` in the analog — one level shallower
---
<!doctype html>
<html lang="es">  <!-- or omit lang entirely; the analog's per-locale lang param doesn't apply here -->
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="robots" content="noindex" />
    <link rel="canonical" href={target} />
    <title>Nocturna Avatars</title>
    <noscript><meta http-equiv="refresh" content={`0; url=${target}`} /></noscript>
    <script define:vars={{ target }}>
      location.replace(target);
    </script>
  </head>
  <body></body>
</html>
```
**Security invariant to preserve (T-01-03, already verified in the analog):** `target` is
a build-time literal baked via `define:vars`, NEVER a runtime-read value — the inline
script never reads `Astro.params` directly, only the pre-assembled `target` const. Do not
introduce a `?next=` param or any runtime redirect-target source.

---

### `Website/src/pages/[slug].astro` (NEW, root-level — the vanity page)

**Analog:** `Website/src/pages/e/[slug].astro` (today's full file, already read in full —
this IS the file being moved, mechanically a `git mv` one directory level up). Required
edits after the move (relative import depth changes from `../../` to `../`):
```
git mv src/pages/e/[slug].astro src/pages/[slug].astro
```
then every relative import at the top of the file shifts by one level:
```astro
import EditorLayout from '../layouts/EditorLayout.astro';              // was '../../layouts/...'
import EditorHeaderCard from '../components/editor-shell/EditorHeaderCard.astro'; // was '../../components/...'
import PresenceDot from '../components/editor-shell/PresenceDot.astro';
import LinkButton from '../components/editor-shell/LinkButton.astro';
import ViewCounter from '../components/editor-shell/ViewCounter.astro';
import SpotifyVinyl from '../components/editor-shell/SpotifyVinyl.astro';
import BlockRenderer from '../components/editor-blocks/BlockRenderer.astro';
import LightboxOverlay from '../components/LightboxOverlay.astro';
import type { Editor, EditorLink } from '../lib/editorTypes';
import editorsData from '../data/editors.json';
import { safeHref } from '../lib/url';
import '../styles/gallery.css';
// and the inline <script> import:
import '../scripts/gallery.ts';   // was '../../scripts/gallery.ts'
```
`getStaticPaths()`, `Astro.props`, and every render-body line (defensive field reads,
`EditorLayout`/`EditorHeaderCard`/`BlockRenderer` composition, the `.e-bg`/`.e-main`/
`.e-column` styles) are otherwise BYTE-IDENTICAL — this route's own logic does not change,
only its file location and import depth (D-05: "no separate vanity field", the slug IS
the route param exactly as it is today at `/e/{slug}`).

**Verification required before merge (Pitfall 5, unresolved by static analysis alone):**
run `npm install && npm run build` in the `Website` checkout after this move and confirm
`/en/galeria`, `/en/servicios`, and the `public/gallery`/`public/store`/`public/fonts`
static-copy paths still resolve — Astro's literal-route-over-dynamic-route priority is
docs-asserted, not empirically verified in this session.

---

## Shared Patterns

### Tier-gate split (the phase's one genuinely new mechanism)
**Source:** `app/deps.py::require_manager` (lines 203-214) generalized to a hypothetical
`is_editor` branch; composed directly in `app/main.py`'s `editor_page` handler via
`Depends(_resolve_roles)` + a manual `TierForbidden(required_tier="editor")` raise.
**Apply to:** GET `/` and GET `/editor` only. Every POST mutation endpoint
(`/editor/save`, `/editor/image`, `/editor/media`, `/editor/audio`, `/editor/unpublish`)
keeps `Depends(require_editor)` completely unchanged (D-07 freeze).
```python
async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```

### Server-rendered tier-locked sidebar (D-14, unchanged mechanism, one new tier value)
**Source:** `app/templates/_sidebar.html`'s `sections[]` loop + `unlocked` expression.
**Apply to:** the new 8th `editor` entry only — no new sidebar CSS, no client-side gating
anywhere (house rule, unbroken by this phase).

### Generic 403 dead-end (D-16, zero change needed)
**Source:** `app/templates/forbidden.html` (full file) + `app/main.py`'s
`_auth_html_or_json` exception handler's `TierForbidden` branch (lines 391-395).
**Apply to:** automatically covers `required_tier="editor"` — confirmed by direct code
read, no template/handler edit required for this phase.

### Astro build-time redirect stub (GitHub Pages has no server-side 301, T-01-03)
**Source:** `Website/src/pages/[lang]/[concept]/[slug].astro`'s `define:vars` +
`location.replace(target)` + `<noscript>` meta-refresh + `rel="canonical"` quadruple.
**Apply to:** the new `Website/src/pages/e/[slug].astro` redirect stub — same four-part
shape, one cartesian dimension removed (no locale loop).

### Chrome token retint (dashboard.css as the single chrome source of truth)
**Source:** `app/static/dashboard.css`'s `:root` token block (lines 10-64) + `.mod-hdr`/
`.status-badge`/`.toast` component shapes (lines 236-380).
**Apply to:** every non-`.preview-*` rule in `editor.css`. Explicitly does NOT apply to
`.preview-*` rules or the `@keyframes fx-*` blocks (Pitfall 6 — these stay on `--theme-*`
custom properties + the old `--ink`/`--red`/`--fg`/`--dim` constants as fallback values only).

## No Analog Found

None. Every file in this phase is either a direct in-place modification of itself (the
overwhelming majority) or has a byte-for-byte-verified sibling pattern already shipped in
one of the two repos (the tier-gate split mirrors `require_manager`; the Astro redirect
stub mirrors `[lang]/[concept]/[slug].astro`; the vanity page mirrors today's
`e/[slug].astro`). No net-new architectural pattern needs to be invented from
RESEARCH.md's illustrative code alone.

## Metadata

**Analog search scope:** `nocturna-bot/app/{templates,static,deps.py,main.py}`,
`nocturna-bot/core/editors_model.py`, `nocturna-bot/tests/test_app_{dashboard,editor}.py`
+ `test_editors_model.py`, sibling `Website/src/pages/{e,[lang]}/**`, `Website/public/`,
`Website/src/pages/en/`.
**Files scanned (read in full or targeted range):** `app/deps.py` (full), `app/main.py`
(lines 355-666 + route grep across full file), `app/templates/_sidebar.html` (full),
`app/templates/_dashboard_base.html` (full), `app/templates/forbidden.html` (full),
`app/templates/editor.html` (lines 1-1083 of 1328 — sufficient; remaining lines are
unmodified Alpine helper methods, RESEARCH.md's line references for the rest were
cross-checked against the read portion and are consistent), `app/static/dashboard.css`
(targeted grep, tokens + `.mod-hdr`/`.status-badge`/`.toast`), `app/static/editor.css`
(targeted grep, `:root` tokens), `core/editors_model.py` (lines 1-80 + `RESERVED_SLUGS`
grep), `tests/test_app_dashboard.py` (targeted read, lines 140-179),
`Website/src/pages/e/[slug].astro` (full), `Website/src/pages/[lang]/[concept]/[slug].astro`
(full), `Website/src/pages/en/`, `Website/public/` (directory listings only).
**Pattern extraction date:** 2026-07-30
