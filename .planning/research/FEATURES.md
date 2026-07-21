# Feature Research

**Domain:** Single-guild Discord bot staff/admin dashboard (MEE6/Dyno/Carl-bot/Wick class)
**Researched:** 2026-07-21
**Confidence:** MEDIUM (product dashboards are client-rendered SPAs behind auth; UI patterns
verified via docs, GitHub template architecture, and cross-source agreement rather than
live screenshots — see per-item notes)

Scope note: this milestone already has its feature list locked in `PROJECT.md` (Active
section). This research does not propose new features — it validates the **dashboard
mechanics** for each already-scoped feature against ecosystem convention, and flags what
similar products do that Nocturna should explicitly NOT copy.

## Feature Landscape

### Table Stakes (Users Expect These)

Features/behaviors staff will assume exist because every comparable bot dashboard has them.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Sidebar nav, one item per module, active-state highlight | Universal in MEE6/Dyno/Carl-bot/Wick; sketch 001 variant A already committed to this | LOW | Already decided (sketch winner). No further research needed. |
| Per-module page header with a status/state indicator | MEE6's defining pattern is a big toggle per module page; staff will expect *some* visible "is this on/working" signal | LOW | See Anti-Features — recommend a **status badge**, not a functional kill-switch, for Gallery/Reviews/Meetings (they have no "off" state in scope). Jinxxy legitimately has one (last-sync status). Reminders has real pause/resume per-item, not per-module. |
| CRUD table + modal for list-type data (Reminders) | Standard admin-panel pattern; also how the community-built Discord dashboard templates (e.g. `fuma-nama/discord-bot-dashboard`) implement "Actions" — form-in-modal, publish/save, row-level edit/delete | MEDIUM | Table: columns for schedule/next-fire/status; row actions edit, pause/resume, delete; "+ New" opens the same modal in create mode. Inline validation before submit (matches existing `settings.set` validate-then-write discipline). |
| Approval queue: pending list + approve/reject per item | Direct parity requirement with the existing ✅/🌙 Discord reaction flow (PROJECT.md); approval queues are the standard pattern for any Discord moderation dashboard (Dyno's ban/mute appeal queue: approve/reject/view-history per submission) | MEDIUM | Card or row per pending item; approve = same code path as ✅ reaction (publish to repo); reject/remove = same as 🌙. Optimistic removal from queue on action, with server-confirmed state (avoid double-approve race if two staff act on the same item). |
| Manual sync trigger with last-run status | Not Discord-dashboard-specific but universal SaaS integration pattern (Stripe/GitHub/Zapier "Sync now" + "Last synced X ago" + spinner + error surfaced inline) | LOW–MEDIUM | Button must disable/spinner while in-flight and the trigger must guard against overlapping runs with the existing periodic poll (reuse one code path, don't fork a second sync implementation). Persist last-run timestamp + result (success/error) somewhere both the bot process and the panel can read — same shared-sqlite channel already used for settings. |
| Readable names for channel/role (#name, @role) with raw ID shown beneath | Universal across MEE6/Dyno/Carl-bot — none of them show a raw snowflake as the primary label in settings UI; they resolve to Discord's own mention-chip style | MEDIUM | Already the committed v2.0 approach (POLISH-01, sketch 001 confirms "mejor que el ID pelado actual"). Requires Discord API read access from the admin app — a credential/scope decision already flagged as Pending in PROJECT.md Key Decisions; this is an architecture dependency, not a features one. |
| Overview/home landing page | Users always land somewhere after login; every dashboard studied has a default/home view | LOW | PROJECT.md explicitly scoped this down: bot status only, no quick-actions (variant C rejected), no log console. Keep it a summary/status page, resist scope creep back toward variant C. |
| Role → tier assignment UI (owner-only) | Every staff-facing dashboard with more than one access level needs *some* place to say "this role = this access"; Wick's Custom Permits and simpler role-gated dashboards (Carl-bot: Discord role position + Manage Server permission) both need a resolvable mapping | MEDIUM | Nocturna's version is more explicit than MEE6/Dyno/Carl-bot (which mostly key off Discord's native "Manage Server" permission or role hierarchy, not a custom tier table) — see Differentiators. Must exist and be enforced *before* any per-tier module visibility can be verified, so it gates the rest of the shell. |

### Differentiators (Competitive Advantage)

Not required by ecosystem convention, but valuable and specific to Nocturna's existing
pipeline. None of the reference products (MEE6, Dyno, Carl-bot, Wick) have direct
equivalents.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Meetings browser with summary edit + re-publish | No comparable Discord bot dashboard has a "voice meeting → AI summary → editable forum post" workflow; this is unique to Nocturna's Whisper/Ollama pipeline | HIGH | Re-publish should **edit the existing forum post**, not create a duplicate — requires the admin app to trigger a Discord message edit. That's a new credential-boundary decision (bot-token-class write from a second process), same class of decision as Discord-API name resolution; flag for architecture research, not just features. |
| Custom editable role→tier mapping (owner/Manager/editor) beyond Discord's native permission model | MEE6/Dyno/Carl-bot lean on Discord's own "Manage Server" permission or role position; only Wick (Custom Permits, v5) builds an independent tier abstraction, and that's considered one of Wick's most advanced/differentiating features | MEDIUM–HIGH | Confirms this is a legitimately more sophisticated pattern than the median bot dashboard — worth the complexity because it lets ops staff (Managers) operate without touching Discord's Server Settings at all. Keep it to a flat 3-tier model (see Anti-Features) rather than a Wick-style permission builder. |
| Approval queue with Discord-reaction-flow parity (✅/🌙 semantics carried into the UI) | Staff already have muscle memory from the reaction workflow; a dashboard queue that mirrors it (not a generic "pending/rejected" abstraction) lowers the training cost to near zero | LOW–MEDIUM | Cheap differentiator — mostly a labeling/interaction-model choice, not new architecture. |
| Editors presentation section folded into the same shell (not a separate app) | Editors already have a working self-serve app; folding it in as a dashboard section (rather than leaving it as a standalone URL) is a real UX improvement most bot dashboards don't need to solve (they don't have a "creator self-service" tier at all) | LOW–MEDIUM | Mostly a navigation/routing integration since the editor app's logic and auth already exist — main work is fitting it under the shared shell/tier system, not rebuilding it. |

### Anti-Features (Commonly Requested, Often Problematic)

Patterns visible in the reference products that Nocturna should explicitly avoid copying.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Global per-module on/off kill-switch (MEE6's literal big toggle, applied to Gallery/Reviews/Meetings) | Sketch 001 variant A visually includes a "toggle grande on/off" per module, and it's MEE6's signature affordance, so it's tempting to implement it everywhere for visual consistency | Gallery/Reviews/Meetings have no designed "off" state — disabling them mid-flight could silently break the cross-repo publish pipeline or leave a meeting mid-transcription; none of this is in PROJECT.md scope, and it reopens a trust-boundary/blast-radius question that Phase 1/2 explicitly closed for settings | Keep the visual toggle affordance from the sketch for modules that legitimately have one (Reminders pause/resume is per-item; Jinxxy sync has a real "last run" state) and render the rest as a static "Active" status badge, not an interactive switch |
| Multi-guild / server switcher (MEE6, Dyno, Carl-bot, Wick all support many guilds per login) | Standard SaaS-bot-dashboard expectation; every reference product has it | Explicitly out of scope per PROJECT.md ("single Nocturna guild") — building a guild switcher is pure wasted complexity for a project that will only ever have one guild | Hardcode the single guild context everywhere; no guild-selection UI |
| Full audit/mod-log console (Wick's detailed action-log stream, Carl-bot's logging config) | Feels like a natural companion to an approval queue / permission system | Explicitly out of scope per PROJECT.md ("Log viewer / process monitoring... not an ops log console") — this is a real scope-creep magnet once staff start asking "who approved this" | Overview shows bot status + simple last-activity timestamps per module; defer a real audit trail to a future milestone if staff actually ask for it post-launch |
| Real-time websocket-pushed live dashboard state (bot health, sync status streamed live) | Feels modern; some larger bot dashboards do this for uptime/member-count widgets | Adds a websocket server + reconnect/backoff logic for a 3-tier, single-guild, small-staff dashboard — disproportionate infra cost for the actual value (staff refresh a page a few times a day, not monitor it like an ops console) | Manual refresh / simple polling on page load; the existing shared-sqlite read-at-use model already covers "is this fresh enough" |
| Wick-style granular permission-builder (dozens of individually toggleable capabilities per custom tier) | Once you have "editable tiers," it's tempting to make every capability independently checkboxable for maximum flexibility | Over-engineered for a 3-tier, single-guild staff of a handful of people; every extra checkbox is another thing the owner has to get right to avoid a trust-boundary mistake (same class of risk `require_owner`/`require_editor` was built to close) | Fixed 3-tier model (owner > Manager > editor) with a simple role→tier dropdown mapping; no per-capability matrix |
| Dashboard writing Discord role assignments back to members (some higher-end bots let you assign/remove member roles from the panel) | Feels like a natural extension of "role→tier mapping" once you're already reading roles | Scope creep beyond what's asked — PROJECT.md only requires mapping *existing* Discord roles to internal tiers, not managing Discord's own role membership from a second process; this would also reopen the credential-boundary question at a much larger blast radius (member management vs. read-only role listing) | Dashboard reads existing Discord roles (for the mapping dropdown) and writes only to the internal tier-mapping table; role assignment to members stays in Discord itself |

## Feature Dependencies

```
Role -> tier mapping storage + enforcement middleware
    └──requires──> Discord API read access (role list) from the admin app
                       └──shared architecture decision with──> Readable channel/role
                                                                names (Settings + everywhere
                                                                else IDs currently show)

Dashboard shell (sidebar + per-tier route guards)
    └──requires──> Role -> tier mapping + enforcement (must exist before ANY module's
                     per-tier visibility can be verified)

Gallery approval queue ──requires──> queryable "pending" state on gallery items
Reviews approval queue ──requires──> queryable "pending" state on reviews
    (verify existing schema exposes this, or it needs a small addition — flag for
     architecture-phase research, not assumed here)

Jinxxy manual sync + status
    └──requires──> existing periodic-sync function made safely re-triggerable
                     (single code path, overlap guard) + a persisted last-run
                     status field readable by both processes (reuses the shared-sqlite
                     settings channel from v1)

Meetings edit + re-publish
    └──requires──> admin app can trigger a Discord message edit
                       └──same class of decision as──> Discord API read access above,
                                                         but WRITE not read — larger
                                                         credential-boundary question,
                                                         should get its own architecture
                                                         research pass

Editors presentation section integration ──enhances──> Dashboard shell
    (mostly a routing/auth-tier fit, since editor app logic/auth already exists)

Per-module functional kill-switch ──conflicts──> Gallery/Reviews/Meetings (no designed
    "off" state) — see Anti-Features; only Reminders (per-item pause/resume) and Jinxxy
    (sync state) have a real on/off-shaped state today
```

### Dependency Notes

- **Dashboard shell requires Role→tier mapping first:** every other module's "does this
  user see this page" check depends on the tier system existing and being enforced. This
  should be the first phase, mirroring how `require_owner` had to exist before the v1
  settings panel could ship.
- **Readable names and Meetings re-publish share a credential-boundary shape** (admin app
  reaching into Discord's API from what was previously a bot-token-free process) but differ
  in severity — read-only name resolution vs. an authenticated write (editing a live forum
  post). Recommend treating them as two separate decisions even though they're architecturally
  similar; don't let approval of one silently green-light the other's scope.
- **Approval queues need a "pending" state that already answers "what does a photo/review
  look like before it's approved."** If the current schema only tracks `published`/`not
  published` and infers "pending" from reaction presence, the dashboard needs a poll or a
  denormalized flag — worth a quick architecture check before committing story points to a
  phase.
- **Manual sync is a status-machine problem, not a button problem.** The complexity isn't the
  click — it's making sure the manual trigger and the scheduled poll can't run concurrently
  and stomp each other's state, and that the panel can show a meaningfully fresh "last
  synced" value from a process it doesn't share memory with (same shared-sqlite pattern that
  already solved this for settings in v1).

## MVP Definition

PROJECT.md already locks this milestone's scope (all items below are "Active," not
speculative) — so this section maps ecosystem convention onto phase-ordering priority
rather than proposing a smaller launch.

### Launch With (this milestone)

- [ ] Dashboard shell + sidebar routing — every other module depends on it existing
- [ ] Role→tier mapping (owner-only) + enforcement middleware — gates every other page's
      access control; must land before per-tier testing is meaningful
- [ ] Settings migrated into shell with readable names — lowest-risk migration of an
      already-shipped feature, good early-phase confidence builder
- [ ] Reminders CRUD + pause/resume — standalone, no cross-module dependency, good
      candidate for the first "new" module built
- [ ] Gallery approval queue — needs the pending-state check (Dependency Notes) resolved
      first
- [ ] Reviews approval queue — same shape as Gallery, can likely share the queue UI pattern
- [ ] Jinxxy manual sync + status — needs the overlap-guard/status-field work done first
- [ ] Meetings browser + edit + re-publish — highest complexity (new write-credential
      decision), sequence last among modules so the credential decision doesn't block
      everything else
- [ ] Editors presentation section folded into shell — mostly integration work, can be
      done in parallel with other modules once the shell/tier system exists

### Add After Validation (not this milestone, but natural next asks)

- [ ] Audit/activity log per approval action ("who approved this photo") — likely the first
      thing staff ask for once the approval queue is live; deliberately deferred per
      PROJECT.md Out of Scope
- [ ] Live-interval hot-swap for loop-based settings — deferred per Key Decisions, revisit
      if "apply next cycle" proves annoying in practice

### Future Consideration (explicitly out of scope, revisit only if requested)

- [ ] Global per-module kill-switches for Gallery/Reviews/Meetings — see Anti-Features;
      only build if a real "pause this entire pipeline" need emerges
- [ ] Granular per-capability permission builder (Wick-style) — only if the flat 3-tier
      model proves insufficient in practice
- [ ] Multi-guild support — out of scope; single Nocturna guild by design

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|----------------------|----------|
| Role→tier mapping + enforcement | HIGH | MEDIUM | P1 |
| Dashboard shell + sidebar | HIGH | LOW | P1 |
| Settings migration + readable names | MEDIUM | MEDIUM | P1 |
| Reminders CRUD + pause/resume | HIGH | MEDIUM | P1 |
| Gallery approval queue | HIGH | MEDIUM | P1 |
| Reviews approval queue | MEDIUM | MEDIUM | P1 |
| Jinxxy manual sync + status | MEDIUM | LOW–MEDIUM | P1 |
| Meetings browser + edit + re-publish | HIGH | HIGH | P1 (sequence last) |
| Editors section integration | MEDIUM | LOW–MEDIUM | P2 |
| Per-module status badges (non-functional) | LOW | LOW | P2 |
| Audit/activity log | MEDIUM | MEDIUM | P3 (deferred) |
| Granular permission builder | LOW | HIGH | P3 (deferred, avoid unless requested) |

**Priority key:**
- P1: Must have for this milestone (already in PROJECT.md Active scope)
- P2: Should have if time allows within this milestone
- P3: Explicitly deferred — future consideration only

## Competitor Feature Analysis

| Feature | MEE6 | Dyno | Carl-bot | Wick | Nocturna's Approach |
|---------|------|------|----------|------|----------------------|
| Module organization | Per-plugin page, big enable/disable toggle | Sidebar modules, toggles + text config | Sidebar modules, no prominent toggle emphasis | Modules + a setup wizard | Sidebar per module (sketch 001 variant A); toggle affordance only where a real on/off state exists (Reminders per-item, Jinxxy sync), status badge elsewhere |
| Access control | Discord "Manage Server" permission gates dashboard access; no custom tiers | Same — Discord permission-based, not a custom tier table | Discord role position + Manage Server permission | Custom Permits (v5): independent hierarchical permission system beyond Discord roles | Custom 3-tier model (owner/Manager/editor) with an editable role→tier mapping — closer to Wick's approach than to MEE6/Dyno/Carl-bot's Discord-permission-only model |
| Approval/queue workflows | Not a core pattern (mostly config, not moderation queues) | Ban/mute appeal queue: approve/reject/view-history per item | Reaction-role config (not really an approval queue) | Moderation-focused, log/action-heavy | Gallery/Reviews approval queues with explicit parity to existing ✅/🌙 Discord reactions — a closer domain match to Dyno's appeal queue than to MEE6/Carl-bot's pure config model |
| Manual "run now" actions | Limited — mostly config takes effect passively | Limited | Limited | N/A found | Jinxxy manual sync + last-status is a differentiator for Nocturna relative to the reference set (none surfaced dedicated "sync now" UI in research) |
| AI-generated content review | None | None | None | None | Meetings summary edit + re-publish has no direct competitor equivalent found — genuine differentiator, not a validated ecosystem pattern (LOW confidence there's prior art to compare against) |

## Sources

- [MEE6 Dashboard | MEE6 Wiki](https://wiki.mee6.xyz/en/features/dashboard) — page title only
  retrievable (client-rendered SPA); module-toggle claim corroborated via search snippets
  and general knowledge of MEE6's plugin-enable pattern (MEDIUM confidence)
- [Getting Started With MEE6 | MEE6 Support Portal](https://help.mee6.xyz/en/articles/605731-getting-started-with-mee6)
- [Dyno Docs — Modules](https://docs.dyno.gg/en/modules) — 403 on direct fetch; module/toggle
  pattern and appeal-queue behavior corroborated via search snippets (MEDIUM confidence)
- [Dyno Docs — Reminders](https://docs.dyno.gg/en/modules/reminders) — confirms Dyno's own
  reminders dashboard has limited CRUD (no view/remove of active reminders), a gap Nocturna's
  full CRUD explicitly improves on
- [Dyno Docs — Dashboard Settings](https://docs.dyno.gg/en/dashboard/settings)
- [Carl-bot — carl.gg/about](https://carl.gg/about) and community guides — permission model
  confirmed as Discord role-position + Manage Server permission, no custom tier table (MEDIUM
  confidence, WebSearch-sourced)
- [Wick Docs — FAQ / Setup / v5.0.0 changelog](https://docs.wickbot.com/) — Custom Permits
  (independent hierarchical permission system) confirmed via changelog and FAQ snippets
  (MEDIUM confidence)
- [fuma-nama/discord-bot-dashboard (GitHub)](https://github.com/fuma-nama/discord-bot-dashboard) —
  concrete open-source template showing Features/Actions tab split, toggle-per-feature, and
  publish/delete task pattern (HIGH confidence — source is the actual repo content, not a
  search snippet)
- General SaaS integration UX pattern (manual sync + last-run status + spinner + inline error)
  drawn from well-established conventions (Stripe, GitHub, Zapier-class "sync now" UI) rather
  than a Discord-bot-specific source — flagged LOW confidence as a *Discord dashboard* pattern
  specifically, though HIGH confidence as a general admin-UI pattern
- `.planning/PROJECT.md` — milestone scope, Active/Out-of-Scope requirements, Key Decisions
- `.planning/sketches/001-dashboard-shell/README.md` — visual contract (variant A winner:
  MEE6-pure module pages with big toggle, spacious cards)

---
*Feature research for: Nocturna Bot v2.0 Staff Dashboard*
*Researched: 2026-07-21*
