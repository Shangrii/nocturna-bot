# Phase 10: Editors Section Integration - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Fold the existing standalone editor presentation page into the shared dashboard shell
as a real section under the **editor tier**, and — per the owner's "full experience"
decision — deliver the *complete* editor experience: full shell chrome, vanity URLs for
editor pages, and a targeted visual/UX polish pass on the editor surface.

Today (Phase 3 / D-15) the editor page is a **fully standalone** surface: `app/templates/editor.html`
has its own `<html>`/topbar/fonts and `app/static/editor.css`, and is reached only by a
link-out (`/editor`). An editor-only user's post-login redirect (`app/auth.py`
`_REDIRECT_EDITOR_TIER = "/editor"`) drops them onto that standalone page — they never see
the shell. Phase 3 explicitly deferred "the real integration" to this phase.

**⚠ SCOPE EXPANDED beyond the roadmap framing.** ROADMAP.md calls Phase 10 the
"lowest-risk, lowest-priority integration" with SC2 = editor workflow "keeps working
**unchanged**." The owner (2026-07-29) chose the maximal scope: full shell wrap +
**vanity URLs** (a new public-site routing capability) + **integrate-and-polish** (not
integrate-as-is). Bookkeeping follow-ups the planner/transition must handle:
- **REQUIREMENTS.md:** EDIT-01 stays (shell integration). Add **EDIT-02** (vanity URLs
  for editor pages). Soften EDIT-01/SC2 wording from "unchanged" to **workflow parity**
  (OAuth, save/publish, uploads, view counter behave identically) *with defined polish*.
- **ROADMAP.md:** update the Phase 10 goal/success-criteria to reflect the three
  deliverables (shell integration, vanity URLs, polish).

This phase has a UI hint (`yes`) → run `/gsd:ui-phase 10` to produce a UI-SPEC that pins
the shell-wrap visuals and enumerates the polish changes before planning.

</domain>

<decisions>
## Implementation Decisions

### Shell integration (the editor page inside the shell)
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

### Vanity URLs (new capability — EDIT-02)
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

### Editor-surface polish (Integrate + polish)
- **D-06: Match dashboard look AND targeted UX cleanups.** Beyond wrapping, make the
  editor visually consistent with the shell (shared `dashboard.css` tokens/topbar/type/
  spacing) **and** apply targeted UX improvements — candidates: clearer save/publish
  states, upload feedback, mobile layout. Each concrete change is enumerated and approved
  in the **UI-SPEC pass** before planning.
- **D-07: SC2 workflow-parity guard.** Polish may change chrome/visuals/UX affordances,
  but the underlying editor **behavior** must stay functionally identical: OAuth flow,
  `/editor/save` (publish-on-save, D-13), `/editor/image` `/editor/media` `/editor/audio`
  upload+re-encode contracts, self-unpublish, and the IDOR/path-traversal guards
  (`require_editor` choke point, session-forced `discordId`, server-side `mediaId`).

### Claude's Discretion
- Exact `editor.css`/`dashboard.css` reconciliation strategy, sidebar section ordering
  (editor entry placement), and nav wording — planner/UI-SPEC decide within the decisions
  above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase-defining prior context
- `.planning/phases/03-dashboard-shell-tiered-access/03-CONTEXT.md` — **D-15** (editors
  get the shell in Phase 3 with everything locked + link-out; "Phase 10 does the real
  integration"), additive-not-exclusive tier rule, **D-14** (server-rendered sidebar lock
  state), **D-16** (`forbidden.html` dead-end), **D-08** (`has_editor_role` unifies on the
  `editor_roles` settings key).
- `.planning/ROADMAP.md` §"Phase 10: Editors Section Integration" — goal + SC1/SC2 (note
  the scope-expansion flag in Phase Boundary above; refs update needed).
- `.planning/REQUIREMENTS.md` — EDIT-01 (and add EDIT-02 for vanity URLs).

### Shell + tier system (the integration target)
- `app/templates/_sidebar.html` — the data-driven 7-section nav + the bolt-on
  `is_editor` `.editor-link` to promote (D-03).
- `app/templates/_dashboard_base.html` — the shell base editor.html must extend (D-01);
  shell topbar with the "Back to editor" link.
- `app/deps.py` — `_resolve_roles` (`is_owner`/`is_manager`/`is_editor`),
  `require_manager`/`require_owner`, `TierForbidden`/`required_tier`.
- `app/main.py` — single FastAPI app serving both editor surface (`/`, `/editor`,
  `require_editor`) and shell modules; `_MODULE_SECTIONS`, the `StarletteHTTPException`
  handler that renders `forbidden.html`/`login.html`.
- `app/auth.py` — OAuth, per-tier post-login redirect (`_REDIRECT_MANAGER_TIER`,
  `_REDIRECT_EDITOR_TIER`), first-login draft provisioning.

### Editor surface (wrap + polish target; behavior frozen per D-07)
- `app/templates/editor.html` — standalone two-pane block editor (Alpine `editorApp`).
- `app/static/editor.css` / `app/static/dashboard.css` — the two stylesheets to reconcile.
- `core/editors_model.py` — `EditorPage`, `resolve_slug`/`normalize_slug`/`SlugRejected`
  (the slug source for vanity URLs, D-05).
- `core/github_publish.py` — `sync_editors`, `unpublish_editor`, `_fetch_json` (cross-repo
  commit flow that publishes `editors.json` + media; the vanity-URL mechanism rides on this).
- `app/counter_app.py` — separate view-counter systemd unit (:8771); keep working (SC2).
- `deploy/EDITOR_DEPLOY.md` — infra source-of-truth (Caddy reverse proxy on
  `editors.nocturna-avatars.site`, OAuth redirect URI, DNS). Relevant if vanity-URL
  routing or redirects touch the proxy/public-site layer.

### Milestone visual contract
- `.planning/sketches/001-dashboard-shell/` — variant A shell visual contract the editor
  page must match after the full wrap (D-01/D-06).
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — original approved
  design spec the milestone bootstrapped from.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_dashboard_base.html` + `_sidebar.html`: the shell chrome editor.html extends (D-01);
  sidebar is already data-driven and already server-renders lock icons — add one
  `tier:"editor"` section + an `is_editor` unlock branch.
- `core/editors_model.resolve_slug`: already produces unique, reserved-guarded,
  normalized slugs — the vanity URL is that slug (D-05), no new validation needed.
- `core/github_publish.sync_editors` / `_fetch_json`: the established cross-repo commit
  path to the static site repo — the vanity-URL page generation rides on the same flow.
- `dashboard.css` design tokens: the polish pass reuses these for editor visual parity (D-06).

### Established Patterns
- **Single FastAPI app, one systemd unit** at `editors.nocturna-avatars.site` behind Caddy
  serves BOTH the editor surface and the shell — integration is same-app template/route
  work, not a new service or mount.
- **Server-side tier resolution + server-rendered locks** (D-14): no client-side gating;
  the new editor section follows the same predicate pattern.
- **`require_editor` = the D-08 IDOR choke point**: identity is session-only; the body
  never supplies WHO. D-07 polish must preserve this.
- **Publish-on-save, no draft state** (D-13); uploads re-encode server-side and commit
  only optimized bytes. Behavior frozen under D-07.

### Integration Points
- `_sidebar.html` sections[] (+ lock predicate) — new editor section.
- `editor.html` — restructure to `{% extends "_dashboard_base.html" %}` + `content` block.
- `app/auth.py` redirect + `app/main.py` `/editor` route — in-shell render + nav reconcile.
- Public site repo (Astro/GitHub Pages) — new vanity-URL route + legacy redirect
  (the one genuinely cross-repo / new-surface piece; needs research).

</code_context>

<specifics>
## Specific Ideas

- "Full experience" — the owner explicitly wants Phase 10 to ship the complete editor
  experience, not a minimal reachability change. Everything I offered as "out of scope /
  confirm frozen" was pulled IN.
- Vanity URL example the owner has in mind: `nocturna-avatars.site/shangri`.
- Editors are the least-technical user tier — the uniform locked shell (D-02) is the
  chosen model, but the polish (D-06) should keep the single-purpose editing flow obvious.

</specifics>

<deferred>
## Deferred Ideas

None — the owner chose to pull every candidate (vanity URLs, counter-app parity, editor
polish) INTO Phase 10 for a full-experience release. The only items held back are strictly
outside EDIT scope and unchanged from PROJECT.md Out-of-Scope (multi-guild, secret editing,
log viewer, Overview quick actions).

</deferred>

---

*Phase: 10-editors-section-integration*
*Context gathered: 2026-07-29*
