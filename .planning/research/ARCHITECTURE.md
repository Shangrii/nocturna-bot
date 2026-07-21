# Architecture Research — v2.0 Staff Dashboard

**Domain:** MEE6-style staff dashboard grafted onto an existing two-process Discord bot +
FastAPI admin app, sharing one sqlite file.
**Researched:** 2026-07-21
**Confidence:** MEDIUM-HIGH (grounded directly in this codebase's existing code, not generic
ecosystem docs — the open questions are genuinely new for this project, but every
recommendation below extends a pattern that already ships and is already validated)

## Standard Architecture

### System Overview (target, v2.0)

```
┌───────────────────────────────┐        ┌──────────────────────────────────────────┐
│   discord.py bot process      │        │   FastAPI admin app process (dashboard)   │
│   (systemd unit: bot)         │        │   (systemd unit: editors-app)             │
│                                │        │                                            │
│  cogs/gallery.py  ─┐           │        │  app/deps.py                              │
│  cogs/reviews.py  ─┤           │        │    require_editor (unchanged)             │
│  cogs/jinxxy.py   ─┼─ business │        │    require_owner   (unchanged)             │
│  cogs/meeting.py  ─┘  logic    │        │    require_tier(min)  ← NEW, layers on the │
│  cogs/reminders.py             │        │    same live-role-recheck pattern          │
│  cogs/presence.py              │        │                                            │
│                                │        │  app/main.py                              │
│  core/github_publish.py  ──────┼────────┼─→ (already called directly for editors)   │
│  core/discord_names_sync.py    │        │  app/routers/gallery.py    ← NEW           │
│    (NEW: gateway cache → DB)   │        │  app/routers/reviews.py    ← NEW           │
│  core/action_queue.py          │        │  app/routers/reminders.py  ← NEW (pure DB) │
│    (NEW: poller/dispatcher)    │        │  app/routers/jinxxy.py     ← NEW           │
│                                │        │  app/routers/meetings.py   ← NEW           │
│  ── polls ──────────┐          │        │  app/routers/settings.py   ← extended      │
│                      ▼          │        │                                            │
└───────────────────────┬────────┘        └────────────────────┬───────────────────────┘
                         │                                      │
                         │        shared sqlite (DB_PATH, WAL)  │
                         ▼                                      ▼
        ┌───────────────────────────────────────────────────────────────────┐
        │  settings         (existing — config, now + MANAGER_ROLE_IDS)     │
        │  reminders        (existing — CRUD, + new `paused` column)        │
        │  store_snapshot   (existing — jinxxy sync)                        │
        │  presence         (existing — bot→app cache, precedent pattern)   │
        │  discord_names    (NEW — bot→app cache: channel/role id → name)   │
        │  action_queue     (NEW — app→bot request/result, generic)        │
        │  meetings         (NEW — bot writes at publish time; app reads/   │
        │                    edits/requests re-publish via action_queue)   │
        │  gallery_pending / reviews_pending (NEW — bot→app cache: which   │
        │                    messages are awaiting approval)               │
        └───────────────────────────────────────────────────────────────────┘
                         │                                      │
                         ▼                                      ▼
              ┌────────────────────┐                 ┌────────────────────────┐
              │ Discord Gateway/REST│                 │ GitHub Git Data API     │
              │ (bot token, live)   │                 │ (already shared today) │
              │ Jinxxy API (bot only)│                │ core/github_publish.py │
              └────────────────────┘                 └────────────────────────┘
```

Both boxes remain **separate OS processes** (two systemd units on host "cinema"), exactly as
today. Nothing in this milestone introduces a third process, a socket, or a direct
process-to-process RPC call. The shared sqlite file is *still* the only channel between them
— this milestone only adds tables to it and, in one direction (bot → app), generalizes an
already-shipped pattern (`presence`) instead of inventing a new one.

### Component Responsibilities

| Component | Responsibility | New / Modified |
|-----------|-----------------|-----------------|
| `app/deps.py::require_tier(min_tier)` | Resolve the caller's tier (`owner`/`manager`/`editor`) from session + live Discord roles + the settings-stored role→tier mapping; deny below `min_tier` | **NEW** (built alongside existing `require_editor`/`require_owner`, which it can subsume or wrap) |
| `core/settings.py` schema | Adds `MANAGER_ROLE_IDS` (role_list) under a new `"access"` group | **MODIFIED** (pure data addition, reuses `_validate_role_id_list`) |
| `core/discord_names_sync.py` + a `DiscordNamesCog` | Bot-side: on `on_ready` + `on_guild_channel_update`/`on_guild_role_update` (and a slow periodic refresh), write `{id, kind, name}` into `discord_names` from the bot's already-live gateway cache (zero extra REST calls) | **NEW** |
| `core/action_queue.py` (core, framework-agnostic) + a bot-side `ActionQueueCog` | Generic `enqueue(kind, payload) -> action_id` (called from the FastAPI app) / `claim_next()` + `complete(action_id, result)` (called from the bot's poll loop) against a new `action_queue` table | **NEW** |
| `cogs/gallery.py::_publish` / `_unpublish` | Refactored to be callable with a `message_id` (fetched via `channel.fetch_message`) from **either** the reaction listener **or** the new `ActionQueueCog` dispatcher — one implementation, two callers | **MODIFIED** (thin refactor, not a rewrite) |
| `cogs/reviews.py::_publish` / `_unpublish` | Same refactor as gallery | **MODIFIED** |
| `cogs/jinxxy.py::JinxxyCog._run_sync` | Already framework-light; wire a `"jinxxy_sync"` action-queue kind to call it directly (no change to the method itself) | **MODIFIED** (thin wiring only) |
| `core/db.py` | New `init_meetings`/`init_gallery_pending`/`init_reviews_pending`/`init_discord_names`/`init_action_queue`, all `CREATE TABLE IF NOT EXISTS`, called from the owning cog's `__init__` (existing idiom) | **MODIFIED** |
| `cogs/meeting.py` | Persist `(thread_id, title, date_utc, summary, transcript, notes)` into a new `meetings` table right after `_publish` succeeds; add a `"meeting_republish"` action-queue handler that edits/posts to the stored `thread_id` | **MODIFIED** |
| `app/routers/*.py` (gallery/reviews/reminders/jinxxy/meetings) | New FastAPI routers behind `require_tier("manager")`; reminders CRUD hits `core/db.py` directly (no queue — mirrors the existing settings read-at-use flow); the other four enqueue into `action_queue` and poll/return the row's status | **NEW** |
| `app/templates/*`, `app/static/*` | Dashboard shell (sketch 001 variant A) — sidebar, per-module color accents, module pages | **NEW** (front-end only, no backend logic of its own) |

## Recommended Project Structure

```
core/
├── db.py                     # + init_meetings, init_gallery_pending, init_reviews_pending,
│                              #   init_discord_names, init_action_queue (same idiom as today)
├── settings.py                # + "access" group: MANAGER_ROLE_IDS
├── github_publish.py           # unchanged — already framework-agnostic, already dual-called
├── action_queue.py             # NEW — pure module: enqueue/claim_next/complete, no discord import
├── discord_names_sync.py       # NEW — pure module: upsert helpers around discord_names table
└── access.py                   # NEW — pure module: resolve_tier(role_ids, discord_user_id) →
                                 #   "owner" | "manager" | "editor" | None (shared by deps.py
                                 #   AND any future need to know "what tier is this Discord id")

cogs/
├── gallery.py                  # _publish/_unpublish refactored to take a message_id
├── reviews.py                  # same refactor
├── jinxxy.py                   # + a queue-kind wire-up for "jinxxy_sync"
├── meeting.py                  # + meetings table write, + "meeting_republish" handler
├── discord_names.py             # NEW — DiscordNamesCog (gateway cache → discord_names table)
└── action_queue_worker.py       # NEW — ActionQueueCog: a fast tasks.loop that claims + dispatches
                                 #   queued actions to the right cog method, writes back the result

app/
├── deps.py                     # + require_tier(min_tier); require_editor/require_owner stay
│                                #   (require_owner becomes require_tier("owner") internally)
├── main.py                     # mounts the new routers; dashboard shell routes
├── routers/                    # NEW package
│   ├── gallery.py               # list gallery_pending, POST approve/remove → enqueue
│   ├── reviews.py                # same shape as gallery
│   ├── reminders.py               # pure CRUD against core/db.py — NO queue involved
│   ├── jinxxy.py                  # POST sync-now → enqueue; GET last-sync status
│   ├── meetings.py                 # list/edit meetings table; POST re-publish → enqueue
│   └── settings.py                  # existing settings page + new MANAGER_ROLE_IDS field +
│                                     #   Discord-name-resolved labels (reads discord_names)
├── templates/                   # dashboard shell templates (sketch 001 variant A)
└── static/                      # sidebar/module CSS, Alpine-driven table+modal components
```

### Structure Rationale

- **`core/action_queue.py` and `core/discord_names_sync.py` are pure** (no `discord`/`fastapi`
  import), matching the existing house style (`core/store_sync.py`, `core/editors_model.py`,
  `core/settings.py`) — they're the framework-agnostic, unit-testable center; the cog and the
  FastAPI router are thin adapters around them.
- **`core/access.py` is a new single seam** for "what tier does this Discord identity have,"
  reused by `app/deps.py::require_tier`. Keeping tier resolution out of `deps.py` itself keeps
  `deps.py` a thin HTTP-layer file (as it is today) and makes the tier logic independently
  testable without a `Request` object, mirroring how `core/settings.py` is tested without FastAPI.
- **Gallery/reviews `_publish`/`_unpublish` stay in the cogs**, just parameterized — the
  alternative (duplicating this logic into a new admin-app-side REST client) was considered and
  rejected; see Anti-Patterns.

## Architectural Patterns

### Pattern 1: Generalized command queue (app → bot), extending the settings precedent

**What:** A new `action_queue` table (`id, kind, payload_json, status, requested_by,
requested_at, claimed_at, completed_at, result_json`). The FastAPI app inserts a row
(`status='pending'`) when a Manager clicks Approve/Remove/Sync-now/Re-publish. A new
`ActionQueueCog` (bot side) runs a `@tasks.loop(seconds=5)` — the same idiom already used by
`cogs/jinxxy.py`'s poll and `cogs/reminders.py`'s scheduler — claims the oldest pending row
(`UPDATE ... SET status='claimed' WHERE id=? AND status='pending'`, avoiding double-claim on a
single-process bot), dispatches on `kind` to the right cog method (`GalleryCog._publish(
message_id)`, `ReviewsCog._unpublish(message_id)`, `JinxxyCog._run_sync()`, a new
`MeetingCog._republish(meeting_id)`), then writes `status='done'|'error'` + `result_json`. The
FastAPI route either polls the row (2-3 short polls, ~1-2s apart, typical for a button click)
or the front-end polls a `GET /api/actions/{id}` endpoint.

**When to use:** Any panel-initiated action whose correctness depends on the bot's *own*
in-process business logic — specifically, anything that must also update the Discord
message's reaction-based "published" marker (gallery/reviews — see Pitfall below) or that
already lives inside a stateful/rate-limit-aware bot method (`jinxxy._run_sync`, meeting
forum posting).

**Trade-offs:** Adds a few seconds of latency vs. a live HTTP round-trip; adds one new table
and one new cog. In exchange: zero new write-capable Discord credential usage in the FastAPI
process, zero duplicated business logic, and Discord's per-bot-token rate-limit bucket stays
managed by the ONE process (discord.py's own internal rate limiter) that already owns it —
see Anti-Pattern 1 below for why this matters.

**Example:**
```python
# core/action_queue.py (pure)
def enqueue(kind: str, payload: dict, requested_by: str) -> int:
    with db._get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso()))
        return cur.lastrowid

def claim_next() -> sqlite3.Row | None:
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM action_queue WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return None
        conn.execute("UPDATE action_queue SET status='claimed', claimed_at=? WHERE id=?",
                     (_now_iso(), row["id"]))
    return row
```

### Pattern 2: Reverse-direction cache table (bot → app), extending the `presence` precedent

**What:** `cogs/presence.py` already writes `{discord_id, status}` into a `presence` table
that the FastAPI app reads read-only at `/api/presence/<id>` — the exact comment in that
file even calls it "native live Discord status." This milestone adds a second instance of the
same pattern: a `discord_names` table (`id TEXT, kind TEXT` ('channel'|'role'), `name TEXT,
updated_at`), populated by a new `DiscordNamesCog` from data the bot's gateway connection
*already has cached in memory* (`guild.channels`, `guild.roles`) — no incremental REST call
is needed at all. Refresh on `on_ready` (full dump) plus `on_guild_channel_update` /
`on_guild_role_update` / `on_guild_channel_delete` / `on_guild_role_delete` (incremental,
event-driven) keeps it fresh with zero polling.

**When to use:** Any "show me a Discord name" need in the admin app — this milestone's
Settings-panel POLISH-01 (`#channel`/`@role` labels) and any future name lookups.

**Trade-offs:** A short staleness window is possible (a channel renamed seconds ago might
show its old name until the next event fires) — acceptable for a settings label. The
alternative (the FastAPI app calling Discord REST directly with the bot token on every
render) was considered and is explicitly NOT recommended — see Anti-Pattern 2.

### Pattern 3: Tiered authorization as a single parametrized dependency

**What:** `require_tier(min_tier: Literal["editor","manager","owner"])` returns a FastAPI
dependency function. It:
1. Runs the SAME session + live-role-recheck logic `require_editor` already runs (D-08 IDOR
   discipline preserved — identity from `request.session` only).
2. Fetches the caller's full role-id set via ONE bot-token REST call (the existing
   `has_editor_role` already makes this exact call shape; generalize it to return
   `set(member["roles"])` instead of a single bool).
3. Calls `core/access.py::resolve_tier(role_ids, discord_id)`:
   - `discord_id == config.DISCORD_USER_ID` (fail-closed on unset/`0`, same guard as
     `require_owner` today) → `"owner"`, unconditionally — role-mapping edits can never
     lock the owner out.
   - else `role_ids & set(settings.get("MANAGER_ROLE_IDS"))` → `"manager"`.
   - else `config.ROLE_MODERATOR_ID in role_ids` (today's editor role) → `"editor"`.
   - else → `None` (401/403).
4. Compares the resolved tier against `min_tier` on a fixed ladder
   (`owner > manager > editor`) and raises 403 if below.

**When to use:** Every new module route. `require_owner` (Settings) becomes
`require_tier("owner")`; the five staff-operations modules (Gallery/Reviews/Reminders/
Jinxxy/Meetings) use `require_tier("manager")`; the Editors presentation section keeps
`require_editor`/`require_tier("editor")` (same population as today, framed as the bottom
rung of the same ladder rather than a separate concept).

**Trade-offs:** One extra Discord REST read per protected request (same cost `require_editor`
already pays today — no new expense class, just reused for more routes). The role→tier
mapping is read via `settings.get("MANAGER_ROLE_IDS")` — already read-at-use with no cache to
invalidate, so an owner's edit in Settings takes effect on the very next request, with zero
extra plumbing (Phase-1's "reload = read-at-use" decision applies unchanged).

## Data Flow

### Flow 1: Owner edits the Manager role mapping (extends the existing Phase-2 flow, unchanged shape)

```
Owner (Settings module, require_tier("owner"))
    → POST /admin/settings {MANAGER_ROLE_IDS: "123,456"}
    → settings.validate_only (role_list validator, existing) → settings.set (existing)
    → sqlite `settings` table row updated
    → NEXT request to ANY module: require_tier reads settings.get("MANAGER_ROLE_IDS") fresh
      → new Manager access takes effect immediately, no restart (same guarantee as Phase 1)
```

### Flow 2: Manager approves a gallery photo from the dashboard

```
Manager clicks "Approve" in the Gallery module (require_tier("manager") passed)
    → POST /dashboard/gallery/{message_id}/approve
    → app/routers/gallery.py calls core/action_queue.enqueue("gallery_publish",
      {"message_id": ...}, requested_by=session discord_id)
    → row inserted, status='pending'
    → front-end polls GET /api/actions/{id} every ~1s
    ↓ (bot process, independently)
ActionQueueCog._poll (tasks.loop, ~5s) claims the row
    → dispatches to GalleryCog._publish(message_id) — SAME method the ✅ reaction calls
    → optimizes images, commits via github_publish (existing), adds 🟢/🌙 reactions (existing)
    → writes status='done', result_json={"count": N}
    ↓
front-end poll sees status='done' → shows the success toast
    ↓ (in parallel, bot-side cache refresh)
GalleryCog also removes the row from `gallery_pending` (the queue-list cache the dashboard's
Gallery module reads to render "awaiting approval" — populated on the ✅-prompt add, removed
on publish/dismiss, mirroring `gallery_state`'s existing cursor-table idiom)
```

### Flow 3: Dashboard renders `#channel`/`@role` names in Settings (POLISH-01)

```
Bot process, on_ready / on_guild_channel_update / on_guild_role_update
    → DiscordNamesCog reads its OWN already-cached guild.channels / guild.roles
    → upserts {id, kind, name} into `discord_names` (no REST call — pure gateway-cache dump)
    ↓
FastAPI Settings route
    → for each snowflake-typed setting, SELECT name FROM discord_names WHERE id=?
    → renders "#general (1416329356426481717)" — falls back to the bare id if the cache
      has no row yet (fresh bot restart before first on_ready, or an id the bot has never
      seen) — never blocks the page render on a live REST call
```

### Key Data Flows

1. **Config/tier flow (app writes, bot+app read-at-use):** Settings table — extended, not
   changed in shape. An owner edit is visible to both processes on their very next read.
2. **Action-request flow (app writes, bot executes, both read result):** the new
   `action_queue` table — the only new "channel" direction, and it is the write-side mirror
   of the read-side pattern the settings table already established.
3. **Cache-refresh flow (bot writes, app reads):** `presence` (existing) and the new
   `discord_names` / `gallery_pending` / `reviews_pending` tables — all the same shape:
   the bot pushes a snapshot of state it already holds in memory; the app never needs to ask
   Discord anything itself.

## Anti-Patterns

### Anti-Pattern 1: FastAPI app makes write-side Discord REST calls directly (reactions, forum posts)

**What people would do:** Since `app/auth.py::has_editor_role` already makes a bot-token REST
*read* call directly from the FastAPI process, it's tempting to extend that to *writes*
(add/remove reactions, post to a forum thread) so the panel gets instant feedback with no
queue.

**Why it's wrong:** Two independent processes each holding the same bot token would each run
their own in-memory rate-limit bookkeeping — discord.py's `Client` in the bot process already
tracks Discord's per-route/global rate-limit buckets and backs off correctly; a second raw
`httpx` client in the FastAPI process has no visibility into that state, so concurrent
bursts (a Manager clicking Approve on 5 photos while the bot is mid-backfill) are more likely
to trip Discord's rate limiter than if all writes funnel through the one process that already
manages it. It also means the gallery/reviews publish business logic (idempotency-by-🟢-marker,
caption trimming, filename generation, retry/⚠️-surfacing) would need a **second
implementation** in the admin app, which is exactly the kind of two-codebases-one-behavior
drift risk this codebase has otherwise avoided (`core/github_publish.py`,
`core/store_sync.py` etc. are already shared, not duplicated).

**Do this instead:** Route every write-side Discord action through the bot process via the
action-queue pattern (Pattern 1). Reserve direct-from-panel Discord REST calls for **reads
only** (which `has_editor_role` already does, and which the `discord_names`/`gallery_pending`
cache tables make largely unnecessary anyway).

### Anti-Pattern 2: An internal HTTP endpoint on the bot process

**What people would do:** Stand up a small aiohttp/FastAPI listener inside the bot process
(or alongside it) that the admin app calls synchronously for "do this Discord thing now,"
avoiding queue-poll latency.

**Why it's wrong:** It reverses an already-validated project decision — PROJECT.md records
"No IPC/socket/signal is built — sqlite is the channel" as a **validated** Phase-1 outcome,
specifically because both processes already share the sqlite file and adding a second
channel doubles the surface that needs its own auth, its own failure mode (what happens to a
panel action mid-request if the bot is mid-restart — sqlite already answers this
gracefully; an HTTP call to a possibly-down bot does not), and its own audit trail. It also
adds a new listening port to a deployment that has deliberately kept the bot process
network-passive.

**Do this instead:** The action-queue table already gives the panel a durable, resumable
request/result contract that survives either process restarting mid-action — a bot restart
mid-poll simply resumes claiming pending rows on its next tick; an HTTP call mid-flight would
just fail.

### Anti-Pattern 3: Letting the panel bypass reaction bookkeeping "because it's just a JSON commit"

**What people would do:** Since `core/github_publish.py` is already framework-agnostic and
already called directly by the admin app (`app/main.py`'s `/editor/save` /-image/-media/-audio
routes), it's tempting to have the new Gallery/Reviews panel routes call
`github_publish.publish_message`/`remove_message`/`publish_review`/`remove_review` directly,
skipping the Discord-side 🟢/🌙 reaction bookkeeping entirely (it's "just cosmetic," and the
GitHub commit is the real state).

**Why it's wrong:** For gallery/reviews specifically, the 🟢 marker reaction on the original
Discord message IS the durable "is this published" flag the LIVE `on_raw_reaction_add`
handler checks (`_is_published`) — it is not merely cosmetic. If the panel commits to GitHub
without setting 🟢, a staff member still using Discord reactions in parallel would see an
unmarked, apparently-still-pending photo and re-approve it via ✅, and the backfill/reconcile
pass would only be saved from double-publishing because it *also* cross-checks
`gallery.json` entries (a defense that live reaction handling does not have). Reviews and
gallery are the two modules where "parity with the reaction flow" is an explicit requirement
(PROJECT.md), which is precisely the signal that both interfaces must converge on the same
state, not two independently-progressing ones.

**Do this instead:** Route gallery/reviews approve+remove through the action queue so the
EXACT SAME cog method — reactions and all — runs regardless of which interface triggered it.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|----------------------|-------|
| Discord Gateway + REST (bot token) | Bot process only for writes (reactions, forum posts, thread edits); bot process also owns the `discord_names`/`presence` gateway-cache dumps. FastAPI process keeps its existing READ-only bot-token usage (`has_editor_role`, now generalized to `resolve_tier`) | Never add write-side bot-token calls to the FastAPI process (Anti-Pattern 1) |
| GitHub Git Data API (`core/github_publish.py`) | Already shared between both processes (bot for gallery/reviews/store; admin app for editors) | The module's `_commit_lock` is an `asyncio.Lock()` — **process-local**, not cross-process. Two processes committing to the same branch concurrently are only protected by the existing 409/422 retry-with-backoff (D-18), not by mutual exclusion. This was already true before v2.0 (the editors app already commits independently of the bot); v2.0 adds more concurrent commit paths (gallery/reviews/meetings) from the SAME bot process via the action queue, so this risk does not actually increase — the queue serializes bot-side commits through the bot's own single event loop and lock, same as today |
| Jinxxy API (`core/jinxxy_api.py`) | Bot-only, unchanged. The panel never calls Jinxxy directly — it only enqueues `"jinxxy_sync"` and reads `store_snapshot`/a last-sync-result row | No new credential exposure |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|----------------|-------|
| FastAPI dashboard ↔ bot (config/tiers) | `settings` table, read-at-use | Unchanged shape from Phase 1/2 |
| FastAPI dashboard ↔ bot (action trigger) | `action_queue` table, request/poll/result | NEW — the one genuinely new cross-process contract this milestone adds |
| bot ↔ FastAPI dashboard (name/status cache) | `presence` (existing), `discord_names`/`gallery_pending`/`reviews_pending` (NEW) | All same shape: bot pushes a snapshot of state it already holds |
| Reminders module ↔ bot scheduler | `reminders` table CRUD, read-at-due-time | No new integration needed — this module is pure DB CRUD end to end, same as before; only a `paused` column is new |
| Meetings module ↔ bot | `meetings` table (bot writes at publish time, panel reads/edits text) + `action_queue` (panel-triggered re-publish only) | Recording/transcription/summarization stays 100% bot-only and out of the panel's reach — the panel only ever touches an ALREADY-generated summary |

## Scaling Considerations

This is an internal staff tool for one guild with a handful of staff accounts — there is no
public-traffic scaling axis to plan for. The only "scale" that matters is **perceived
latency of the action queue** vs. **poll interval**:

| Scale | Approach |
|-------|----------|
| Current (a few staff, occasional approvals) | `@tasks.loop(seconds=5)` poll is imperceptible for a button click; no changes needed |
| If action volume grows (e.g. bulk-approving 50 photos) | Batch dispatch: claim + process several pending rows per tick instead of one, still within the same loop — no architecture change, just a loop-body tweak |
| If sub-second feedback ever becomes a hard requirement | Would justify revisiting Anti-Pattern 2 (bot-side HTTP endpoint) deliberately, as its own scoped decision — not something to pre-build now |

## Sources

- This codebase, read directly (HIGH confidence — these are the actual files this milestone
  extends, not analogous examples):
  - `app/deps.py` — `require_editor`/`require_owner` (the pattern `require_tier` extends)
  - `app/main.py` — existing direct `github_publish` calls from the FastAPI process, existing
    `db.init_presence()`/`db.init_view_counts()` lifespan pattern
  - `app/auth.py::has_editor_role` — the existing bot-token REST read from the FastAPI process
  - `core/db.py` — the `CREATE TABLE IF NOT EXISTS` idiom, the `settings`/`presence`/
    `gallery_state`/`store_snapshot` tables this milestone's new tables mirror
  - `core/settings.py` — the validated read-at-use config store this milestone's role→tier
    mapping reuses verbatim (`_validate_role_id_list`, `get`/`set`/`all_for_ui`)
  - `core/github_publish.py` — confirms the module is framework-agnostic and already
    dual-called; confirms the `_commit_lock` is process-local (`asyncio.Lock()`, line ~70)
  - `cogs/gallery.py`, `cogs/reviews.py` — confirms the 🟢/🌙 reaction markers are the durable
    published-state flag (`_is_published`), not merely cosmetic
  - `cogs/jinxxy.py` — confirms `_run_sync` is already a single orchestration method reused by
    both the poll loop and `/tienda sync`, the shape the action-queue wiring extends
  - `cogs/meeting.py` — confirms NO current persistence of transcripts/summaries (in-memory
    `MeetingSession` only, deleted after publish) — the `meetings` table is a genuine gap to fill
  - `cogs/presence.py` — the exact bot→app cache-table precedent `discord_names` extends
  - `bot.py` — confirms `intents.members = True` / `intents.presences = True` are already
    enabled, so the bot's gateway cache already has the channel/role/member data
    `discord_names_sync` needs, at zero extra REST cost
  - `.planning/PROJECT.md` — the "No IPC/socket/signal is built — sqlite is the channel"
    validated Key Decision (Anti-Pattern 2's basis) and the "v2.0 Admin app calls Discord API"
    /"Access tiers" pending Key Decisions this document resolves
- General Python knowledge (HIGH confidence, standard library behavior): `asyncio.Lock()` is
  scoped to a single process's event loop and provides no cross-process mutual exclusion —
  relevant to the `github_publish._commit_lock` note above.

---
*Architecture research for: v2.0 Staff Dashboard integration with the existing two-process
Nocturna bot + admin app*
*Researched: 2026-07-21*
