# Phase 4: Settings Migration + Name Resolution - Context

**Gathered:** 2026-07-22
**Status:** Ready for planning

<domain>
## Phase Boundary

The Phase-2 owner settings panel (grouped typed tunables, server-side
validate-then-write, per-field errors, no secrets rendered) is folded into the
Phase-3 dashboard shell's **Settings section**, and every channel/role field
(`snowflake` and `role_list` schema types) renders a human-readable
`#channel` / `@role` name — with the raw ID beneath — resolved from a cache the
**bot pushes into the shared sqlite**, never a cold Discord REST call from the app.

Delivers SETT-01 (migration, no loss of functionality) and SETT-02 (readable
names). Full guild-populated channel/role **dropdown pickers** remain deferred
(FUT-01) — this phase adds readable names on the existing raw-ID inputs, not
pickers. Editing UX stays raw-ID input as locked in Phase 3 (D-07).

</domain>

<decisions>
## Implementation Decisions

### Settings page composition (SETT-01 migration)
- **D-01: One scrolling Settings page, feature groups.** The v1 tunables and the
  Phase-3 role→tier mapping live on a single Settings-section page. The mapping
  (`manager_roles` / `editor_roles`) becomes one more fieldset **"Access" group**
  alongside the existing feature groups (gallery, reviews, reminders, jinxxy,
  meetings, forum). One Save action for the whole page. Matches the existing
  grouped-form pattern and Phase-3's "Access group field" (D-05); no new tab/sub-nav
  pattern introduced.
- **D-02: Retire the standalone `/admin/settings` route.** The in-shell Settings
  section route becomes the *only* Settings URL. Remove the Phase-2 standalone
  page route rather than redirecting or keeping both. **Implementation note:** the
  existing 403-exception-handler special-case keyed on
  `request.url.path == "/admin/settings"` (app/main.py ~line 362) must be updated
  to the new section path so the styled in-shell 403 still fires for a
  non-owner / missing-session caller.
- **D-03: No loss of functionality (SETT-01, non-negotiable).** The migrated form
  keeps the exact Phase-2 contract: two-pass atomic validate-then-write
  (`settings.validate_only` all keys → 422 with error map if any invalid → only
  then `settings.set`), per-field inline errors, `require_owner` fail-closed gate,
  no secret ever rendered.

### Name display treatment (SETT-02)
- **D-04: Rich single-field display.** A resolved `snowflake` field shows the name
  (`#gallery`, `@Staff`) prominently, a **type/color cue** (channel-type icon for
  text/forum/voice; the role's Discord color as a swatch/tint), and the raw ID in
  small muted text beneath. Requires the bot cache to carry more than names — see
  D-08.
- **D-05: Role lists = one colored chip per role.** `role_list` fields
  (e.g. `GALLERY_STAFF_ROLE_IDS`, `manager_roles`, `editor_roles`) render each ID
  as its own readable `@role` chip tinted with the role color, ID available
  beneath/on the chip. The edit control stays the same comma-separated raw-ID
  input; chips are the read-side rendering.

### Unresolved / stale ID handling (SETT-02 robustness)
- **D-06: Per-field fallback, never blocks save.** When an entered ID has no cache
  entry (deleted/renamed, never in this guild, or pre-first-push), the field falls
  back to the raw ID with a muted **bilingual "name unavailable · no encontrado"**
  marker. The owner always sees the ID they set; resolution failure never prevents
  saving a valid ID.
- **D-07: Distinguish "cache not ready" from "genuinely gone."** Use a cache
  **freshness signal** (heartbeat-style — see D-08). When the cache is empty/stale
  (no recent bot push / bot offline), show a **section-level** "names loading — bot
  syncing" hint instead of flagging every field as broken. A cold start must not
  false-alarm every field as "deleted/unavailable."

### Bot-pushed name cache (channel — reuses Phase-3 pattern)
- **D-08: Cache carries id → name + kind + type/color + freshness, pushed via the
  established `@tasks.loop`→sqlite pattern.** The shared sqlite is the *only*
  bot↔app channel (locked project decision; no IPC/HTTP), exactly as
  `bot_heartbeat` / `jinxxy_sync_status` proved in Phase 3 (D-09/D-10). Each row
  resolves a snowflake to: display name, kind (`channel` vs `role`),
  channel-type (text/forum/voice) or role color, sufficient for D-04/D-05. A
  freshness marker (a last-push timestamp; the existing heartbeat freshness may be
  reusable) drives D-07's "cache ready?" decision.

### Resolution timing (edit-form UX)
- **D-09: Live client-side lookup.** Ship the id→{name, kind, color} cache into the
  Settings page as Alpine data so the readable name updates the instant the owner
  types/pastes a valid ID — before saving — catching a wrong-ID paste immediately.
  The cache is a single guild's channels+roles (small, owner-only surface), so
  shipping it to the browser is acceptable. Server-side render still resolves the
  initial paint from the same cache.

### Claude's Discretion
- Exact `name_cache` (or similar) table schema and column names.
- Bot-side push cadence and triggers (startup snapshot, periodic refresh loop,
  and/or Discord guild channel/role create-update-delete events) — deferred to
  researcher/planner; must land through the shared-sqlite pattern only.
- Whether the cache reuses the existing heartbeat freshness row or adds its own
  push-timestamp.
- Exact chip / swatch / icon styling within the variant-A dark-SaaS visual language
  (Inter, per-module accents, Nocturna red logo-only).
- Precise placement of the "Access" group among the feature groups on the page.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — SETT-01 (migrate v1 panel into shell, no loss of
  functionality) and SETT-02 (readable #channel/@role + ID beneath via bot-pushed
  cache); FUT-01 (guild-populated dropdown pickers — explicitly deferred).
- `.planning/ROADMAP.md` — Phase 4 goal + success criteria; Phase 3 context for the
  shell/Settings-section this migrates into.

### Prior phase context (patterns this phase rides on)
- `.planning/phases/03-dashboard-shell-tiered-access/03-CONTEXT.md` — D-05/D-07
  (mapping lives in the settings store as `manager_roles`/`editor_roles` with raw-ID
  inputs; dropdown pickers deferred to Phase 4/FUT-01), D-09/D-10 (bot
  `@tasks.loop`→shared-sqlite push pattern the name cache reuses), D-16 (styled
  in-shell 403 copy), and the `<code_context>` inventory of reusable assets.

### Prior design / spec
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — approved v1
  settings-panel design spec (store + panel invariants: validate-then-write,
  no-secrets, fail-closed owner gate) that SETT-01 must preserve.

### Visual contract
- `.planning/sketches/001-dashboard-shell/index.html` + `README.md` — variant-A
  shell chrome the migrated Settings section must match.
- `.planning/sketches/MANIFEST.md` — dark-SaaS aesthetic, Inter, Alpine.js (no build
  step), Nocturna red reserved for the logo.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/settings.py` — validated store: `_SCHEMA` allowlist with `type_tag`
  (`snowflake` / `role_list` / …), `all_for_ui()` (grouped label/min/max payload),
  `validate_only()` dry-run, `set()`, `SettingRejected`. The migrated form and the
  fields that get name resolution are exactly the `snowflake`/`role_list` entries here.
- `app/main.py` `settings_page` (`GET /admin/settings`) + `save_settings`
  (`POST /admin/settings`, two-pass validate-then-write, 422 error map) — the v1
  route logic to move into the shell Settings section (D-01/D-02/D-03).
- `app/templates/settings.html` — Alpine grouped form with per-type field templates
  (`snowflake`, `role_list`, int_range, timezone, …), `errors[]` binding, toast.
  Extend the `snowflake`/`role_list` templates for name/chip rendering + live lookup.
- `app/deps.py::require_owner` — unchanged fail-closed owner gate for the migrated
  route.
- `core/db.py` — the Phase-3 `bot_heartbeat` / `jinxxy_sync_status` init + upsert
  helpers (single-row `CHECK (id=1)`, `INSERT OR REPLACE`, fresh-connection-per-call,
  WAL) are the exact template for the name-cache table and its push helper.
- `cogs/heartbeat.py` — the `@tasks.loop` that upserts liveness every ~45s: the
  model for the bot-side cache push loop (D-08).
- `app/static/alpine.min.js` — already shipped; powers the D-09 live client-side lookup.

### Established Patterns
- Shared sqlite (`DB_PATH`, WAL) is the ONLY bot↔app channel — no IPC/HTTP. The name
  cache MUST use it (D-08).
- Server-side validate-then-write for every settings mutation; no secrets rendered;
  POST-only mutations; bilingual (ES/EN) user-facing copy.
- Owner-only Settings via `require_owner`, fail-closed on the `0`/unset default.
- The 403 exception handler special-cases the Settings path to render the styled
  in-shell forbidden page — must track the route change (D-02).

### Integration Points
- Bot side: a new cache-push `@tasks.loop` (and/or guild event listeners) writing
  channel/role name+kind+color+freshness into the shared sqlite.
- App side: the Settings section route reads the cache to resolve field values at
  render and ships the map to Alpine for live lookup; the v1 GET/POST logic collapses
  into this section route.

</code_context>

<specifics>
## Specific Ideas

- "Name unavailable · no encontrado" — bilingual fallback marker, muted, in the
  house ES/EN style (D-06).
- "Names loading — bot syncing" — section-level state when the cache is cold/stale,
  distinct from a genuinely-deleted ID (D-07).
- Role chips tinted with the actual Discord role color; channel fields show a
  type icon (text/forum/voice) (D-04/D-05).

</specifics>

<deferred>
## Deferred Ideas

- **Guild-populated channel/role dropdown pickers (FUT-01)** — full picker UI that
  replaces raw-ID entry. This phase ships readable names on the existing ID inputs
  only; pickers remain future polish per REQUIREMENTS.md FUT-01 and Phase-3 D-07.

</deferred>

---

*Phase: 4-Settings Migration + Name Resolution*
*Context gathered: 2026-07-22*
