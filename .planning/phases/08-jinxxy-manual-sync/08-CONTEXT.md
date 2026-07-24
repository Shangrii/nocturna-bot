# Phase 8: Jinxxy Manual Sync - Context

**Gathered:** 2026-07-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring the store sync's **manual trigger** — today reachable only through the
staff-gated `/tienda sync` slash command in Discord — into the **dashboard's
Jinxxy Store section** as a Manager-operated button, with **last-run status
visible** and a **proven overlap guard** so a manual trigger can never
double-sync against the scheduled `_poll` loop (`JINXXY_POLL_HOURS`, 6–12h band).
That is JINX-01, and the roadmap's two success criteria are exactly: (1) a
Manager can trigger a sync and see the last run's status/result, disabled/spinner
while in-flight; (2) a manual trigger fired while the poll is running does not
double-sync, **proven under test**.

**The load-bearing constraint (locked, inherited):** the FastAPI app holds **no
Jinxxy, GitHub, or Discord credentials**. It therefore cannot sync. Phase 8 is
**one new `action_queue` kind + a status/mirror read surface** on top of the
already-shipped `JinxxyCog`:

- **Write side:** a Manager-gated POST route `enqueue`s a `jinxxy_sync` action;
  `ActionQueueCog._dispatch` grows one handler that calls the bot's existing
  `JinxxyCog._run_sync` (then `_announce`) — the sync logic is **never**
  reimplemented in the app.
- **Read side:** the panel reads `jinxxy_sync_status` (already written by
  `_record_sync_status` on every run, from every trigger) plus `store_snapshot`
  (the durable local catalog the `/tienda` autocomplete already reads). No new
  push cache is needed — this is the cheapest module in the milestone on the read
  side.
- **Guard side:** the phase's real engineering content. Phase-5 D-08 makes
  idempotency the module's responsibility; here that responsibility **is** the
  overlap guard.

**Not in this phase:** the `/tienda sync`, `/tienda medios`, and `/tienda editar`
Discord commands (already shipped, unchanged); any editing of store data from the
panel (D-17); changing the poll cadence or the merge/reconcile logic in
`core/store_sync.py`.

**Hard dependency:** Phase 5 (`action_queue` + sqlite hardening) and Phase 3
(`require_manager` tier gate, `jinxxy_sync_status`, `activity_log`,
`bot_heartbeat`). Phase 7 is the pattern precedent for a queue-riding module.

</domain>

<decisions>
## Implementation Decisions

### Overlap guard — the phase's core guarantee (roadmap criterion #2)

- **D-01: A collision resolves as a benign "already syncing" SUCCESS, never an
  error.** When the dispatch finds a sync in flight it returns **immediately**
  with a quiet success — *"Ya se está sincronizando · Sync already running"* —
  rendered as a calm ✓-class state, **not** a red ✗. Directly mirrors Phase-7
  D-11 ("a moot action is a success — the desired end state is being reached").
  **Critical mechanical reason to return instead of wait:** Phase-5 D-10
  dispatches **one action per tick**, so a handler that blocked on the lock for
  the duration of a multi-minute sync would park the single dispatch slot and
  stall every other queued action (gallery approve, reviews remove) behind it.
  **Rejected:** coalesce-and-run-after; hold-the-action-until-free.
- **D-02: `asyncio.Lock` (or busy flag) in `JinxxyCog` is the AUTHORITATIVE
  guard; a `running` state in `jinxxy_sync_status` is the panel-visible MIRROR.**
  Both `_poll` and the new queue handler funnel through the single `_run_sync`
  entry point **in the same bot process**, so a non-blocking `locked()` check is
  correct by construction — no DB row read/write is a real mutex. The mirror
  exists solely because the app has no other way to see bot-process state.
  **Binding:** the mirror is set/cleared around the *whole* `_run_sync` body (the
  same span the lock covers) so the two can never disagree while the bot is up.
  **Rejected:** lock-only (forecloses D-05); DB-flag-only (racy, and a crash
  leaves it stuck).
- **D-03: The reverse collision — the poll's tick firing while a manual sync
  runs — skips the tick and logs only.** No sync, no announce; the next cadence
  (6–12h) runs normally. The manual sync just reconciled the store, so a poll
  seconds later has nothing to add. Symmetric back-off (whoever holds the lock
  wins, the other backs off) and consistent with the Jinxxy cog's own locked
  rules — its D-05 ("errors and ops never reach Discord") and D-06 ("silent on no
  change"), both documented in the `cogs/jinxxy.py` module docstring.
  **Rejected:** poll waits then re-runs (redundant full enumeration); poll
  pre-empts the manual sync (a Manager's explicit click must not lose to a timer).
- **D-04: Duplicate clicks dedupe AT ENQUEUE.** If a `jinxxy_sync` action is
  already `pending` or `claimed`, the POST route returns **that existing action's
  id** rather than inserting a second row; the second clicker simply short-polls
  the in-flight run and sees the same result. **This closes a hole D-01 does not
  cover:** a queued duplicate dispatches *after* the first releases the lock, not
  during it, so the overlap guard would never see it and a full redundant
  enumeration (N+2 Jinxxy API calls + a GitHub read) would run. **Rejected:** a
  time-based cooldown on top (a second rule and a second piece of state for a
  case dedupe already handles); no guard at all.

### In-flight state (roadmap criterion #1 — "disabled/spinner while in-flight")

- **D-05: The busy state reflects ANY sync, from ANY entry point.** Because the
  mirror is written around `_run_sync` (D-02), it covers the scheduled poll,
  `/tienda sync` from Discord, and the panel click for free. The button is
  disabled with *"Sincronizando… · Syncing…"* for **every** Manager on the page
  and **survives a reload** — nobody clicks into a guaranteed "already syncing"
  reply. **Rejected:** deriving busy from the `action_queue` row alone (would show
  in-flight only for panel-triggered syncs).
- **D-06: Stuck-mirror recovery = clear-on-startup + heartbeat staleness.**
  `JinxxyCog.__init__` clears the mirror on every boot (the in-process lock is
  gone at startup, so `running` is definitionally false) — the same defensive-init
  idiom as the adjacent `db.init_store_state()`. **Plus:** the app treats the
  mirror as void when `bot_heartbeat` is stale (Phase-5 D-07), so a bot that is
  *currently down* never shows a phantom sync in progress. Two cheap rules, **no
  sweeper and no timeout constant to guess**. **Rejected:** a staleness timeout on
  `started_at` (N is a guess — too short re-enables mid-sync on a large catalog,
  too long leaves the button dead); startup-clear alone (phantom "in progress" for
  the whole outage window).
- **D-07: While running, render spinner + elapsed + trigger source.**
  *"Sincronizando… 1:20"* plus a label for what started it (*programada · desde el
  panel · desde Discord*). Both are derivable from the mirror row (`started_at` +
  a source column) — **no new bot→app machinery**. Answers the only two questions
  a waiting Manager has: is it stuck, and did I cause this. **Rejected:** elapsed
  without source (an unexplained sync reads as the panel acting on its own); a
  plain indeterminate spinner (can't distinguish slow from hung on a multi-minute
  run).
- **D-08: A click while the bot is offline stays DURABLE — Phase-5 D-07 is
  unchanged.** The action stays pending and dispatches on reconnect. Note the
  composition, which is deliberate and must not be "fixed": `JinxxyCog._poll`'s
  immediate first tick **is** the startup reconcile (CR-01, no separate `on_ready`
  path), so on reconnect the poll takes the lock first and the queued action
  dispatches ~1.5s later **into a held lock**, resolving as D-01's benign "ya se
  está sincronizando". The Manager's click is honored (the store *is* reconciled,
  by the startup tick) and **no redundant second enumeration runs** — the two
  guards compose with nothing new to build. **Rejected:** expiring a stale queued
  sync (breaks Phase-5's "the queue never silently drops an action" invariant for
  one kind); disabling the button while the bot is down (discards the "no lost
  clicks" property Phase 5 deliberately built).

### Result & error feedback

- **D-09: Show the added/updated/removed counts, AND persist them.** The panel
  renders the `/tienda sync` copy — *"3 nuevos · 2 actualizados · 1 quitado"* or
  *"Sin cambios."* — which is available for free on a panel-triggered sync because
  `_run_sync`'s return dict becomes the handler's return value, which
  `action_queue.complete(id, result)` stores and `/api/actions/{id}` serves.
  **Additionally widen `jinxxy_sync_status` to store the same counts**, so the
  "Última sync" card is equally informative after a poll- or Discord-triggered
  run, not just one the panel started. (Today the row holds only
  `last_run_utc / ok / product_count / error`.) **Rejected:** counts from the
  action row only (last-sync card stays thin for the other two triggers); bare ✓ +
  product_count (hides the one thing the Manager clicked to learn).
- **D-10: A failure shows a bilingual CATEGORY derived from the exception TYPE —
  never a raw third-party string.** `JinxxyAPIError` → *"No pude contactar con
  Jinxxy · Couldn't reach Jinxxy"*; `github_publish.GitHubPublishError` → *"No
  pude publicar en la web · Couldn't commit to the site"*; anything else → *"Falló
  la sincronización · Sync failed"* — each with *"revisa los logs"*. `str(exc)`
  from these clients can carry API URLs and status codes, so nothing raw is
  rendered: this honors the cog's locked *"errors go to logs ONLY"* rule and the
  project's no-secrets invariant, while still being actionable (a Manager can tell
  a Jinxxy outage from a GitHub failure without shell access — the whole point of
  the dashboard). **Note:** this is a deliberate divergence from Phase-5 D-02's
  "short raw reason", justified by the exception text originating outside this
  codebase. **Rejected:** truncated `str(exc)`; a single generic message.
- **D-11: A panel-triggered sync ANNOUNCES, under the same rules.** The handler
  calls `_run_sync` then `_announce(result)`, exactly like `/tienda sync`. True
  trigger parity — the public store-news embed depends on the **store changing**,
  not on which surface asked. `_announce` is already silent on no-change (D-06 of
  the original Jinxxy phase), and D-01 + D-04 make repeat clicks incapable of
  producing repeat posts. Announce-send failures remain cosmetic (WR-09: logged,
  swallowed) and must **not** fail the queued action.
- **D-12: Attribute the trigger in `activity_log` and the status card.** Instead
  of the current source-agnostic *"Sync de Jinxxy ejecutado / Jinxxy sync ran"*,
  the line names the source — e.g. *"Sync de Jinxxy desde el panel (Nombre) ·
  Jinxxy sync from the panel (Name)"* vs *"programada · scheduled"*. Mostly
  wiring: `requested_by` is already on the queue row and the source column already
  exists for D-07's in-flight label. Gives an ops audit trail for a shared button
  that costs real third-party API calls.

### The `/jinxxy` section page (currently a `module_stub`)

- **D-13: The section = last-sync card + Sync button + a READ-ONLY product
  table.** The catalog comes from `store_snapshot`, the durable local sqlite table
  the `/tienda` autocomplete already reads — **no credentials, no new cache, no
  new bot→app push**. This is read-only *display* of data the bot already owns, so
  it adds no capability and stays inside the phase boundary. It gives the section
  substance and lets a Manager confirm the sync did what the counts claim.
  **Known limitation to design around:** `store_snapshot` holds only the
  **sync-owned** fields (`checkout_url, jinxxy_id, name, price, category, nsfw,
  date`). Staff-supplied **images, description, and editor** live only in the
  website's `store.json` and are **not** available to the panel — the table must
  not imply otherwise. **Rejected:** a totals-only figure; button + status alone.
- **D-14: The list is a compact table**, not a card grid: name · price · category ·
  NSFW badge · date, with the name linking out to its `checkoutUrl`. Reuses the
  shipped Reminders table styling and the `--accent-jinxxy` (`#34d399`) accent,
  scans well at catalog size, and needs no modal since nothing is editable. A card
  grid was rejected specifically because the snapshot carries **no image** — they
  would be picture-less cards. **Rejected:** card grid; collapsed-by-default.
- **D-15: An explicit never-synced empty state.** Before any sync has ever run
  (`jinxxy_sync_status` has no row, `store_snapshot` is empty) the card reads
  *"Nunca se ha sincronizado · Never synced"* — **not** a dash — the table area
  reads *"Aún no hay productos sincronizados · No synced products yet"*, and the
  Sync button stays enabled and prominent. "Never ran" and "ran and found nothing"
  are different situations and must look different. **Rejected:** reusing
  Overview's `—` placeholder (reads as "unknown", not "press the button");
  hiding the table until first sync (page changes shape; empty-after-sync becomes
  indistinguishable from never-synced).
- **D-16: The Sync button is ONE-CLICK — no confirm dialog.** A sync only makes
  the store match Jinxxy — the identical reconcile the poll runs unattended every
  6–12h — so a click cannot reach a state the bot would not have reached anyway.
  Matches `/tienda sync` (no confirm there either) and Phase-7 D-10's house rule
  (Remove confirms because it drops live content on a human's initiative; Approve
  and, here, Sync are one-click). The in-flight disable (D-05) and enqueue-dedupe
  (D-04) already absorb accidental double-clicks. **Rejected:** a confirm dialog —
  it would gate an action the scheduler performs unattended and add friction to
  the one thing this section exists to do.
- **D-17: The panel is trigger + status + read-only view ONLY.** Editing store
  metadata stays on the Discord commands (`/tienda medios` for images and
  bilingual descriptions, `/tienda editar` for the credited editor) → **Deferred**.
  Holds the phase to the roadmap boundary.

### Claude's Discretion

Delegated to research/planning, constrained by the decisions above:

- The exact `action_queue` `kind` string (`jinxxy_sync` is the obvious name) and
  its payload shape — the sync takes no parameters, so the payload may be empty
  or carry only the trigger source.
- Exact column names/types added to `jinxxy_sync_status` for the D-02 mirror
  (`running`, `started_at`), the D-07 source label, and the D-09 counts — plus
  whether the source label is stored as an enum-ish string or an id.
- **How the widening is applied** (see `code_context` — the table already exists
  in deployed DBs, so `CREATE TABLE IF NOT EXISTS` alone will NOT add columns).
- The precise dedupe query for D-04 (`SELECT … WHERE kind='jinxxy_sync' AND
  status IN ('pending','claimed')`) and how the route returns the existing id.
- The Alpine short-poll interval for the sync item and for the mirror-backed busy
  state (reuse the Phase-5/7 values); the elapsed-time formatting for D-07.
- Whether the `running` state is a dedicated column or an inference from a
  `started_at`/`finished_at` pair.
- Whether the Overview "Última sync" tile also gains the D-09 counts (optional —
  the Jinxxy section is the required surface).
- Exact table column set, sort order (by name? by date?), and any client-side
  filter for the D-14 product table.
- All bilingual **ES/EN** copy, Spanish-first house style: the "already syncing"
  success, the three D-10 error categories, the D-15 empty states, the D-07
  in-flight labels, and the D-12 activity line.
- The design of the **automated overlap test** (roadmap criterion #2 requires the
  guard be *proven under test*): at minimum it must show that a `jinxxy_sync`
  dispatch arriving while `_run_sync` holds the lock produces **exactly one**
  sync — one `sync_store` call, one announce — and resolves as a success, not a
  failure. The Phase-5 concurrency-test harness (`tests/test_action_queue_
  concurrency.py`) is the closest precedent.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **JINX-01**: "A Manager can trigger a manual sync
  and see the status/result of the last sync (with an overlap guard against the
  periodic poll)." Also the Out-of-Scope table (no websockets — polling is
  sufficient; no new IPC).
- `.planning/ROADMAP.md` — Phase 8 goal ("A Manager can force a store sync on
  demand without ever racing the scheduled poll") and its two success criteria,
  including **"overlap guard proven under test"**. Phase 8 depends on Phase 7.

### Existing implementation this phase wraps (MUST read — do NOT reimplement)
- `cogs/jinxxy.py` — the whole store-sync controller. Specifically:
  `_run_sync` (the single orchestration every trigger funnels through — the
  natural home of the D-02 lock and mirror), its **ordering-is-removal-safety**
  contract (T-09-15: enumeration raises before any commit/snapshot delete), the
  `@tasks.loop(hours=config.JINXXY_POLL_HOURS)` `_poll` whose **immediate first
  tick IS the startup reconcile** (CR-01 — load-bearing for D-08) with its
  `_on_poll_error` 15-min cooldown restart (WR-02), `_record_sync_status` (the
  D-09/D-12 instrumentation point), `/tienda sync` (the manual trigger this phase
  mirrors, including its counts copy and its D-05 errors-to-logs-only rule),
  `_announce` / `_build_announce_embed` (D-11, silent on no change, send failures
  swallowed per WR-09), and the `_is_staff` gate.
- `core/store_sync.py` — the pure merge: `map_product`, `three_way_merge`,
  `reconcile_store` (returns `added`/`updated`/`removed`/`changed`/`products` —
  the source of D-09's counts), `is_https_url`. **Unchanged by this phase.**
- `core/jinxxy_api.py` — `get_me` / `list_all_products` / `get_product` and
  `JinxxyAPIError` (the D-10 error category; it RAISES rather than returning `[]`
  on an outage — T-09-15).
- `core/github_publish.py` — `sync_store`, `_fetch_store`, and
  `GitHubPublishError` (the second D-10 error category). Bot-side only; the app
  never calls it.

### Infrastructure this phase consumes (MUST read)
- `core/action_queue.py` — `enqueue(kind, payload, requested_by) -> int`,
  `claim_next()`, `complete(id, result)`, `fail(id, error)`, `retry(...)`,
  `get_status(id)`, `recover_stale_claims()`. The D-04 dedupe reads this table
  before enqueuing; `complete(id, result)` is what carries D-09's counts to the
  panel.
- `cogs/action_queue_worker.py` — `ActionQueueCog._dispatch` (the kind→handler
  table already holding `noop` + the four Phase-7 gallery/reviews kinds; Phase 8
  adds exactly one entry), the **1.5s** `_tick` loop, and the
  claim → dispatch → complete/fail lifecycle whose one-action-per-tick
  serialization is the mechanical reason behind D-01.
- `core/db.py` — `init_jinxxy_sync_status` / `set_jinxxy_sync_status` /
  `get_jinxxy_sync_status` (the single-row table this phase widens — its own
  docstring already says *"Phase 8's manual-sync status display reuses this exact
  record"*); `init_store_state` / `get_store_snapshot` / `upsert_store_snapshot`
  (the D-13 read source); `log_activity` (D-12, keep-last-500 purge-on-write);
  `set_heartbeat` / `get_heartbeat` (D-06 staleness); `_get_conn` (WAL +
  `busy_timeout`); and the **`ALTER TABLE … ADD COLUMN` in try/except
  `sqlite3.OperationalError`** idiom used for `forum_posts` and `reminders` — the
  template for widening `jinxxy_sync_status`.
- `app/main.py` — `/jinxxy` (currently `_module_stub_page`, to be replaced),
  `POST /api/actions` + `GET /api/actions/{id}` + `POST /api/actions/{id}/retry`
  (the shipped Manager-gated enqueue/status/retry endpoints), `require_manager`,
  `_build_overview_status` / `_read_overview_status` (already reads
  `jinxxy_sync_status` for the Overview tile), `_dashboard_asset_v`.
- `app/templates/_sidebar.html` — the shipped `jinxxy` entry
  (`route: /jinxxy`, `tier: manager`, `accent: var(--accent-jinxxy)`).
- `app/static/dashboard.css` — `--accent-jinxxy: #34d399` and the existing table /
  card / stat-tile blocks D-14 reuses.
- `app/templates/reminders.html` — the shipped table convention D-14 follows.
- `app/templates/overview.html` — the existing "Última sync Jinxxy" stat tile
  (`syncDetail()`), for consistency of wording with the new status card.

### Prior phase context (patterns this rides on)
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-CONTEXT.md`
  — the `action_queue` contract; **D-08 invariant** (at-least-once delivery, the
  module owns idempotency — here that IS the overlap guard); D-10 serialized
  one-action-per-tick dispatch (the reason for D-01); D-01/D-05 inline status +
  short-poll; D-07 bot-offline durable state (the basis of D-08 here); D-02
  Retry-on-failure.
- `.planning/phases/07-gallery-reviews-approval-queues/07-CONTEXT.md` — the
  precedent for a queue-riding module: D-08 (re-invoke existing cog logic, never
  reimplement), **D-11 (a moot/concurrent action is a benign success, not a red
  error — directly reused as D-01 here)**, D-09 inline status, D-10 the
  confirm-only-for-Remove house rule behind D-16.
- `.planning/phases/03-dashboard-shell-tiered-access/03-CONTEXT.md` — the
  `require_manager` tier gate, POST-only bilingual mutations, the
  `jinxxy_sync_status` single-row upsert pattern, `activity_log`, `bot_heartbeat`,
  and the per-module accent convention.

### Milestone research
- `.planning/research/ARCHITECTURE.md` — the `action_queue` design and the
  shared-sqlite-only bot↔app channel discipline this phase obeys.
- `.planning/research/PITFALLS.md` — Pitfall 3 (sqlite writer/writer contention;
  the `busy_timeout` + retry hardening the enqueue path inherits from Phase 5).

### Prior design / spec
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — the
  validate-then-write / inline-error / no-secrets panel invariants the dashboard
  preserves (D-10's no-raw-error rule sits under the no-secrets invariant).
- `JINXXY_DEPLOY.md` — Jinxxy API/deploy notes for the store sync.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`cogs/jinxxy.py::JinxxyCog._run_sync`** — the single orchestration path for
  every trigger (poll, `/tienda sync`, and now the queue handler). D-02's lock and
  mirror wrap this one method, which is why the guard is correct for all three
  entry points at once and why D-05's busy state is free.
- **`cogs/jinxxy.py::_record_sync_status`** — already writes both the
  `jinxxy_sync_status` row and the `activity_log` line on **every** run, success
  or failure, wrapped in a try/except that can never change the sync outcome.
  D-09's counts and D-12's attribution extend this exact method.
- **`cogs/action_queue_worker.py::ActionQueueCog._dispatch`** — the kind→handler
  dict; Phase 8 adds **one** entry. Its `_run_once` already maps a handler
  exception to `action_queue.fail(id, str(exc))`, which is the seam where D-10's
  category mapping must intervene (map the type *before* it reaches `fail`, or map
  at render time — planner's call, but the raw string must not reach the panel).
- **`core/db.py` migration idiom** — `ALTER TABLE … ADD COLUMN` inside
  `try/except sqlite3.OperationalError: pass  # Ya existe`, as used for
  `forum_posts` (`image_url`, `source_url`) and `reminders`. **This matters:**
  `jinxxy_sync_status` already exists in deployed databases, so
  `CREATE TABLE IF NOT EXISTS` will silently NOT add the D-02/D-07/D-09 columns.
- **`core/db.py::get_store_snapshot`** — returns `{checkout_url: Row}` and is
  already read per-keystroke by the `/tienda` autocomplete; D-13's table reads the
  same helper from the app process.
- **`app/main.py` shipped action endpoints** — `POST /api/actions`,
  `GET /api/actions/{id}`, `POST /api/actions/{id}/retry`, all `require_manager`.
  The sync trigger may reuse them directly or add a thin `/jinxxy`-scoped route
  for the D-04 dedupe; the short-poll surface already exists.
- **Phase-3 shell** — the `/jinxxy` route + sidebar entry + `--accent-jinxxy`
  already ship; only the stub body is replaced. Alpine is already vendored
  (`app/static/alpine.min.js`).

### Established Patterns
- **Shared sqlite (`DB_PATH`, WAL + `busy_timeout`) is the ONLY bot↔app channel.**
  The app holds **no Jinxxy/GitHub/Discord credentials** (locked) — it enqueues
  and reads, the bot syncs.
- **DB idiom:** fresh-connection-per-call; `init_*()` called from the owning cog's
  `__init__` (dual-process defensive init so the app never 500s on a missing
  table); parameterized SQL only; explicit column allowlists.
- **Errors go to logs only; never to a public Discord channel.** The one
  user-facing signal has always been a direct reply to the invoking staff member;
  the panel status is now its second, equally scoped surface (D-10).
- **Silent on no change** (`_announce` returns early unless `result["changed"]`) —
  preserved verbatim by D-11.
- **Manager-gated, POST-only, bilingual ES/EN Spanish-first** for every panel
  mutation and user-facing string.
- **At-least-once queue + module-owned idempotency** (Phase-5 D-08) — honored here
  by the overlap guard rather than a marker.

### Integration Points
- **Bot side:** an `asyncio.Lock`/busy flag + mirror writes around `_run_sync`
  (D-02); a `locked()` fast-path early-return in `_poll` (D-03); a mirror clear in
  `JinxxyCog.__init__` (D-06); one new `kind` handler in
  `ActionQueueCog._dispatch` that resolves the `JinxxyCog` from the bot, calls
  `_run_sync` then `_announce`, and returns the counts as the action result
  (D-09/D-11); exception-type → category mapping (D-10); source attribution in
  `_record_sync_status` (D-12).
- **DB:** widen `jinxxy_sync_status` via the ADD-COLUMN idiom with `running`,
  `started_at`, `source`, and the added/updated/removed counts.
- **App side:** replace the `/jinxxy` `module_stub` with a real page —
  `require_manager`-gated, reading `get_jinxxy_sync_status` + `get_store_snapshot`;
  a Manager-gated POST that enqueues `jinxxy_sync` with D-04 dedupe; Alpine
  short-poll driving the D-05/D-07 busy state and the D-09/D-10 result; the D-14
  table and D-15 empty states; `dashboard.css` blocks under `--accent-jinxxy`.
- **Unchanged:** `core/store_sync.py`, `core/jinxxy_api.py`,
  `core/github_publish.py`, the three `/tienda` commands, and the poll cadence.

</code_context>

<specifics>
## Specific Ideas

- **Already-syncing success copy (D-01):** *"Ya se está sincronizando · Sync
  already running"* — a calm success, never a red ✗. Same spirit as Phase-7's
  *"Ya estaba publicada."*
- **In-flight label (D-05/D-07):** *"Sincronizando… 1:20"* with a source tag —
  *programada · desde el panel · desde Discord*.
- **Error categories (D-10):** *"No pude contactar con Jinxxy · Couldn't reach
  Jinxxy"* (JinxxyAPIError), *"No pude publicar en la web · Couldn't commit to the
  site"* (GitHubPublishError), *"Falló la sincronización · Sync failed"*
  (anything else) — each with *"revisa los logs"*, echoing the shipped
  *"No pude sincronizar ahora; revisa los logs."*
- **Success copy (D-09):** reuse the `/tienda sync` wording —
  *"3 nuevos · 2 actualizados · 1 quitado"* / *"Sin cambios."*
- **Never-synced empty states (D-15):** *"Nunca se ha sincronizado · Never
  synced"* on the card; *"Aún no hay productos sincronizados · No synced products
  yet"* in the table area.
- **Bot-offline state (D-08):** reuse Phase-5's *"bot offline — will run on
  reconnect"* wording.
- **Attribution (D-12):** *"Sync de Jinxxy desde el panel (Nombre) · Jinxxy sync
  from the panel (Name)"* vs *"programada · scheduled"*.

</specifics>

<deferred>
## Deferred Ideas

- **Editing store metadata from the panel** (D-17) — images and bilingual
  descriptions (`/tienda medios`) and the credited editor (`/tienda editar`) stay
  on the Discord commands. A future phase could bring them into the D-13 table as
  an edit affordance; they are deliberately out of Phase 8, which is trigger +
  status + read-only view.
- **A time-based cooldown between manual syncs** — considered alongside D-04 and
  rejected as redundant once duplicates dedupe at enqueue. Revisit only if the
  Jinxxy or GitHub API rate limits ever bite.
- **Surfacing the D-09 counts on the Overview tile** — left to the planner's
  discretion; the Jinxxy section is the required surface.
- **Sync-progress detail** (per-step "enumerating / merging / committing")
  — rejected in favor of an indeterminate spinner + elapsed (D-07); it would
  require new bot→app progress pushes for a run that is usually short.

</deferred>

---

*Phase: 8-Jinxxy Manual Sync*
*Context gathered: 2026-07-24*
