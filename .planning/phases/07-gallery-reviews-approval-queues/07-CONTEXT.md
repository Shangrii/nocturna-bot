# Phase 7: Gallery + Reviews Approval Queues - Context

**Gathered:** 2026-07-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring the **gallery photo-approval** and **client-reviews-approval** flows —
today driven **only** by ✅/🌙 Discord reactions in `cogs/gallery.py` and
`cogs/reviews.py` — into the **staff dashboard** as **Manager-operated queues**
with **full parity to the reaction flow** and **no double-publish**
(GAL-01, GAL-02, GAL-03, REV-01, REV-02).

**The load-bearing constraint (locked, shapes every decision):** the FastAPI app
holds **no Discord and no GitHub credentials**. It therefore cannot read the
queue (pending state lives only in Discord) nor publish (the cross-repo commit
uses the bot's `GITHUB_PAT`). Phase 7 is a **read cache + a write queue** on top
of the two already-built cogs:

- **Read side (GAL-01, queue visibility):** the bot **pushes** a snapshot of
  pending + published items into shared sqlite (the Phase-4 `discord_names` /
  `set_heartbeat` push idiom); the panel reads that cache.
- **Write side (approve/remove):** the panel **enqueues** a typed action on the
  **Phase-5 `action_queue`**; the bot's `ActionQueueCog` dispatches it by
  **re-invoking the existing cog publish/unpublish logic** — so the shipped
  🟢-marker idempotency delivers GAL-02's no-double-publish for free.

**Not in this phase:** the reaction flow itself (already shipped), editor-credit
/ NSFW controls (Discord-only, deferred — D-12), and any change to the review
anonymity contract (D-13).

**Hard dependency:** Phase 5 (`action_queue` + sqlite hardening) and Phase 4
(`discord_names` push-cache pattern) must be in place — this phase is their
first real consumer.

</domain>

<decisions>
## Implementation Decisions

### Queue visibility — how the panel SEES a Discord-only queue (GAL-01 / REV-01 read side)
- **D-01: Bot→app push cache (the only viable route).** A bot cog pushes a
  snapshot of the pending **and** published gallery/reviews items into a
  shared-sqlite cache, following the Phase-4 `discord_names` /
  `jinxxy_sync_status` / `bot_heartbeat` push idiom. The app **reads** this
  cache and never touches Discord or GitHub (locked no-credentials-in-app).
  **Rejected:** the app reading `gallery.json`/`reviews.json` directly — that
  surfaces only *published* items; *pending* items exist solely as Discord
  messages carrying the bot's ✅ prompt without a 🟢 marker.
- **D-02: Near-live cadence + Alpine auto-refresh.** The snapshot is re-pushed on
  a periodic loop (~30–60s, heartbeat-style — planner picks the exact interval)
  and the panel short-polls (Alpine, already shipped) so newly-posted pending
  items and status flips appear **without a reload**. Free side effect: re-pushing
  refreshes the Discord CDN **signed thumbnail URLs** (which expire ~24h), so a
  photo sitting in the queue never shows a dead thumbnail.
- **D-03: Gallery row fields — full judging context.** Each pending/published
  gallery card carries: **thumbnail**, **poster** (staff editor display name),
  **caption** text, **posted-at** (relative), and an **open-in-Discord** message
  link. Enough to approve/remove confidently without opening Discord.
- **D-04: Review row fields.** Each review card carries: **author** (display name
  for a named review / the fixed **"Anónimo"** label for an anonymous one),
  the **full review text**, the **date**, and a **named/anonymous badge**.
  Anonymity is preserved end-to-end (see D-13).

### Layout & preview (UI — sidebar sections `Gallery` and `Reviews`)
- **D-05: Gallery = responsive thumbnail grid; Reviews = text cards.** Gallery
  photos are a visual medium → a responsive grid of cards (image + fields +
  per-card actions). Reviews reuse the card pattern minus the image (text +
  author/date + actions). **Rejected:** a dense list/table for gallery.
- **D-06: Pending | Published tabs** on each section. **Pending** is the primary
  Manager job and is the default tab; **Published** exists for removal
  (GAL-03/REV-02).
- **D-07: Click-to-expand lightbox.** Clicking a gallery thumbnail opens the
  full-size image so a Manager can inspect detail/quality before approving or
  removing.

### Action mechanics — approve/remove parity (GAL-02/03, REV-01/02 write side)
- **D-08: Ride the Phase-5 `action_queue`; reuse the cog logic — do NOT
  reimplement.** Manager-gated POST routes `enqueue` typed actions (e.g.
  `gallery_publish` / `gallery_remove` / `review_publish` / `review_remove`,
  exact names = planner's call) with the Discord message id in the payload. The
  bot's `ActionQueueCog._dispatch` grows new `kind` handlers (the file already
  says *"Phases 6-9 add kinds here"*) that **re-fetch the message and call the
  existing** `GalleryCog._publish`/`_unpublish` and `ReviewsCog._publish`/
  `_unpublish`. The shipped **🟢-marker idempotency IS the GAL-02
  no-double-publish guarantee** and satisfies the Phase-5 D-08 invariant ("the
  module owns idempotency").
- **D-09: Inline per-item status.** Each acted item shows **Working… → ✓ / ✗**
  (Phase-5 D-01/D-05) and the durable-queue **"bot offline — will run on
  reconnect"** state (Phase-5 D-07) — no lost clicks.
- **D-10: Remove = confirm dialog; Approve = one-click.** Remove opens a short
  confirm ("¿Quitar esta foto/reseña de la web?") because it drops live website
  content (reversible after: a removed item returns to Pending and is
  re-approvable). Approve is a single click — the primary job, easily undone by
  Remove. (**Rejected** for Remove: no-confirm; undo-toast.)
- **D-11: A moot/concurrent action resolves as a benign "already done" success,
  never a red error.** When a staff ✅/🌙 reaction (or a second Manager) already
  reached the target state, the bot's 🟢-marker check makes the dispatch a no-op.
  The panel must reflect this as a **quiet success** ("ya publicada" / "ya
  quitada"), because the desired end-state was reached — this **is** true
  reaction-flow parity. **Implication (for planner):** the dispatch handler /
  status mapping must distinguish *"no-op because already in the target state"*
  (→ success) from a *genuine failure* (→ ✗ + Retry, Phase-5 D-02).

### Scope & anonymity
- **D-12: Panel is approve/remove parity ONLY.** Editor-credit
  (`/galeria creditar` — attach an editor slug so a photo appears on that
  editor's profile) and the NSFW flag stay on the Discord command → **Deferred**.
  Holds the phase to the roadmap boundary.
- **D-13: True end-to-end review anonymity is LOCKED (unchanged).** The bot's
  push cache carries only **"Anónimo" + text + date** for an anonymous review;
  the submitter's name/id is **never** written to shared sqlite. **No tier
  (owner included) can de-anonymize**, and the collection-panel promise
  *"Reseña anónima — se publica sin ningún dato tuyo"* stands unchanged. The cog
  already deliberately discards the identity (`ReviewModal` *"ANONYMITY
  CONTRACT: never read the submitter's identity"*, T-07-02) — Phase 7 preserves
  that, adding nothing that captures it. (**Considered and rejected:**
  owner-only reveal — it would require storing the identity the cog throws away
  and would break the submitter-facing promise.)

### Claude's Discretion
- Exact push-cache table schema/column names and the precise refresh interval
  within the "~30–60s / feels near-live" envelope (D-01/D-02); one shared cache
  table vs. one per module.
- Exact `action_queue` `kind` string names and payload shape (D-08).
- The precise Alpine short-poll interval (reuse the Phase-5 value).
- Whether the **published** list is sourced from the same push cache or read from
  the live `gallery.json` / `reviews.json` (both viable for *published*; only the
  push cache can carry *pending*).
- Lightbox implementation (native/Alpine) and grid breakpoints (D-05/D-07).
- All bilingual **ES/EN** copy: confirm dialogs, empty states, the
  named/anonymous badge, and the "already done" / "bot offline" messages (house
  style, Spanish-first).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **GAL-01** (Manager sees the pending-photos
  queue), **GAL-02** (approve → publishes with ✅-flow parity, no double-publish
  on a concurrent reaction), **GAL-03** (remove a published photo, 🌙 parity),
  **REV-01** (approve a pending review → `reviews.json`), **REV-02** (remove a
  published review).
- `.planning/ROADMAP.md` — Phase 7 goal + the five success criteria; note
  Phase 7 **depends on** Phase 6 (and transitively Phases 4 & 5).

### Existing implementation (this phase wraps these — MUST read)
- `cogs/gallery.py` — the full gallery reaction engine: `_publish` / `_unpublish`
  (the exact logic D-08's queue handlers re-invoke), the **🟢-marker
  idempotency** (`_is_published`, the `r.me` 🟢 check in `_publish` — the GAL-02
  guarantee), `_image_attachments`/`_build_filename` (published photo identity),
  the ⚠️ retry UX, and the `on_raw_message_delete` / startup-backfill reconcile.
  Also the Discord-only `/galeria creditar` + NSFW flow deferred by D-12.
- `cogs/reviews.py` — the reviews analog: `_publish`/`_unpublish`, 🟢-marker
  idempotency keyed by message id, the **anonymity contract** (`ReviewModal`,
  `_build_review_embed`, `REVIEW_ANON_LABEL = "Anónimo"`, `_review_author_and_text`
  — the seam that maps anonymous → `author: null`; D-13 preserves this), and the
  guided collection panel (`panel_resenas`, out of scope here).
- `core/github_publish.py` — the cross-repo transport the bot (never the app)
  calls: `publish_message`/`remove_message`/`set_gallery_editor` (gallery),
  `publish_review`/`remove_review` (reviews), `_fetch_gallery`/`_fetch_json`
  (published-list reads if D-01's "published from json" discretion is taken).

### Infrastructure this phase consumes (MUST read)
- `core/action_queue.py` — `enqueue(kind, payload, requested_by)` /
  `claim_next()` / `complete(id, result)` / `fail(id, error)` / `retry(...)` /
  `get_status(id)` / `recover_stale_claims()`. D-08's routes call `enqueue`; the
  worker calls the rest.
- `cogs/action_queue_worker.py` — `ActionQueueCog._dispatch` (the `{"noop": …}`
  table Phase 7 extends with the four gallery/reviews kinds), the 1.5s dispatch
  loop, and the claim → dispatch → complete/fail lifecycle D-11 hooks into.
- `core/db.py` — the push-cache idiom D-01 copies: `set_heartbeat`/`get_heartbeat`,
  `init_discord_names`/`replace_discord_names`/`get_discord_names` (bot→app
  snapshot-replace pattern), `jinxxy_sync_status` single-row upsert,
  `log_activity` (D-09 optional Overview line, keep-last-N purge), and
  `init_action_queue`. New `init_*` + replace/read helpers for the gallery/reviews
  cache follow this idiom (fresh-conn-per-call, parameterized SQL, allowlists).

### Milestone research (directly blueprints this phase — MUST read)
- `.planning/research/ARCHITECTURE.md` — the `action_queue` design and the
  bot↔app shared-sqlite-only channel discipline the D-01 push cache and D-08
  write queue both obey.
- `.planning/research/PITFALLS.md` — Pitfall 3 (sqlite writer/writer contention,
  the `busy_timeout` + retry hardening D-08's enqueue path inherits) and the
  per-row-try/except reconcile hazards the cogs already handle.
- `.planning/research/SUMMARY.md` — `require_tier`/`require_manager` gating for
  the enqueue routes; the short-poll inline-status technique (D-09).

### Prior phase context (patterns this rides on)
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-CONTEXT.md`
  — the `action_queue` contract, **D-08 invariant** (the module owns
  idempotency → the 🟢 marker here), inline-status + bot-offline states (D-09),
  Retry-on-failure (D-11).
- `.planning/phases/04-settings-migration-name-resolution/04-CONTEXT.md` — the
  bot→app `discord_names` push cache, the model D-01 replicates for the
  pending-queue snapshot (and reused to resolve the gallery poster name, D-03).
- `.planning/phases/03-dashboard-shell-tiered-access/03-CONTEXT.md` — the
  `require_manager` tier gate (queues are Manager-gated), POST-only bilingual
  mutations, Alpine table/grid + modal conventions, and `dashboard.css`
  per-module accents (`--accent-gallery`, `--accent-reviews`).

### Prior design / spec
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — the
  validate-then-write / inline-error / no-secrets panel invariants the dashboard
  preserves.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`cogs/gallery.py` / `cogs/reviews.py` `_publish` & `_unpublish`** — the exact
  approve/remove business logic; D-08's queue handlers re-fetch the message and
  call these, inheriting the 🟢-marker idempotency, ⚠️ retry UX, and activity_log
  hooks unchanged. **Do not duplicate this logic in the app.**
- **🟢-marker idempotency** (`_is_published`, the `r.me` 🟢 checks) — already the
  GAL-02 no-double-publish guarantee; nothing new is needed to satisfy it.
- **`core/action_queue.py` + `cogs/action_queue_worker.py`** — the app→bot write
  channel; extend `_dispatch` with the four gallery/reviews kinds (D-08).
- **`core/db.py` push-cache helpers** (`replace_discord_names` snapshot-replace,
  `set_heartbeat` single-row upsert, `jinxxy_sync_status`) — templates for the new
  pending/published snapshot cache (D-01).
- **Phase-4 `get_discord_names`** — resolves the gallery poster's readable name
  for D-03 (and any channel/role labels needed).
- **Phase-3 dashboard shell** — `/gallery` and `/reviews` routes + module stubs
  (to be replaced with the real grid/tabs), sidebar entries, `require_manager`
  gate, `--accent-gallery`/`--accent-reviews`, Alpine (`app/static/alpine.min.js`).

### Established Patterns
- **Shared sqlite (`DB_PATH`, WAL + `busy_timeout`) is the ONLY bot↔app channel.**
  D-01 cache = bot→app (reverse); D-08 queue = app→bot (forward). No IPC/HTTP; the
  app holds **no Discord/GitHub credentials** (locked).
- **DB idiom:** fresh-connection-per-call; `init_*()` from the owning cog's
  `__init__` (dual-process defensive init so the app never 500s on a missing
  table); parameterized SQL only; explicit column allowlists.
- **Manager-gated, POST-only, bilingual (ES/EN), Spanish-first** for every panel
  mutation and user-facing string.
- **At-least-once queue + module-owned idempotency** (Phase-5 D-08) — honored here
  by the 🟢 marker; the queue must never cause a double-publish.

### Integration Points
- **New (bot side):** a push-cache cog (or extend an existing one) that snapshots
  pending+published gallery/reviews items into shared sqlite on a ~30–60s loop
  (D-01/D-02); new `core/db.py` `init_*`/replace/read helpers for that cache; four
  new `kind` handlers in `ActionQueueCog._dispatch` wrapping the existing
  cog `_publish`/`_unpublish` (D-08), mapping "already in target state" → success
  (D-11).
- **New (app side):** `require_manager`-gated `/gallery` + `/reviews` section
  routes reading the cache; Manager-gated POST enqueue routes (approve/remove);
  a per-action status-read endpoint the item short-polls (D-09); the thumbnail-grid
  + Pending|Published tabs + lightbox templates and `dashboard.css` blocks
  (D-05/D-06/D-07); a Remove confirm dialog (D-10).
- **Unchanged:** the reaction flow, the cross-repo transport, and the review
  anonymity path — Phase 7 adds surfaces around them, never rewrites them.

</code_context>

<specifics>
## Specific Ideas

- **Remove confirm copy:** "¿Quitar esta foto de la web?" / "¿Quitar esta reseña
  de la web?" (bilingual ES/EN).
- **Moot-action success copy (D-11):** "Ya estaba publicada." / "Ya estaba
  quitada." (a calm success, not an error).
- **Bot-offline state (D-09):** reuse Phase-5's "bot offline — will run on
  reconnect" wording.
- **Anonymous badge label:** the fixed **"Anónimo"** (never the submitter's name),
  matching `REVIEW_ANON_LABEL` in `cogs/reviews.py`.
- **Tabs:** Pending default, Published secondary — pending is the job.

</specifics>

<deferred>
## Deferred Ideas

- **Editor-credit + NSFW flag in the panel** (D-12) — attach an editor slug /
  mark NSFW from the gallery card. Considered, deferred to a later phase to keep
  Phase 7 at approve/remove parity; stays available via `/galeria creditar`.
- **Owner-only de-anonymization of anonymous reviews** (D-13) — considered and
  **rejected**, not merely deferred: it breaks the end-to-end anonymity guarantee
  and the "sin ningún dato tuyo" submitter promise. Revisit only with an explicit,
  disclosed consent-copy change.
- **Reviews collection panel management** (`panel_resenas`) from the dashboard —
  out of scope; it's a client-facing Discord affordance.

</deferred>

---

*Phase: 7-Gallery + Reviews Approval Queues*
*Context gathered: 2026-07-23*
