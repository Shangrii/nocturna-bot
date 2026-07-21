# Project Research Summary

**Project:** Nocturna Bot v2.0 Staff Dashboard
**Domain:** MEE6-style multi-tier staff/admin dashboard grafted onto an existing two-process Discord bot (discord.py) plus FastAPI admin app, sharing a single sqlite file
**Researched:** 2026-07-21
**Confidence:** HIGH

## Executive Summary

This is not a greenfield dashboard build. It is an extension of an already-shipped, disciplined FastAPI plus discord.py plus sqlite system into a full MEE6-style staff dashboard (sidebar, 7 modules, tiered access, editable permissions). Every research pass converged on the same conclusion: the codebase's own established idioms (shared-sqlite-as-only-IPC-channel, require_owner/require_editor fail-closed auth, vendored Alpine.js plus Jinja2, CREATE TABLE IF NOT EXISTS cog-owned tables, tasks.loop polling cogs) are sufficient to build all nine target features with zero new pip dependencies. The recommended architecture generalizes two patterns the bot already proved in v1: the presence table (bot pushes cached state to the app) becomes the template for discord_names/gallery_pending/reviews_pending, and a new action_queue table (app requests, bot executes) is the write-side mirror that lets the panel trigger bot-owned actions (publish, sync, re-publish) without ever holding write-capable Discord credentials itself.

The recommended approach is: build the tiered-access dependency (require_tier) and the dashboard shell with a hard POST-only convention FIRST (everything else depends on it for access-gating and inherits its CSRF discipline); route every panel-initiated Discord write (gallery/reviews approve, meeting re-publish) through the bot process via the action-queue pattern rather than duplicating publish logic or handing bot credentials to the FastAPI process; and treat Discord name resolution as bot-gateway-cache-pushed (zero incremental REST calls) rather than the admin app calling Discord REST cold.

The key risks are all trust-boundary and concurrency risks, not technology risks: (1) an editable role-to-tier mapping that could lock out the owner or let a Manager self-elevate if tier-assignment writes are not hard-gated to require_owner exclusively; (2) a check-then-act publish race once the panel becomes a second writer alongside the live Discord reaction flow; (3) sqlite writer/writer contention as the panel adds write volume (WAL solves reader/writer blocking only, not writer/writer); (4) reintroducing bot credentials into the admin app, reversing a locked v1 security decision; and (5) GET-triggered "quick action" links silently breaking the existing SameSite=Lax CSRF model. All five have concrete, cheap mitigations documented in PITFALLS.md and should be designed in from the start of the relevant phase, not retrofitted.

## Key Findings

### Recommended Stack

Zero new pip dependencies for this milestone. Every capability -- Discord name resolution, bot-side action triggering, the MEE6-style shell, table+modal CRUD -- is achievable by extending patterns the codebase already uses. This mirrors the project's own documented discipline of rejecting new dependencies (e.g., slowapi) in favor of extending what's already installed and proven.

**Core technologies (all already installed, no version change):**
- httpx 0.28.1 (async client): Discord REST calls for role/channel resolution. Already the exact tool app/auth.py has_editor_role uses for a bot-token REST call.
- sqlite3 (stdlib) plus existing WAL pragma: the ONLY cross-process channel between bot and admin app. v2.0 adds tables to the same file rather than introducing IPC/a broker.
- discord.ext.tasks (via discord.py 2.7.1): short-interval poll loop (tasks.loop seconds=5-10) that turns a sqlite row into a real Discord action. Same idiom as cogs/jinxxy.py and cogs/reminders.py.
- Jinja2 3.1.6 plus vendored Alpine.js 3.15.12: server-rendered dashboard shell (base.html plus per-module block) with client-side reactivity for toggles/modals. Both already shipped and used in editor.html/settings.html.

**Key techniques (not libraries):** in-process TTL dict cache for resolved channel/role names (5-10 min TTL); a new bot_commands/action_queue sqlite table plus short-poll cog to trigger bot-side actions from FastAPI; new tables via CREATE TABLE IF NOT EXISTS for meeting persistence and pending-state caches; a Depends(require_tier(...)) generalization of the existing require_editor/require_owner dependency chain.

Full detail: .planning/research/STACK.md

### Expected Features

PROJECT.md already locks this milestone's feature scope. Research validated the dashboard mechanics for each feature against ecosystem convention (MEE6/Dyno/Carl-bot/Wick) rather than proposing new features.

**Must have (table stakes):**
- Sidebar nav with active-state highlight, per-module status indicator (badge, not a functional kill-switch for modules with no real "off" state)
- CRUD table plus modal pattern for list-type data (Reminders)
- Approval queue (pending list plus approve/reject) with parity to the existing checkmark/moon reaction flow (Gallery, Reviews)
- Manual sync trigger with last-run status, disabled/spinner while in-flight, guarded against overlap with the scheduled poll (Jinxxy)
- Readable #channel/@role names with raw ID shown beneath (already committed, POLISH-01)
- Overview/home landing page: status only, no quick-actions, no log console (explicitly scoped down)
- Role-to-tier assignment UI (owner-only): gates every other module's per-tier visibility

**Should have (differentiators, no direct competitor equivalent):**
- Meetings browser with summary edit plus re-publish (unique to Nocturna's Whisper/Ollama pipeline). Re-publish must edit the existing forum post, not duplicate it.
- Custom editable role-to-tier mapping beyond Discord's native permission model (closer to Wick's Custom Permits than MEE6/Dyno/Carl-bot's Discord-permission-only model). Keep to a flat 3-tier model.
- Editors presentation section folded into the same shell rather than left standalone

**Defer (explicitly out of scope, future consideration only):**
- Audit/activity log per approval action
- Global per-module functional kill-switches for Gallery/Reviews/Meetings
- Granular Wick-style per-capability permission builder
- Multi-guild support
- Real-time websocket-pushed live state (manual refresh/polling is sufficient at this scale)

Full detail: .planning/research/FEATURES.md

### Architecture Approach

Both processes remain separate OS processes (two systemd units) exactly as today; nothing in this milestone introduces a third process, socket, or direct RPC. The shared sqlite file stays the only channel. This milestone generalizes it in two directions: a reverse-direction cache (bot to app, extending the presence precedent) for discord_names/gallery_pending/reviews_pending, and a new forward-direction command queue (app to bot, generalizing the settings-write precedent) via an action_queue table for any action that must run inside the bot's own Discord/business-logic context.

**Major components:**
1. app/deps.py require_tier(min_tier): NEW, resolves owner/manager/editor via session plus live Discord role re-check plus the settings-stored role-to-tier mapping; subsumes require_editor/require_owner
2. core/action_queue.py (pure, framework-agnostic) plus a bot-side ActionQueueCog (tasks.loop seconds=5): generic enqueue/claim/complete against a new action_queue table; the ONE new genuinely-new cross-process contract this milestone adds
3. core/discord_names_sync.py plus DiscordNamesCog: bot-side, pushes its already-live gateway cache (guild.channels/guild.roles) into a discord_names table on on_ready/update events; zero incremental REST calls
4. app/routers/{gallery,reviews,reminders,jinxxy,meetings}.py: new FastAPI routers behind require_tier("manager"); reminders is pure DB CRUD (no queue), the other four enqueue into action_queue and poll for status
5. cogs/gallery.py / cogs/reviews.py _publish/_unpublish: thin refactor to be callable by either the reaction listener or the new queue dispatcher, preserving single-writer discipline for GitHub publish/Discord write actions

Key anti-patterns flagged: never let the FastAPI process make write-side Discord REST calls directly (reactions, forum posts); route through the action queue instead. Never stand up an internal HTTP endpoint on the bot process (reverses the locked "sqlite is the only channel" decision). Never let the panel bypass the reaction bookkeeping when publishing, since it's the durable published-state flag the live reaction handler checks.

Full detail: .planning/research/ARCHITECTURE.md

### Critical Pitfalls

1. **Editable role-to-tier mapping locks out the owner or lets Manager self-elevate** -- Keep tier-assignment writes owner-gated ONLY (require_owner, never a generic manager-or-higher check); derive tier from one resolve_tier() function with the owner check (fixed DISCORD_USER_ID comparison) always first; never allow "owner" as an assignable tier value in a POST body. Owner lockout is impossible by construction as long as this boundary holds, but only if it's tested directly against the endpoint, not just verified via UI hiding.

2. **Check-then-act publish/unpublish race between the panel and the live reaction flow** -- Once the panel's Approve button is a second writer, the same message can be approved via Discord reaction and via panel click close enough in time to double-publish. Route BOTH the reaction handler and panel actions through the same single bot-side function (via the action queue, since the panel is a separate process); never let the panel call github_publish.* directly.

3. **sqlite writer/writer contention as the panel adds write volume** -- WAL solves reader/writer blocking, NOT writer/writer contention. As the panel becomes a frequent writer (triage-clearing 15 gallery photos, reminders CRUD), unhandled "database is locked" errors become likely. Add an explicit busy_timeout pragma plus retry-with-backoff wrapper on new panel write paths before shipping the first write-heavy phase (Gallery).

4. **Reintroducing Discord bot credentials into the admin app** -- Adding BOT_TOKEN (or equivalent) to the admin app for name resolution/actions reverses a locked v1 credential-isolation decision, doubling the blast radius of a token leak. Scope any credential to read-only name resolution; route every write-capable Discord action through the bot process via the action queue, never directly from app/.

5. **GET-triggered "quick action" links silently break SameSite=Lax CSRF coverage** -- SameSite=Lax blocks cross-site POST but NOT cross-site top-level GET navigation. Every new state-changing dashboard action (approve/pause/delete/sync-now) must be POST/PUT/DELETE, enforced by a route-enumeration test. Establish this convention in the dashboard-shell phase before any module-specific action endpoints exist.

(A sixth pitfall -- the reminders scheduler silently undoing or outrunning a concurrent panel edit/delete via a check-then-act race on the same row -- should be mitigated in the Reminders CRUD phase specifically via a version column or re-fetch-before-act.)

Full detail: .planning/research/PITFALLS.md

## Implications for Roadmap

Based on combined research, the phase order should follow the dependency chain research surfaced repeatedly: tiered access and the POST-only/CSRF convention must exist before any module ships, a cross-cutting sqlite-hardening pass should land before the first write-heavy module (Gallery), and the two write-credential decisions (name resolution reads, meeting re-publish writes) should be treated and reviewed as separate, sequenced decisions rather than one blanket "give the admin app Discord access" choice.

### Phase 1: Dashboard Shell + Tiered Access Foundation
**Rationale:** Every other module depends on require_tier existing and being enforced first; this mirrors how require_owner had to exist before the v1 settings panel could ship. This phase must also establish the POST-only convention project-wide, since retrofitting it later means auditing every module.
**Delivers:** base.html shell with sketch-001-variant-A sidebar; core/access.py resolve_tier(); app/deps.py require_tier(min_tier); owner-gated role-to-tier mapping storage/UI in Settings; a route-enumeration test asserting no state-mutating route is GET-only.
**Addresses:** Dashboard shell + sidebar routing, Role-to-tier mapping + enforcement (FEATURES.md P1 items)
**Avoids:** Pitfall 1 (self-elevation/lockout), Pitfall 6 (GET-based CSRF gap)

### Phase 2: Settings Migration + Discord Name Resolution
**Rationale:** Lowest-risk migration of an already-shipped feature (good early confidence builder), and the first phase that genuinely needs a Discord-credential-scope decision. Resolving that here, narrowly (read-only, bot-gateway-cache-pushed), prevents later phases from reusing an over-scoped credential for a purpose it was not reviewed for.
**Delivers:** core/discord_names_sync.py + DiscordNamesCog (gateway cache to discord_names table, zero incremental REST calls); Settings page migrated into the shell rendering channel/role names with raw ID fallback.
**Uses:** httpx (only if REST fallback needed), sqlite CREATE TABLE IF NOT EXISTS idiom, existing presence-table precedent
**Implements:** Pattern 2 (reverse-direction cache table, bot to app)

### Phase 3: Cross-Cutting sqlite Hardening + Action Queue Infrastructure
**Rationale:** Every subsequent write-heavy module (Reminders, Gallery, Reviews, Meetings) inherits whatever the connection helper and the app-to-bot trigger mechanism look like at this point. Doing this once, deliberately, before the first write-heavy module avoids a scramble after a production database-locked report.
**Delivers:** Explicit busy_timeout pragma plus retry/backoff wrapper on write paths; core/action_queue.py (pure) plus ActionQueueCog (tasks.loop) generic enqueue/claim/complete plumbing, unit-tested independent of any specific module.
**Avoids:** Pitfall 3 (sqlite writer/writer contention)
**Implements:** Pattern 1 (generalized command queue, app to bot)

### Phase 4: Reminders CRUD (standalone module)
**Rationale:** No cross-module dependency beyond the shell/tier system already built; good candidate for the first new module since it validates the table+modal CRUD pattern without the added complexity of the action-queue hand-off.
**Delivers:** Full CRUD + pause/resume for Reminders via table+modal pattern; a version/updated_at guard (or re-fetch-before-act) in the scheduler to close the panel-edit-vs-scheduler race.
**Addresses:** Reminders CRUD + pause/resume (FEATURES.md P1)
**Avoids:** Pitfall 7 (scheduler vs. panel reminder-edit race)

### Phase 5: Gallery + Reviews Approval Queues
**Rationale:** Both share the same queue-UI shape and, critically, the same publish-race risk against the live reaction flow. Sequencing them together lets the cross-process hand-off design (built in Phase 3) be validated once and reused, rather than solved twice.
**Delivers:** Approval queue UI (pending list, approve/reject) for both modules, routed entirely through the action_queue to bot-side publish/unpublish (same method the reaction flow calls); gallery_pending/reviews_pending cache tables.
**Addresses:** Gallery approval queue, Reviews approval queue (FEATURES.md P1)
**Avoids:** Pitfall 2 (check-then-act publish race)

### Phase 6: Jinxxy Manual Sync + Status
**Rationale:** Lower complexity than Gallery/Reviews (rare trigger frequency, low write volume) and reuses the same action-queue infrastructure already proven in Phase 5. Sequence after the queue pattern is battle-tested on a higher-volume module.
**Delivers:** Sync-now button (disabled/spinner while in-flight) wired to a jinxxy_sync action-queue kind calling the existing sync method; persisted last-run status readable by both processes.
**Addresses:** Jinxxy manual sync + status (FEATURES.md P1)

### Phase 7: Meetings Browser + Edit + Re-publish
**Rationale:** Highest complexity (new write-credential decision, editing a live forum post from a second process) and the first phase requiring net-new persistence (meetings currently have zero durability). Sequenced last among modules so this credential decision does not block everything else, per FEATURES.md's explicit dependency note.
**Delivers:** meetings table (bot writes at publish time); browse/edit UI; a meeting-republish action-queue handler that edits the stored thread's post; idempotency guard so a double-click/retry does not duplicate the forum post.
**Addresses:** Meetings browser + edit + re-publish (FEATURES.md P1, sequenced last per its own dependency note)

### Phase 8: Editors Section Integration
**Rationale:** Mostly routing/auth-tier integration work since the editor app's logic and auth already exist; can run in parallel with other modules once the shell/tier system exists, but sequenced last here since it is lower risk and lower priority (P2) than the modules above.
**Delivers:** Editors presentation section folded into the shared dashboard shell under the tier system.
**Addresses:** Editors section integration (FEATURES.md P2)

### Phase Ordering Rationale

- Tiered access must exist before any module's per-tier visibility is meaningful to build or test (FEATURES.md dependency graph, ARCHITECTURE.md Pattern 3).
- The two Discord-credential decisions (read-only name resolution vs. write-capable action-triggering) are treated as separate phases specifically because PITFALLS.md and FEATURES.md both independently flag that approving one should not silently green-light the other's larger blast radius.
- sqlite hardening is pulled forward to its own phase (rather than left to whichever module hits it first) because PITFALLS.md is explicit that every later write-heavy phase inherits whatever the connection helper looks like at that point.
- Gallery/Reviews are grouped together (not sequenced across separate phases) because they share the identical publish-race pitfall and queue-UI shape. Solving the cross-process hand-off once and reusing it avoids solving the same race problem twice.
- Meetings is sequenced last among modules per FEATURES.md's own explicit dependency note (highest complexity, newest credential-boundary question) and Editors integration last overall since it is lower priority (P2) and lowest architectural risk.

### Research Flags

Phases likely needing deeper research during planning (plan-phase with research-phase flag):
- **Phase 1 (Tiered Access):** The owner/Manager divergence risk (Pitfall 1) and the CSRF route-enumeration test design are novel enough to this codebase to warrant a focused pass before implementation.
- **Phase 5 (Gallery + Reviews queues):** The cross-process publish-race mitigation (Pitfall 2) and the exact action-queue dispatch shape need concrete design (which fields, how the panel polls, how idempotency is guaranteed) before coding starts.
- **Phase 7 (Meetings):** The write-credential decision (editing a live forum post from a queued bot action) and idempotent re-publish design are genuinely new territory, with no direct precedent in this codebase or the competitor set.

Phases with standard, well-documented patterns (research-phase can likely be skipped):
- **Phase 2 (Settings + name resolution):** Directly extends the proven presence-table pattern; batching/caching guidance is concrete and already fully specified in STACK.md and PITFALLS.md.
- **Phase 4 (Reminders CRUD):** Standard table+modal CRUD; the scheduler-race mitigation has two concretely specified options in PITFALLS.md.
- **Phase 6 (Jinxxy sync):** Thin wiring onto an already-existing, already-tested sync method via infrastructure proven in Phase 5.
- **Phase 8 (Editors integration):** Mostly routing/auth-tier fit onto existing, working logic.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations verified directly against this repository's own shipped code (app/auth.py, core/db.py, cogs, requirements.txt); no unverified new libraries proposed; PyPI version checks confirmed no bump needed. |
| Features | MEDIUM | Ecosystem convention (MEE6/Dyno/Carl-bot/Wick) verified via docs, GitHub template architecture, and cross-source agreement rather than live product screenshots (several dashboards are client-rendered SPAs behind auth, limiting direct verification); this milestone's own feature scope is already locked in PROJECT.md, so this research validated mechanics rather than proposing new features. |
| Architecture | MEDIUM-HIGH | Grounded directly in this codebase's existing code and two already-validated precedents (presence table, settings read-at-use); the genuinely new pieces (action_queue, discord_names_sync) are extensions of proven patterns, not novel unverified designs. |
| Pitfalls | HIGH | Every pitfall is grounded in specific lines/functions read directly from this repo (core/db.py, cogs/gallery.py, cogs/reminders.py, app/deps.py); general web/SQLite/Discord-API knowledge (CSRF, WAL contention, rate limits) is cross-checked against external sources and flagged MEDIUM/LOW separately where it fills a gap. |

**Overall confidence:** HIGH

### Gaps to Address

- **Exact Discord-credential scope for name resolution** is flagged Pending in PROJECT.md's Key Decisions and resolved here only at the recommendation level (bot-gateway-cache-push, not admin-app REST calls). Get explicit sign-off on this scope decision during Phase 2 planning before writing code, per Pitfall 4.
- **Gallery/Reviews pending-state schema** -- FEATURES.md flags that it is unverified whether the current schema already exposes a queryable pending state or whether a denormalized flag/table is needed; verify during Phase 5 planning before committing story points.
- **CSRF/SameSite reasoning for GET-based actions** is corroborated only via general web-security knowledge, not an independently re-verified dated external source. Flag for validation if a dedicated CSRF-hardening spike is ever done (noted directly in PITFALLS.md sources).
- **Meetings re-publish idempotency** -- no existing precedent in this codebase for editing an already-posted forum message from a second trigger path; the exact retry-safe design needs to be worked out during Phase 7 planning, not assumed from this research.

## Sources

### Primary (HIGH confidence)
- This repository, read directly: app/auth.py, app/deps.py, app/main.py, core/db.py, core/settings.py, core/jinxxy_api.py, core/store_sync.py, core/github_publish.py, cogs/jinxxy.py, cogs/meeting.py, cogs/gallery.py, cogs/reviews.py, cogs/reminders.py, cogs/presence.py, bot.py, requirements.txt
- .planning/PROJECT.md -- v2.0 scope, constraints, locked Key Decisions (sqlite-only IPC, owner-gated trust boundary changes)
- .planning/sketches/001-dashboard-shell/index.html and README.md -- visual contract (variant A winner)
- Discord Developer Docs, Rate Limits (docs.discord.com/developers/topics/rate-limits) -- verified rate-limit header names and backoff guidance
- fuma-nama/discord-bot-dashboard (GitHub) -- actual repo content confirming Features/Actions tab split and toggle/publish patterns

### Secondary (MEDIUM confidence)
- MEE6 Wiki Dashboard page and Dyno Docs (Modules/Reminders/Dashboard Settings) -- module-toggle and appeal-queue patterns corroborated via search snippets (client-rendered SPAs limited direct verification)
- Carl-bot about page -- permission model confirmed as Discord role-position based
- Wick Docs (Custom Permits / v5.0.0 changelog) -- independent tier-abstraction precedent
- SQLite User Forum (WAL single-writer/busy_timeout limitations) and Bert Hubert's article on SQLITE_BUSY despite timeout -- corroborate writer/writer contention guidance

### Tertiary (LOW confidence)
- General SaaS "manual sync + last-run status" UX convention (Stripe/GitHub/Zapier-class patterns) -- HIGH confidence as a general admin-UI pattern, LOW confidence as a Discord-dashboard-specific pattern (no direct prior-art source found)
- General CSRF/SameSite reasoning -- standard web-security knowledge, not independently re-verified against a dated external source in this pass

---
*Research completed: 2026-07-21*
*Ready for roadmap: yes*
