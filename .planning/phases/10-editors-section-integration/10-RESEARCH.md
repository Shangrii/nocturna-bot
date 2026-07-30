# Phase 10: Editors Section Integration - Research

**Researched:** 2026-07-30
**Domain:** FastAPI/Jinja2 dashboard-shell integration + static-site (Astro/GitHub Pages) vanity-URL routing
**Confidence:** HIGH (all core findings verified by direct code read of both repos — `nocturna-bot` and the sibling `Website` Astro checkout — not from training-data assumptions)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Shell integration (the editor page inside the shell)**
- **D-01: Full shell wrap.** `editor.html` is restructured to extend `_dashboard_base.html`
  (shell topbar + `_sidebar.html` rail); the two-pane block editor becomes the `content`
  block. "Everyone operates the same shell." Research/planning must resolve `editor.css`
  ↔ `dashboard.css` coexistence (scope/namespace or fold editor styles onto dashboard
  tokens) without regressing the working two-pane editor + live preview.
- **D-02: Full locked sidebar for editors.** An editor sees all 7 operational sections
  with 🔒 icons **plus** their Editor section unlocked — identical shell chrome to
  owner/Manager (uphold Phase 3 D-14 server-rendered lock state + D-16 `forbidden.html`
  dead-end when an editor clicks a locked item). No reduced/editor-only sidebar.
- **D-03: Editor becomes a real 8th data-driven section, editor-only.** Promote the
  current bolt-on `{% if roles.is_editor %}` `.editor-link` block in `_sidebar.html` into
  a proper `sections[]` entry `{id:"editor", tier:"editor", route:"/editor"}` with uniform
  lock logic. Access is **editor-tier only** — an owner/Manager *without* the editor role
  does not see/reach it (honors Phase 3's additive-not-exclusive tier rule: Manager+editor
  ⇒ modules AND editor page; Manager alone ⇒ no editor page). Sidebar lock predicate must
  gain an `is_editor` branch for the new tier.
- **Editor landing:** editor-only post-login continues to `/editor`, which now renders
  **in-shell**. `_dashboard_base.html`'s existing "Volver al editor · Back to editor"
  topbar link and the shell↔editor navigation should be reconciled with the new in-shell
  editor section (planner decides exact nav wording; the route contract `/editor` + `/`
  stays).

**Vanity URLs (new capability — EDIT-02)**
- **D-04: In scope for Phase 10.** Short public URLs for editor pages
  (`nocturna-avatars.site/{slug}`).
- **D-05: Slug IS the vanity URL, with redirect of old links.** Reuse the editor's
  already-chosen slug (`core/editors_model.resolve_slug` — normalized, reserved-word
  guarded, unique). The public URL becomes `nocturna-avatars.site/{slug}`; **old/long
  editor-page links 301-redirect** to the vanity URL so nothing an editor already shared
  breaks. No separate vanity field.
- **Research gap (public site):** the public site is 100% static Astro on GitHub Pages
  (PLAT-02 — the app/bot only *commits* `editors.json` + media to the site repo, never
  serves it). Phase 10 planning must work out the Astro-side mechanism (e.g. a
  `[slug].astro` dynamic route generated from `editors.json`, plus the redirect handling
  for legacy paths) and how the app/bot's existing cross-repo commit flow
  (`core/github_publish.sync_editors`) drives it. Confirm reserved-word/route-collision
  safety against existing public-site routes.

**Editor-surface polish (Integrate + polish)**
- **D-06: Match dashboard look AND targeted UX cleanups.** Beyond wrapping, make the
  editor visually consistent with the shell (shared `dashboard.css` tokens/topbar/type/
  spacing) **and** apply targeted UX improvements — candidates: clearer save/publish
  states, upload feedback, mobile layout. Each concrete change is enumerated and approved
  in the **UI-SPEC pass** before planning. *(Already done — see `10-UI-SPEC.md`, approval
  pending sign-off.)*
- **D-07: SC2 workflow-parity guard.** Polish may change chrome/visuals/UX affordances,
  but the underlying editor **behavior** must stay functionally identical: OAuth flow,
  `/editor/save` (publish-on-save, D-13), `/editor/image` `/editor/media` `/editor/audio`
  upload+re-encode contracts, self-unpublish, and the IDOR/path-traversal guards
  (`require_editor` choke point, session-forced `discordId`, server-side `mediaId`).

### Claude's Discretion
- Exact `editor.css`/`dashboard.css` reconciliation strategy, sidebar section ordering
  (editor entry placement), and nav wording — planner/UI-SPEC decide within the decisions
  above. **(UI-SPEC has already resolved these — see `10-UI-SPEC.md`: retint-chrome/
  preserve-preview-canvas split, position 8/last, "Back to editor" topbar link removed.)**

### Deferred Ideas (OUT OF SCOPE)
None — the owner chose to pull every candidate (vanity URLs, counter-app parity, editor
polish) INTO Phase 10 for a full-experience release. The only items held back are strictly
outside EDIT scope and unchanged from PROJECT.md Out-of-Scope (multi-guild, secret editing,
log viewer, Overview quick actions).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EDIT-01 | The editors presentation section (`editors.nocturna-avatars.site`) is integrated as a dashboard section with its own access tier. | Architecture Patterns (single-app shell wrap), Common Pitfalls #1-#3 (tier-gate/session-clear conflict), Code Examples (sidebar entry + route gate) |
| EDIT-02 *(bookkeeping addition per CONTEXT.md "SCOPE EXPANDED" — not yet in REQUIREMENTS.md; planner/transition should add it)* | Vanity URLs `nocturna-avatars.site/{slug}` for editor pages, with legacy `/e/{slug}` links 301-redirecting. | Architecture Patterns (Astro static-site redirect mechanism), Don't Hand-Roll (native Astro `redirects` config + existing redirect-stub precedent), Common Pitfalls #4-#6 (reserved-word gaps, GH Pages has no server redirects) |

**Note for planner:** REQUIREMENTS.md currently lists only EDIT-01 mapped to Phase 10;
CONTEXT.md's Phase Boundary flags that EDIT-02 (vanity URLs) needs to be added and
EDIT-01/SC2 wording softened from "unchanged" to "workflow parity." This research treats
both EDIT-01 and the vanity-URL work as in-scope per the locked CONTEXT.md decisions,
matching ROADMAP.md's own scope-expansion flag.
</phase_requirements>

## Summary

This phase has two genuinely separate technical surfaces, and conflating them is the
biggest risk: (1) **an in-process Jinja2/FastAPI template restructuring** inside
`nocturna-bot` (the single app already serving both the shell and the standalone editor
page — no new service, no new mount), and (2) **a static-site routing change** in the
*sibling* `Website` repo (Astro 7.0.3, output: static, deployed to GitHub Pages via a
force-pushed `gh-pages` branch, custom domain via `CNAME`). Everything needed for both
surfaces already exists in the codebase in a directly reusable, previously-audited form:
the shell's `sections[]`/lock-icon pattern (`_sidebar.html`), the dashboard token system
(`dashboard.css`), and — critically — **the exact legacy-redirect pattern this phase
needs already ships in the Website repo** (`src/pages/[lang]/[concept]/[slug].astro`,
a build-time meta-refresh + `location.replace` stub redirecting the *previous*
`/es/editores/<slug>` · `/en/editors/<slug>` locale-prefixed URLs to today's `/e/<slug>`).
Phase 10's vanity-URL work is mechanically the same migration one level shallower:
generate one more redirect stub per published editor (`/e/<slug>` → `/<slug>`) and move
the full profile page from `src/pages/e/[slug].astro` to a new root-level
`src/pages/[slug].astro`.

The single highest-risk, concrete finding from reading `app/deps.py`/`app/auth.py` is
that **`require_editor`'s existing session-clear-on-role-loss behavior (Pitfall 2, D-08)
will fire on the wrong population once the "Editor" sidebar item is visible-but-locked to
every owner/Manager** (D-02's full locked sidebar): clicking it as a non-editor currently
means `has_editor_role()` returns `False`, the whole session is **cleared** (logging the
owner/Manager out of the *entire dashboard*, not just denied this one section), and the
denial renders `login.html`, not the `forbidden.html` dead-end D-16/D-02 require. This is
a genuine implementation gap that must be fixed as part of the route-gate work, not a
hypothetical edge case — see Common Pitfalls #1.

**Primary recommendation:** Treat this phase as two independent workstreams that share one
data contract (`editors.json`'s `slug`/`published` fields, already the transport's source
of truth): (A) `nocturna-bot` template/route work — extend `editor.html` off
`_dashboard_base.html`, promote the sidebar entry, and split the `/editor` GET route's tier
gate from its mutation-endpoint gate so a non-editor's click never clears their session; (B)
`Website` Astro work — move the profile page to `src/pages/[slug].astro`, convert
`src/pages/e/[slug].astro` into a redirect stub using the exact pattern already proven at
`src/pages/[lang]/[concept]/[slug].astro`, and widen `RESERVED_SLUGS` (bot-side) to cover
the public site's actual top-level routes/static folders, which today it does not.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Dashboard shell chrome (topbar/sidebar/lock icons) | Frontend Server (SSR, Jinja2) | — | Server-rendered per Phase 3 D-14; no client-side gating anywhere in this app |
| Tier resolution (owner/Manager/editor) | API/Backend (`app/deps.py`) | — | Single live bot-token Discord role read per request, shared via `Depends(..., use_cache=True)` |
| Editor block-editor UI (two-pane + live preview) | Browser/Client (Alpine.js) | Frontend Server (Jinja2 template) | Alpine owns in-page reactive state; Jinja2 renders the initial `entry` payload server-side |
| Editor page validation (`ThemeModel`, block union, slug) | API/Backend (`core/editors_model.py`) | — | Server-side Pydantic gate every save passes through; the "don't trust the client" boundary |
| Cross-repo publish commit (`editors.json` + media) | API/Backend (`core/github_publish.py`) | — | GitHub Git Data API, atomic blob→tree→commit→ref; owns no rendering |
| Public editor page render (`/{slug}`) | CDN/Static (Astro build → GitHub Pages) | — | 100% static output; the admin app never serves this, only commits data to it (PLAT-02) |
| Vanity-URL legacy redirect (`/e/{slug}` → `/{slug}`) | CDN/Static (Astro build-time redirect stub) | — | GitHub Pages has no server-side redirect capability; must be a build-time static HTML stub, same as the existing `/es/editores/<slug>` legacy-route precedent |
| View counter (`/api/views/<slug>`) | API/Backend (`app/counter_app.py`, separate systemd unit) | — | Deliberately isolated from the admin app's OAuth/session machinery (D-25); unaffected by this phase |

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────────────────────────┐
                          │   editors.nocturna-avatars.site (Caddy)      │
                          │   ONE FastAPI app (app/main.py), uvicorn      │
                          │   127.0.0.1:8770                              │
                          │                                               │
  staff browser  ───GET──▶│  /login, /auth/callback   (app/auth.py)      │
                          │       │ OAuth2 + bot-token role read           │
                          │       ▼                                       │
                          │  session cookie {discord_id, username, slug}  │
                          │       │                                       │
                          │       ├─▶ /overview,/gallery,/reviews,...     │
                          │       │     (require_manager, 6 modules)      │
                          │       │     _dashboard_base.html + _sidebar   │
                          │       │                                       │
                          │       └─▶ /  and  /editor  (SAME handler)     │
                          │             (require_editor — Phase 10        │
                          │              restructures this to ALSO        │
                          │              extend _dashboard_base.html)     │
                          │             POST /editor/save                 │
                          │             POST /editor/image|media|audio    │
                          │             POST /editor/unpublish             │
                          │                   │                           │
                          └───────────────────┼───────────────────────────┘
                                              │ asyncio.to_thread + GitHub
                                              │ Git Data API (core/github_publish.py)
                                              ▼
                          ┌─────────────────────────────────────────────┐
                          │  GitHub repo Shangrii/Nocturna-Avatars        │
                          │  (WEBSITE_REPO) — src/data/editors.json +     │
                          │  public/editors/<mediaId>/*  committed here   │
                          └───────────────────┬───────────────────────────┘
                                              │ git push → GitHub Actions
                                              │ (.github/workflows/deploy.yml)
                                              ▼
                          ┌─────────────────────────────────────────────┐
                          │  Astro 7.0.3 build (output: static)           │
                          │  reads src/data/editors.json at BUILD TIME    │
                          │  → dist/ force-pushed to gh-pages branch      │
                          │  → served by GitHub Pages, custom domain      │
                          │    nocturna-avatars.site (CNAME)               │
                          │                                                │
                          │  TODAY:   src/pages/e/[slug].astro (full page) │
                          │  PHASE10: src/pages/[slug].astro (full page,   │
                          │           moved to root — the vanity URL)      │
                          │           src/pages/e/[slug].astro becomes a   │
                          │           redirect STUB → /{slug}  (same       │
                          │           meta-refresh pattern already used    │
                          │           by [lang]/[concept]/[slug].astro     │
                          │           for the PRIOR /es/editores/<slug>    │
                          │           → /e/<slug> migration)               │
                          └─────────────────────────────────────────────┘
public browser ──GET──▶ nocturna-avatars.site/{slug}  (fully static HTML,
                         no auth, no server — the editor's live page)
```

### Recommended Project Structure (files touched, no new top-level dirs)

```
nocturna-bot/
├── app/
│   ├── templates/
│   │   ├── _sidebar.html         # add 8th sections[] entry + is_editor lock branch (D-03)
│   │   ├── _dashboard_base.html  # remove unconditional "Back to editor" link (UI-SPEC)
│   │   └── editor.html           # {% extends "_dashboard_base.html" %} + content block (D-01)
│   ├── static/
│   │   ├── dashboard.css         # unchanged tokens, reused by editor chrome (D-06)
│   │   └── editor.css            # retint chrome rules onto dashboard.css tokens;
│   │                              # .preview-* rules copied forward byte-for-byte (UI-SPEC)
│   ├── deps.py                   # require_editor's session-clear must not fire for a
│   │                              # non-editor's locked-nav click (Common Pitfall #1)
│   └── main.py                   # GET "/" and "/editor" route gate split (see below)
└── core/
    └── editors_model.py          # RESERVED_SLUGS needs public-site route words added
                                    # (Common Pitfall #4)

Website/ (sibling repo, separate git remote)
└── src/
    ├── pages/
    │   ├── [slug].astro          # NEW — moved from e/[slug].astro (the vanity page)
    │   └── e/
    │       └── [slug].astro      # BECOMES a redirect stub → /{slug} (was the full page)
    └── data/
        └── editors.json          # unchanged shape/consumer contract
```

### Pattern 1: Same-app shell extension (not a new mount)

**What:** The editor surface and the 6 operational modules are ALREADY the same FastAPI
app/process (`app/main.py`), same Jinja2 `Environment`, same static mount. Integration is
pure template/route work — no reverse-proxy path split, no iframe, no second uvicorn
process for the editor UI itself (the view-counter app is a *different*, already-separate
concern, unaffected).
**When to use:** Always for this phase — there is no "should we proxy vs. iframe vs.
lift routes" decision to make; the app boundary already dissolved this question. The only
open integration seam is CSS token reconciliation (already resolved by `10-UI-SPEC.md`)
and the tier-gate split below.
**Example (today's mount — confirms single-app, single-route-table reality):**
```python
# Source: app/main.py (verified in this session)
# Mounted at BOTH "/" (10-08's fixed POST_LOGIN_REDIRECT target — the dashboard root)
# and "/editor" (this plan's own literal artifact contract) — same handler, no
# duplicated logic, reconciling the two plans' route-path expectations.
@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request, ident: dict = Depends(require_editor)):
    ...
    return templates.TemplateResponse(request, "editor.html", {...})
```

### Pattern 2: Server-rendered tier gate — the existing 3-tier idiom to replicate

**What:** Every module route resolves tier via `Depends(require_manager)` (owner OR
Manager, else `TierForbidden(required_tier="manager")` → renders `forbidden.html` with
sidebar intact). `require_owner` narrows further for Settings. Both share the single
cached `_resolve_roles` dependency (one live Discord role read/request).
**When to use:** The GET `/editor` (and GET `/`) route needs an equivalent
`TierForbidden(required_tier="editor")` branch for a non-editor — see Common Pitfall #1
for why `require_editor` as currently written cannot be reused as-is for this branch.
**Example:**
```python
# Source: app/deps.py (verified in this session) — the pattern to mirror
async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
```

### Pattern 3: Astro build-time redirect stub for a static host — ALREADY SHIPPED

**What:** GitHub Pages cannot issue server-side 301s. The site already solves exactly
this problem for the *previous* editor-URL migration (`/es/editores/<slug>` ·
`/en/editors/<slug>` → `/e/<slug>`) with a tiny stub page: `noscript` meta-refresh +
`location.replace()` with the target baked in as a **build-time literal** via
`define:vars` (never a runtime-read value — this is the open-redirect guard, T-01-03).
**When to use:** Reuse verbatim for `/e/<slug>` → `/<slug>` (D-05). This is a direct
copy-adapt, not new design work.
**Example (the exact existing pattern to replicate):**
```astro
{/* Source: Website/src/pages/[lang]/[concept]/[slug].astro (verified in this session) */}
const { lang, slug } = Astro.params;
const target = `/e/${slug}`;
---
<script define:vars={{ target }}>
  location.replace(target);
</script>
```
For the new `/e/<slug>` → `/<slug>` stub, `target` becomes `` `/${slug}` `` and the
`getStaticPaths` cartesian collapses from per-locale back to per-editor (mirroring
`e/[slug].astro`'s current single-language `getStaticPaths`, not the legacy route's
locale cartesian).

### Pattern 4: Astro's native `redirects` config — the Don't-Hand-Roll alternative worth considering

Astro (as of the version in this repo, 7.0.3) ships a first-class `redirects` config key
in `astro.config.mjs` that, for a fully static build with no adapter, auto-generates the
identical meta-refresh HTML stub this repo already hand-writes per-route
`[CITED: docs.astro.build/en/reference/configuration-reference — "redirects"]`. Because
`astro.config.mjs` is a plain ESM module, it CAN import `src/data/editors.json` at
config-eval time and build the redirect map programmatically:
```js
// Illustrative — NOT verified against this exact Astro version's JSON-import syntax;
// treat as [ASSUMED] pending a quick build-time smoke test.
import editorsData from './src/data/editors.json' with { type: 'json' };
const legacyEditorRedirects = Object.fromEntries(
  editorsData.filter(e => e?.published && e?.slug).map(e => [`/e/${e.slug}`, `/${e.slug}`])
);
export default defineConfig({ redirects: legacyEditorRedirects, /* ...existing config */ });
```
**Tradeoff vs. Pattern 3:** the hand-written stub (Pattern 3) is already audited, already
proven in production for the harder (locale-cartesian) case, and keeps the redirect
logic colocated with the other editor routes/tests. The native `redirects` config
removes a little boilerplate but is unverified against this repo's exact Astro version
behavior in this session — **recommend Pattern 3** (extend the proven stub) unless the
planner wants to spend a cycle verifying Pattern 4's build output byte-for-byte matches.

### Anti-Patterns to Avoid
- **Reverse-proxying/iframing the editor page as if it were a separate app.** It already
  is not — this would be strictly regressive versus the current single-app reality.
- **Hand-rolling a new redirect/rewrite mechanism (Caddy-level, `_redirects` file, etc.)
  for the vanity URL.** GitHub Pages ignores Netlify-style `_redirects` files entirely;
  Caddy fronts `editors.nocturna-avatars.site` (the admin app), **not**
  `nocturna-avatars.site` (the public static site) — a Caddy-level fix would be solving
  the problem on the wrong host.
- **Trusting `require_editor`'s current session-clear behavior for a locked-nav click.**
  See Common Pitfall #1 — this silently regresses D-02/D-16's own contract.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Static-host redirect for the legacy `/e/{slug}` link | A custom Caddy rewrite, a `_redirects` file, or a hand-rolled JS-only page with no `noscript`/canonical | The proven `[lang]/[concept]/[slug].astro` stub pattern (Pattern 3), or Astro's native `redirects` config (Pattern 4) | GitHub Pages has zero server-side redirect capability; the existing stub already handles the no-JS fallback + SEO canonical + open-redirect guard correctly — reinventing it risks dropping one of those three guarantees |
| Slug uniqueness/validation for the vanity URL | A second slug-validation path on the Astro/site side | `core/editors_model.resolve_slug`/`normalize_slug` (already the single source of truth, D-05 confirms "no separate vanity field") | The slug IS the vanity URL; validating it twice in two languages (Python + a hypothetical Astro-side check) is duplicate logic that will drift |
| Tier lock-icon rendering for the new Editor sidebar entry | New client-side JS gating, a new template partial | `_sidebar.html`'s existing data-driven `sections[]` loop + `--acc` CSS var wiring (D-14, already server-rendered) | Zero new sidebar CSS is needed per UI-SPEC; the loop already generalizes to N sections |
| Non-editor 403 dead-end page | A new bespoke "you can't see this" template for the Editor section specifically | `forbidden.html` (already parametrized on `required_tier`, D-16) — confirmed it renders `required_tier="editor"` correctly with no template change needed | One generic 403 template already exists and is the house pattern for every other locked section |

**Key insight:** every piece of infrastructure this phase needs (tiered sidebar locks,
static-host redirects, slug validation, a generic 403 page) was already built for a
*previous* phase or a *previous* editor-URL migration. The actual new work is almost
entirely wiring/gate-splitting, not net-new mechanism design — which raises the bar for
"don't reinvent something that already works" scrutiny during planning.

## Common Pitfalls

### Pitfall 1: `require_editor`'s stale-session-revocation logic will fire on the wrong population once the Editor nav item is visible-but-locked to everyone (CRITICAL)

**What goes wrong:** D-02 requires every owner/Manager to see the "Editor" sidebar entry
with a 🔒, still linking to the real `/editor` route (D-16's "still links to the real
route" dead-end pattern). But `app/deps.py::require_editor` is:
```python
discord_id = request.session.get("discord_id")
if not discord_id:
    raise HTTPException(status_code=401, ...)
if not await has_editor_role(discord_id):
    request.session.clear()                      # <-- clears the WHOLE session
    raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)
```
An authenticated owner/Manager who clicks the locked "Editor" item has a valid
`discord_id` in session but `has_editor_role()` returns `False` — so their **entire
dashboard session is cleared** (they are logged out of everything, not just denied this
one section), and the 403 is rendered via the generic `login.html` branch in the
exception handler (not `forbidden.html`), because `require_editor` raises a bare
`HTTPException`, not `TierForbidden`.

**Why it happens:** `require_editor` was designed and audited (Pitfall 2 in its own
docstring) for exactly one population: *an editor whose role was revoked mid-session* —
where clearing the session is the CORRECT security behavior (D-10 auto-unpublish
companion). It was never designed to be hit by a non-editor at all, because until this
phase no non-editor ever had a link to `/editor`.

**How to avoid:** Split the GET `/editor` (and GET `/`) route's gate from the mutation
endpoints' gate. The mutation endpoints (`/editor/save`, `/editor/image`, `/editor/media`,
`/editor/audio`, `/editor/unpublish`) are POST-only and D-07-frozen — no non-editor will
ever hit them via the UI, so `require_editor` stays exactly as-is there (zero behavior
change, satisfies D-07). For the GET route only: resolve tier via the shared
`_resolve_roles` dependency first; if `not roles["is_editor"]` AND the caller is
`is_owner`/`is_manager`, raise `TierForbidden(required_tier="editor")` (renders
`forbidden.html`, no session clear — matches D-02/D-16 exactly, identical shape to every
other locked module). Only fall through to the existing `require_editor`
identity/stale-check path when `roles["is_editor"]` is true (an actual editor, where the
existing Pitfall-2 discipline is exactly correct and must be preserved unchanged).
**Warning signs during testing:** an owner test account gets logged out (has to
re-authenticate) after clicking the locked "Editor" nav item — this is the smoking gun
that the split above was not done.

### Pitfall 2: Double live Discord role read if the fix to Pitfall 1 is done naively

**What goes wrong:** `_resolve_roles` and `require_editor`/`has_editor_role` each make
their own independent call to `auth._fetch_member_roles` — FastAPI's `Depends(...,
use_cache=True)` only dedupes repeat calls to the *identical* dependency callable within
one request, not across two different functions that both internally hit the same
Discord endpoint. Naively depending on BOTH `_resolve_roles` (to branch) AND
`require_editor` (for identity) on the same route re-introduces the exact N+1 Discord
REST read anti-pattern `_resolve_roles`'s own docstring calls out as Pitfall 4.
**Why it happens:** the two functions were written independently, in different phases,
before either non-editor callers or a shared-gate need existed.
**How to avoid:** once `_resolve_roles` has confirmed `is_editor`, that IS the live
re-check `require_editor`/`has_editor_role` would otherwise perform — don't call
`require_editor` a second time. Read `slug` directly off `request.session.get("slug")`
and reuse `roles["discord_id"]` for the `_fetch_current_entry` lookup; there is no need
for a second Discord API round-trip.
**Warning signs:** a request-timing regression or duplicate log lines for the same
`/guilds/{id}/members/{id}` call within one request to `/editor`.

### Pitfall 3: `forbidden.html`'s sidebar renders with `_NO_TIER_ROLES` (all locked), including for a legitimately-tiered caller

**What goes wrong:** the existing exception handler passes a hardcoded
`_NO_TIER_ROLES = {"is_owner": False, "is_manager": False, "is_editor": False}` into
`forbidden.html` (which extends `_dashboard_base.html` and includes `_sidebar.html`).
An owner denied the Editor section would see **every** sidebar item rendered as locked,
including the six modules they actually have access to — a cosmetically confusing (but
not security-relevant) side effect.
**Why it happens:** re-deriving the real roles here would mean a second live Discord
read just to render an error page (documented tradeoff already accepted for the
pre-existing Settings-403 case in Phase 3/4).
**How to avoid:** this is a **pre-existing, already-accepted tradeoff** (not introduced
by this phase) — confirm with the owner whether it's worth fixing now that a *second*
scenario (Editor-tier denial) will hit it, or leave it as scoped-out cosmetic debt
matching the Settings-403 precedent. Not a blocker; flagging for awareness only.

### Pitfall 4: `RESERVED_SLUGS` guards the wrong domain's routes for the vanity URL

**What goes wrong:** `core/editors_model.RESERVED_SLUGS` today is
`{"e", "api", "static", "assets", "admin", "editor", "editors", "auth", "login", "logout", "me", "favicon"}`
— this list was built to protect **the admin app's own route table**
(`editors.nocturna-avatars.site`). Once the slug becomes a **root-level path on the
public site** (`nocturna-avatars.site/{slug}`, D-04/D-05), the collision surface that
actually matters is the **public site's** top-level routes and `public/` static folders,
which are verified (this session) to include: `en` (a literal top-level pages directory,
no `index.astro` today — meaning `/en` as a bare path currently 404s and WOULD be
captured by a root `[slug].astro` if "en" were ever chosen as a slug), the implicit `es`/
`en` locale codes used throughout `[lang]` routing, and the `public/` folders `gallery`,
`store`, `fonts` (which are copied verbatim into `dist/` at those exact paths and would
silently collide with a same-named generated page).
**Why it happens:** the reserved list predates the vanity-URL decision; it was written
when the slug only ever appeared under `/e/{slug}`, where none of the public site's own
top-level words could collide.
**How to avoid:** widen `RESERVED_SLUGS` to the union of both domains' top-level words:
add at minimum `en`, `es`, `gallery`, `store`, `fonts`, `build` (the deploy workflow's own
`build.txt`/`.heal` liveness-check file lives at site root too). Treat this as a
must-fix-before-ship item, not a nice-to-have — an editor claiming slug `gallery` would
silently break the site's actual gallery page (or vice versa, depending on Astro's
static-vs-dynamic route precedence at build time, which was not empirically tested in
this session for a real collision).
**Warning signs:** an Astro build failure or a live routing regression report on the
public site involving one of the words above.

### Pitfall 5: Astro route-priority assumption for `[slug].astro` at root is asserted by docs, not empirically verified in this session

**What goes wrong:** Astro's own docs state file-based literal routes always take
priority over same-name dynamic routes `[CITED: docs.astro.build/en/guides/routing]`, so
`/en/*` (served by the literal `src/pages/en/` directory) should never be shadowed by a
sibling `src/pages/[slug].astro`. This was **not** verified with an actual local
`astro build` in this session (no Node/npm dependency install was run against the
`Website` checkout).
**Why it happens:** research budget prioritized reading source over running a full
`npm install && npm run build` in a sibling repo the bot's own test suite doesn't cover.
**How to avoid:** the planner/executor should run a real `astro build` (or `astro dev`)
locally against a `src/pages/[slug].astro` stub early in the Wave-0/scaffolding step and
confirm `/en/servicios` and `/gallery/...` static assets still resolve correctly before
building the rest of the vanity-URL feature on top of the assumption.
**Warning signs:** any 404/wrong-content regression on `/en/*` pages after the root
`[slug].astro` route ships.

### Pitfall 6: `editor.css`'s live-preview canvas is the ONE part of the reconciliation that must not be touched — already resolved by UI-SPEC, restated here as a regression gate

**What goes wrong:** a naive "retint the whole file onto dashboard tokens" pass would
also retint `.preview-*` rules, which render the editor's OWN arbitrary per-page theme
(`--theme-*` custom properties) — breaking the WYSIWYG fidelity between the admin
preview and the real published page (D-01's explicit non-regression clause).
**Why it happens:** `editor.css` today mixes chrome and preview-canvas rules under the
same `:root` token block, making a blanket find-replace attractive but wrong.
**How to avoid:** already fully specified in `10-UI-SPEC.md`'s "Reconciliation Strategy"
section (namespace split: retint chrome, copy `.preview-*` forward byte-for-byte). Restated
here only so the planner's task breakdown treats "verify zero `.preview-*` selector was
touched" as an explicit verification step, not an implicit assumption.

## Code Examples

### Sidebar `sections[]` — the 8th entry to add (D-03)

```jinja2
{# Source: app/templates/_sidebar.html (existing 7-entry pattern, verified this session) #}
{% set sections = [
  ...,
  {"id": "settings", "label": "Ajustes · Settings", "icon": "⚙", "accent": "var(--accent-settings)", "route": "/admin/settings", "tier": "owner"},
  {"id": "editor",   "label": "Editor",              "icon": "✎", "accent": "var(--accent-editor)",  "route": "/editor",         "tier": "editor"},
] %}
{% for section in sections %}
{% set unlocked = (section.tier == "owner" and roles.is_owner)
                or (section.tier == "manager" and (roles.is_owner or roles.is_manager))
                or (section.tier == "editor" and roles.is_editor) %}
...
{% endfor %}
{# The old bolt-on {% if roles.is_editor %}<div class="editor-link">...{% endif %} block
   is DELETED entirely — its route/icon/label are now the "editor" sections[] entry above. #}
```

### GET `/editor` tier-gate split (resolves Pitfall 1/2 — illustrative, not final code)

```python
# Source: app/main.py + app/deps.py (existing pieces this composes, verified this session)
@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request, roles: dict = Depends(_resolve_roles)):
    if not roles["is_editor"]:
        # Matches every other locked-section dead-end (D-16) — no session clear.
        raise TierForbidden(required_tier="editor")
    entry = await _fetch_current_entry(roles["discord_id"])
    ...
    return templates.TemplateResponse(request, "editor.html", {
        "entry": entry, "roles": roles, "active_section": "editor", ...
    })

# app/deps.py — _resolve_roles ALREADY re-derives is_editor live every request (no
# session-cached tier, D-02) and already raises 401 for "not authenticated" — so this
# single dependency now does everything require_editor's read-side used to do, minus
# the write-path's stale-session-clear (which correctly stays ONLY on the POST endpoints,
# still gated by the UNCHANGED require_editor per D-07).
```

### Astro vanity-page move (illustrative diff shape)

```
git mv src/pages/e/[slug].astro src/pages/[slug].astro
# then update relative imports one level up:
#   '../../layouts/EditorLayout.astro' -> '../layouts/EditorLayout.astro'  (etc.)
# and REPLACE src/pages/e/[slug].astro with a redirect stub mirroring
# src/pages/[lang]/[concept]/[slug].astro's getStaticPaths + define:vars pattern,
# but WITHOUT the langCodes cartesian (single target: `/${slug}`, not per-locale).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `/es/editores/<slug>` · `/en/editors/<slug>` (bilingual, cartesian) | `/e/<slug>` (single-language, per D-13's de-bilingualization) | Plan 10.1-07 ("Wave-3 cutover", already shipped) | The OLD locale route is ALREADY a redirect stub today — Phase 10 adds a SECOND redirect hop (`/e/<slug>` → `/<slug>`), not a replacement of the first one. Both stubs coexist. |
| `actions/deploy-pages@v5` (GitHub's official Pages Action) | Manual `git push --force` of `dist/` to a `gh-pages` branch + polling self-heal | 2026-07-04 (per the workflow's own comment: "repeated opaque 'Deployment failed' rejections") | Any Phase 10 change to the Astro build must still emit a valid `dist/` the existing `deploy.yml` can force-push; no new deploy-pipeline touchpoint needed |

**Deprecated/outdated:** none — this is a comparatively young codebase; no stale
dependency findings surfaced.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Astro 7.0.3's native `redirects` config can consume a build-time JSON import to generate a dynamic redirect map identically to the hand-written stub pattern | Architecture Patterns, Pattern 4 | Low — this is presented as an alternative, not the recommended path; Pattern 3 (the already-proven stub) is the primary recommendation precisely to avoid depending on this unverified claim |
| A2 | Astro's literal-route-over-dynamic-route priority (docs-cited) holds in practice for this repo's exact `src/pages/en/` + root `[slug].astro` combination | Common Pitfall #5 | Medium — if wrong, `/en/servicios`/`/en/galeria` could silently break; mitigated by requiring an empirical `astro build` check as an explicit Wave-0 step |
| A3 | No Cloudflare or other reverse-proxy sits in front of `nocturna-avatars.site` (only GitHub Pages directly via `CNAME`) | Common Pitfalls #4/#5, Don't Hand-Roll | Low-Medium — if a proxy DOES exist (not found in this session's search of both repos), a proxy-level redirect rule could be a simpler/more-robust alternative to the build-time stub; worth a one-line confirmation from the owner during planning |

**If this table is empty:** N/A — see rows above; all three are flagged precisely because
they could not be fully closed out without running a live `astro build` or querying
external DNS/CDN configuration, which was out of scope for a static-code research pass.

## Open Questions

1. **Should the pre-existing `_NO_TIER_ROLES` all-locked-sidebar cosmetic quirk on
   `forbidden.html` be fixed as part of this phase?**
   - What we know: it's a pre-existing, already-accepted tradeoff (Phase 3/4's Settings
     403 case already hits it); Phase 10 adds a second scenario (Editor-tier denial) that
     will hit the same quirk.
   - What's unclear: whether the owner considers "two scenarios now instead of one"
     enough to warrant a fix.
   - Recommendation: leave as-is unless flagged during `/gsd:discuss-phase` follow-up;
     it is cosmetic, not a security or functional regression.

2. **Does `nocturna-avatars.site` sit behind any CDN/proxy (Cloudflare or otherwise) that
   could do the legacy-link redirect at the edge instead of via an Astro-generated
   stub?**
   - What we know: `CNAME` + GitHub Pages is the only hosting mechanism found in the
     `Website` repo; no Cloudflare/proxy config was found in either repo searched this
     session.
   - What's unclear: DNS-level configuration (registrar settings) is outside both repos'
     visibility from static analysis.
   - Recommendation: proceed with the build-time Astro stub (Pattern 3) as the default
     plan — it works regardless of DNS layer and is already proven — but a 30-second
     owner confirmation ("is nocturna-avatars.site's DNS proxied through anything, or a
     plain A/CNAME record to GitHub Pages?") would let the planner skip Assumption A3
     entirely.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python + pytest (conda env) | `nocturna-bot` test suite (`tests/test_app_editor.py`, `tests/test_app_dashboard.py`) | ✓ (per project memory: use `C:\Users\Shangri\miniconda3\python.exe -m pytest`, not PowerShell's Python) | not re-verified this session | — |
| Node.js + npm | `Website` Astro build (`npm install && npm run build`) | Not verified this session (no command run against the `Website` checkout) | package.json pins `astro@7.0.3` | If unavailable locally, defer the empirical route-priority check (Common Pitfall #5) to CI (the existing `deploy.yml` runs `npm install`/`npm run build` on every push to `revamp`) |
| GitHub Actions (`deploy.yml`) | Publishing the Astro build to `gh-pages` | ✓ (existing, unmodified by this phase's changes) | — | — |

**Missing dependencies with no fallback:** none identified.
**Missing dependencies with fallback:** local Node/npm for the Astro route-priority
smoke test (Pitfall 5) — CI already runs the equivalent build on push, so this can be
validated post-commit if a local Node toolchain isn't set up for this session.

## Validation Architecture

### Test Framework — `nocturna-bot` side
| Property | Value |
|----------|-------|
| Framework | pytest (existing `tests/` suite; see project memory — run via
`C:\Users\Shangri\miniconda3\python.exe -m pytest`, not PowerShell's `Python314`) |
| Config file | none found (no `pytest.ini`/`pyproject.toml` pytest section) — rootdir-based discovery |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_app_editor.py tests/test_app_dashboard.py -x` |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/` |

### Test Framework — `Website` side
| Property | Value |
|----------|-------|
| Framework | **None** — no vitest/jest/playwright config found; validation today is "the
`astro build` succeeds" (a malformed `getStaticPaths` throws and fails the whole build,
which is the site's existing safety net) plus human visual verification |
| Config file | n/a |
| Quick run command | `npm run build` (fails loudly on any routing/getStaticPaths error) |
| Full suite command | same — `npm run build` is the only automated gate this repo has |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EDIT-01 | Editor sidebar entry renders unlocked for editor / locked (no session clear) for owner-only, Manager-only | unit/integration | `pytest tests/test_app_dashboard.py -k editor -x` | ✅ (extend existing `test_editor_only_locked_out_of_dashboard` style tests — file exists, new cases needed) |
| EDIT-01 | `/editor` renders in-shell (extends `_dashboard_base.html`, sidebar present) | integration | `pytest tests/test_app_editor.py -k renders -x` | ✅ (existing `test_editor_page_renders_slug_field` — extend for shell markers) |
| EDIT-01 (D-07 guard) | Save/upload/unpublish endpoints unchanged behavior | regression | `pytest tests/test_app_editor.py -x` (full file — 25+ existing cases) | ✅ (already comprehensive; these must stay green with ZERO edits to their assertions) |
| EDIT-02 | `resolve_slug` rejects the widened reserved-word set (`en`, `es`, `gallery`, `store`, `fonts`, `build`) | unit | `pytest tests/test_editors_model.py -k reserved -x` | ❌ Wave 0 — new cases needed, existing file/pattern to extend |
| EDIT-02 | Astro build succeeds with `[slug].astro` at root + `e/[slug].astro` as a redirect stub, no `/en/*` regression | build-gate | `npm run build` (Website repo) | ❌ Wave 0 — no existing Astro test harness; this IS the test |

### Sampling Rate
- **Per task commit (bot side):** `pytest tests/test_app_editor.py tests/test_app_dashboard.py tests/test_editors_model.py -x`
- **Per task commit (site side):** `npm run build` (Website repo)
- **Per wave merge:** full `pytest tests/` + full `npm run build`
- **Phase gate:** both suites green + a live human-verify checkpoint (OAuth → edit →
  publish → vanity URL resolves → legacy `/e/<slug>` redirects → owner clicks locked
  Editor nav item without being logged out) before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_editors_model.py` — new reserved-word cases for `en`/`es`/`gallery`/
      `store`/`fonts`/`build`
- [ ] `tests/test_app_dashboard.py` — new case: owner/Manager clicking the locked
      "Editor" nav item gets `forbidden.html` (403, `required_tier == "editor"`) with
      an INTACT session (not logged out) — this is the regression test for Pitfall 1
- [ ] `tests/test_app_editor.py` — new case: `/editor` GET now requires shell markers
      (sidebar present, `_dashboard_base.html` block structure) present in the response
- No JS/Astro test framework exists in `Website` — the Wave 0 gap there is procedural
  (run `npm run build` locally or rely on CI) rather than a missing test file

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | yes (unchanged) | Discord OAuth2 via Authlib (`app/auth.py`) — untouched by this phase, D-07 |
| V3 Session Management | yes | Starlette `SessionMiddleware` (itsdangerous-signed, `Secure`+`SameSite=Lax`, 6h TTL) — this phase's ONE session-handling change is fixing Pitfall 1 (a locked-nav click must NOT clear a valid session) |
| V4 Access Control | yes | Server-rendered tier gate (`_resolve_roles`/`TierForbidden`) — this phase extends the existing pattern to a new tier value (`"editor"`), no new mechanism |
| V5 Input Validation | yes | `core/editors_model.py`'s Pydantic schema (unchanged, D-07) governs all editor-page data; the ONLY new validation surface is the widened `RESERVED_SLUGS` set (Pitfall 4) |
| V6 Cryptography | no | Nothing new — session signing/OAuth secret handling is unchanged (D-07) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Open redirect via the vanity-URL legacy stub | Tampering/Spoofing | Already mitigated in the existing pattern being copied: the redirect target is a **build-time literal** (`define:vars`), never read from a runtime/query value (T-01-03 in the existing code) — the new stub must preserve this, not accept a `?next=` param |
| Slug/route collision granting unintended access to a reserved public-site path | Elevation of Privilege (of a namespace, not auth) | Widen `RESERVED_SLUGS` (Pitfall 4) BEFORE shipping vanity URLs; this is the load-bearing new control this phase introduces |
| Session fixation/hijack via the sidebar-click session-clear bug | Denial of Service (self-inflicted, on legitimate staff) | Fix Pitfall 1 — a locked-nav click must 403 via `TierForbidden`, never clear a valid owner/Manager session |
| XSS via editor-authored theme/content on the public page | Tampering | Already covered, unchanged: Astro auto-escaping, no `set:html`, Pydantic-side scheme/charset guards on every color/URL/media field (D-07 freezes this) |

## Sources

### Primary (HIGH confidence — direct code read, this session)
- `nocturna-bot/app/main.py`, `app/deps.py`, `app/auth.py`, `app/templates/_sidebar.html`,
  `app/templates/_dashboard_base.html`, `app/templates/editor.html`,
  `app/templates/forbidden.html`, `app/static/editor.css`, `app/static/dashboard.css`,
  `core/editors_model.py`, `core/github_publish.py`, `app/counter_app.py`,
  `deploy/EDITOR_DEPLOY.md`
- `Website/astro.config.mjs`, `Website/.github/workflows/deploy.yml`,
  `Website/src/pages/e/[slug].astro`, `Website/src/pages/[lang]/[concept]/[slug].astro`,
  `Website/src/pages/index.astro`, `Website/package.json`
- `.planning/phases/10-editors-section-integration/10-CONTEXT.md`,
  `.planning/phases/10-editors-section-integration/10-UI-SPEC.md`
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`
- `tests/test_app_editor.py`, `tests/test_app_dashboard.py`, `tests/test_editors_model.py`
  (test-name enumeration only, to establish the existing coverage map)

### Secondary (MEDIUM confidence — WebSearch, cross-referenced against official docs)
- Astro `redirects` config / static-output meta-refresh behavior — WebSearch results
  citing `docs.astro.build/en/reference/configuration-reference/` and
  `docs.astro.build/en/guides/routing/` directly; not independently re-fetched via
  WebFetch in this session, so tagged MEDIUM rather than HIGH.

### Tertiary (LOW confidence)
- None — every claim in this document is either directly verified against this
  session's file reads or explicitly logged in the Assumptions table above.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries introduced; every piece (FastAPI, Jinja2,
  Alpine.js, Astro, GitHub Pages/Actions) already lives in the codebase and was read
  directly this session.
- Architecture: HIGH — the single-app shell-integration finding and the Astro
  static-redirect-stub finding are both drawn from reading the actual production code,
  not inferred.
- Pitfalls: HIGH for #1/#2/#4/#6 (directly traced through the exact code paths that
  would misbehave); MEDIUM for #3 (pre-existing, not this phase's fault); LOW-MEDIUM for
  #5 (Astro route-priority claim is docs-cited, not locally build-verified this session).

**Research date:** 2026-07-30
**Valid until:** 2026-08-29 (30 days — stable stack, no fast-moving dependencies; the
Astro-version-specific claim in Pattern 4/Assumption A1 should be re-checked if the
`Website` repo's `astro` pin changes before then)
