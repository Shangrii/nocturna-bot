# Phase 3: Dashboard Shell + Tiered Access - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Every staff member lands on a MEE6-style dashboard shell (sketch 001 variant A: sidebar
across 7 sections — Overview, Gallery, Reviews, Reminders, Jinxxy Store, Meetings,
Settings — with per-module color accents) that shows exactly the sections their access
tier permits: owner everything, Manager (`1453560115423875205`) the 6 operational
modules, editor their presentation section. The owner can edit the role→tier mapping
from Settings; a Manager cannot self-elevate and the owner can never be locked out.
Overview shows bot connection status, last Jinxxy sync, and recent activity.

Module functionality (Gallery/Reviews/Reminders/Jinxxy/Meetings bodies) ships in
Phases 6–9; Settings migration + name resolution is Phase 4; editors-section full
integration is Phase 10. This phase delivers the shell, the tier system, the mapping
editor, and the Overview data plumbing.

</domain>

<decisions>
## Implementation Decisions

### Login & tier resolution
- **D-01: Login gate = any mapped tier.** The OAuth callback resolves the user's tier
  from the role→tier mapping (plus the hardcoded owner ID). Anyone resolving to at
  least one tier gets a session; everyone else gets the existing rejection. One gate,
  extending the existing choke-point pattern in `app/auth.py` / `app/deps.py`.
- **D-02: Live re-check per request.** Every protected request re-reads live guild
  roles via the bot token and resolves the tier fresh — preserves the pinned
  `require_editor` stale-session invariant (instant revocation on role removal).
- **D-03: Multi-role users get the union of tier grants.** Tiers are additive grants,
  not exclusive levels: Manager + editor roles ⇒ 6 operational modules AND own editor
  page. (A Manager without the editor role does NOT get an editor page.)
- **D-04: Owner tier = hardcoded `DISCORD_USER_ID` bypass.** The owner resolves to
  owner tier before and independent of any role lookup. The role→tier mapping cannot
  express or remove ownership — this is the concrete "owner can never be locked out"
  guarantee. Fails closed when unset (existing `require_owner` invariant).

### Role→tier mapping model
- **D-05: Mapping lives in the existing validated settings store** (`core/settings.py`)
  as two role-list keys: `manager_roles` (seeded with `1453560115423875205`) and
  `editor_roles` (seeded from `ROLE_MODERATOR_ID`). Reuses v1 validation, seeding,
  read-at-use, and UI plumbing. Seed must be byte-identical to current behavior until
  the owner edits (v1 compatibility constraint).
- **D-06: Multiple roles per tier.** Each tier holds a role list (settings store
  `role_list` type) — a second qualifying role needs no code change.
- **D-07: Editing UX = raw role-ID input fields** in the Settings section, exactly like
  the v1 settings form handles role lists, server-validated (`^\d{17,20}$`). Readable
  @role names arrive in Phase 4; dropdown pickers stay deferred (FUT-01).
- **D-08: `has_editor_role` unifies onto `editor_roles`.** The editor app gate reads
  the `editor_roles` list from the settings store (seeded from `ROLE_MODERATOR_ID`, so
  behavior is identical until edited). One source of truth for "who is an editor"
  across the editor app and the dashboard tier system.

### Overview data plumbing
- **D-09: Rich bot status block.** A bot `@tasks.loop` writes a heartbeat (timestamp +
  gateway latency) into the shared sqlite every ~30–60s; the status block also shows
  uptime since start, guild member count, and loaded cogs. Overview shows Online iff
  the heartbeat is fresh. Shared sqlite is the channel (locked project decision — no
  IPC/HTTP).
- **D-10: Jinxxy poll records sync metadata now.** The existing periodic poll writes
  each run's outcome (timestamp, ok/error, product count) into the shared sqlite;
  Overview reads it. Phase 8's manual-sync status display reuses this exact record.
- **D-11: New append-only `activity_log` table** with a tiny helper the bot calls on
  notable events (photo published/removed, review approved, reminder fired, sync ran,
  meeting posted). Phase 3 instruments those existing cog events; Overview shows the
  last ~10. Later phases append panel-side actions to the same log.
- **D-12: Overview freshness = server-render on load + Alpine.js poll.** Status tiles
  re-fetch every ~30s while the tab is open. No websockets (out of scope).

### Nav visibility & module stubs
- **D-13: The 5 not-yet-built module sections are coming-soon stubs** — real routes in
  the shell with their variant-A header + per-module color accent and a "coming soon"
  body. Satisfies "staff can navigate the 7 sections"; Phases 6–9 fill in the bodies.
- **D-14: Sidebar shows ALL sections, with lock icons on ungranted ones** (user chose
  visible-but-locked over hiding). Staff see the full feature map; server-side 403
  still enforced on every route regardless of nav rendering.
- **D-15: Editors get the shell too in Phase 3** — sidebar with everything locked
  except an "Editor" entry that links out to the existing `/editor` page. The existing
  editor flow itself is untouched; Phase 10 does the real integration.
- **D-16: Forbidden sections return a styled in-shell 403 page** ("This section needs
  Manager access"), bilingual copy in the style of the existing `_FORBIDDEN_COPY`.
  Locked nav items link to the section (and thus to this page) — the dead end is
  graceful. Status code is 403 (ACCESS-02).

### Claude's Discretion
- Heartbeat cadence, staleness threshold, activity-log retention/pruning, and exact
  Overview tile layout within the variant-A visual language.
- Settings form layout for the mapping fields (consistent with the v1 settings panel).
- Landing page per tier after login (Overview for owner/Manager is the natural default).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Visual contract (dashboard shell)
- `.planning/sketches/001-dashboard-shell/README.md` — sketch frontmatter: design
  question, variants, winner = **A (MEE6 puro)**, what to look for.
- `.planning/sketches/001-dashboard-shell/index.html` — the interactive sketch itself;
  variant A defines the sidebar, per-module color accents, spacing, and page chrome.
- `.planning/sketches/MANIFEST.md` — design direction: dark SaaS aesthetic, Inter,
  Nocturna red reserved for the logo, FastAPI + Jinja + Alpine.js (no build step).

### Prior design / requirements
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — approved v1
  design spec this milestone was bootstrapped from (settings store + panel invariants).
- `.planning/REQUIREMENTS.md` — SHELL-01/02, ACCESS-01/02/03/04 definitions.
- `.planning/ROADMAP.md` — Phase 3 success criteria + downstream phase boundaries.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/settings.py` — validated settings store (schema, get/set/all_for_ui, seeding,
  `role_list` type with `^\d{17,20}$` validation): home for `manager_roles`/`editor_roles`.
- `app/deps.py::require_editor` / `require_owner` — the auth choke-point pattern to
  extend with tier-aware dependencies (e.g., `require_tier`/`require_manager`);
  session-only identity (D-08 IDOR discipline), fail-closed owner gate.
- `app/auth.py::has_editor_role` — live bot-token role read (Discord REST v10 with
  timeout); generalize to read the mapped role lists. `_FORBIDDEN_COPY` bilingual style.
- `app/templates/settings.html` + typed-field form pattern — model for the mapping
  editor fields; `app/static/alpine.min.js` already shipped (used for Overview polling).
- `core/db.py` idiom — fresh connection per call, `CREATE TABLE IF NOT EXISTS` init
  functions, WAL on every connection: pattern for `activity_log` / heartbeat / sync-meta.

### Established Patterns
- Session auth via Starlette SessionMiddleware + Discord OAuth (identify scope only);
  role authority is ALWAYS the bot-token REST read, never the OAuth token.
- OAuth callback order is security-critical: state → identify → role-gate → session.
  The gate change (D-01) modifies the role-gate step only.
- Server-side validate-then-write for every settings mutation; no secrets rendered.
- POST-only convention for mutations (roadmap phase note) — no JS PUT/DELETE.
- Bilingual (ES/EN) user-facing copy.

### Integration Points
- `app/main.py` — all routes live here today (editor + `/admin/settings`); the shell
  adds the section routes and Overview JSON endpoint(s) for Alpine polling.
- Bot side: a heartbeat `@tasks.loop`, sync-metadata write in the Jinxxy poll cog, and
  `activity_log` helper calls in gallery/reviews/reminders/jinxxy/meetings cogs.
- Shared sqlite (`DB_PATH`, WAL) is the only bot↔app channel — no new IPC.

</code_context>

<specifics>
## Specific Ideas

- "MEE6 puro" is the reference feel: spacious module pages, each with its own header
  and accent color; Nocturna graffiti-red stays logo-only (sketch 001 manifest).
- Lock icons on ungranted sidebar items — the user explicitly wants staff to see the
  full feature map rather than a per-tier trimmed nav.
- Editors should experience the new shell from day one (locked nav + Editor link),
  not be shunted around it.

</specifics>

<deferred>
## Deferred Ideas

- **Short vanity URLs for editor pages** — e.g. `nocturna-avatars.site/shangri`
  instead of the current longer editor-page links. New capability (URL routing /
  domain-level change for the public presentation pages); candidate for Phase 10
  (editors integration) or roadmap backlog. Raised mid-discussion 2026-07-21.

</deferred>

---

*Phase: 3-Dashboard Shell + Tiered Access*
*Context gathered: 2026-07-21*
