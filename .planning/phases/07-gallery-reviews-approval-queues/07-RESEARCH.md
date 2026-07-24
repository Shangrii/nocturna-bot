# Phase 7: Gallery + Reviews Approval Queues - Research

**Researched:** 2026-07-23
**Domain:** Discord-reaction-mediated publish pipeline wrapped in a Manager-facing web queue (FastAPI + Jinja2 + Alpine, shared-sqlite-only bot↔app channel)
**Confidence:** HIGH (all findings verified by direct read of the existing codebase — no external libraries are introduced this phase)

## Summary

Phase 7 does not add new technology. It wraps two already-shipped, fully-idempotent
Discord cogs (`cogs/gallery.py`, `cogs/reviews.py`) with a read cache (bot→app) and a
write queue (app→bot) using patterns that are **already proven in this codebase**:
`cogs/discord_names.py` (periodic snapshot push) and `core/action_queue.py` +
`cogs/action_queue_worker.py` (durable app→bot dispatch, already shipped and tested in
Phase 5). No new package, no new IPC mechanism, no new commit path is needed.

The single hardest problem in this phase is **not** idempotency (the 🟢-marker check
already guarantees GAL-02's no-double-publish for free, confirmed by direct code read)
— it is that `GalleryCog._publish`/`_unpublish` and `ReviewsCog._publish`/`_unpublish`
were built for the **reaction flow**, where failure is reported *on the Discord message*
(a ⚠️ reaction + a non-deleting reply) and the coroutine itself **never raises and never
returns a result**. The `action_queue` dispatcher, by contrast, decides success/failure
by whether the handler **raises**. Calling `_publish`/`_unpublish` verbatim from a new
`kind` handler therefore reports every dispatch as `done` — including a silent
staff-authorship-gate no-op or a swallowed `GitHubPublishError` — which is the opposite
of D-11's "no-op → quiet success, genuine failure → ✗ + Retry" contract. The fix is
cheap and requires **zero changes to gallery.py/reviews.py**: read the message's
🟢-marker state (via the already-exported pure helper `_is_published`) **before and
after** calling the existing `_publish`/`_unpublish`, and derive the queue result from
the state *transition*, not from the call's return value. This is directly aligned with
prior Phase-5 research guidance ("surface the panel's pending/settled state from the
SAME source of truth the reaction flow already uses — never a separate flag that can
drift"), and is elaborated with runnable code below.

The second finding worth flagging: the existing bot→app `discord_names` cache (Phase 4)
stores **channel and role names only** — it has never cached Discord *member* display
names. CONTEXT.md's D-03 phrase "poster resolved via the Phase-4 discord_names/push-cache
poster field" is therefore about *reusing the push-cache pattern*, not literally joining
against the existing `discord_names` table (which cannot resolve a poster). The new
gallery/reviews cache must have the bot resolve `message.author.display_name` itself, at
push time, while it already holds the live `discord.Message` object.

**Primary recommendation:** one new sqlite table (or two, module-scoped) populated by a
new bot-side cog that scans the two channels on a ~30–60s loop, classifies every message
via the cogs' own exported `_is_published`/`_review_author_and_text` helpers, and
**upserts** rows (never wholesale DELETE+INSERT like `discord_names`) so a poster/author
name resolved once for an old published item is never re-fetched from Discord on every
cycle. Four new `action_queue` `kind` handlers live in `ActionQueueCog._dispatch`,
each doing a pre-state check → call the existing cog method → post-state check → typed
result, with **no duplicated business logic**.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Pending/published queue detection (🟢 marker, entries) | Bot process (Discord gateway) | — | Only the bot holds a live Discord connection; pending state is Discord-native and cannot be derived by the app (locked, CONTEXT D-01) |
| Queue snapshot cache (read side) | Database / Storage (shared sqlite) | Bot process (writer) | Bot pushes; app only ever `SELECT`s — same discipline as `bot_heartbeat`/`discord_names` (T-03-08 precedent) |
| Queue page render + tabs + lightbox | Frontend Server (Jinja2 SSR) | Browser (Alpine short-poll) | Server-rendered on GET, Alpine handles tab toggle/poll/inline-status client-side — no build step, matches Phases 3/4/6 |
| Approve/Remove action intake | API / Backend (FastAPI POST route) | Database / Storage (`action_queue` write) | Manager-gated route validates + enqueues; never touches Discord/GitHub directly (locked no-credentials-in-app) |
| Approve/Remove action execution | Bot process (`ActionQueueCog` dispatch) | — | Only the bot process holds `GITHUB_PAT`/Discord token; re-invokes the existing cog `_publish`/`_unpublish` |
| Cross-repo commit (gallery.json/reviews.json/images) | Bot process (`core/github_publish.py`) | — | Unchanged this phase — the SAME transport, SAME `_commit_lock`, SAME idempotent dedupe-by-id tree-build |
| Inline per-action status polling | Browser (Alpine) | API / Backend (`/api/actions/{id}` reused) | Reuses the exact Phase-5 `overview.html` `actionProofApp` state machine, sized for a card footer |

## User Constraints (from CONTEXT.md)

<user_constraints>

### Locked Decisions

- **D-01: Bot→app push cache (the only viable route).** A bot cog pushes a snapshot of
  pending **and** published gallery/reviews items into a shared-sqlite cache, following
  the Phase-4 `discord_names`/`jinxxy_sync_status`/`bot_heartbeat` push idiom. The app
  reads this cache and never touches Discord or GitHub. **Rejected:** the app reading
  `gallery.json`/`reviews.json` directly — that surfaces only *published* items; *pending*
  items exist solely as Discord messages carrying the bot's ✅ prompt without a 🟢 marker.
- **D-02: Near-live cadence + Alpine auto-refresh.** The snapshot is re-pushed on a
  periodic loop (~30–60s, planner picks the exact interval) and the panel short-polls
  (Alpine, already shipped) so newly-posted pending items and status flips appear without
  a reload. Re-pushing refreshes the Discord CDN signed thumbnail URLs (expire ~24h) so a
  photo sitting in the queue never shows a dead thumbnail.
- **D-03: Gallery row fields — full judging context.** thumbnail, poster (staff editor
  display name), caption text, posted-at (relative), open-in-Discord message link.
- **D-04: Review row fields.** author (display name / fixed "Anónimo"), full review text,
  date, named/anonymous badge. Anonymity preserved end-to-end (D-13).
- **D-05: Gallery = responsive thumbnail grid; Reviews = text cards.**
- **D-06: Pending | Published tabs**, Pending default.
- **D-07: Click-to-expand lightbox** on gallery thumbnails.
- **D-08: Ride the Phase-5 `action_queue`; reuse the cog logic — do NOT reimplement.**
  Manager-gated POST routes `enqueue` typed actions (e.g. `gallery_publish` /
  `gallery_remove` / `review_publish` / `review_remove`, exact names = planner's call)
  with the Discord message id in the payload. `ActionQueueCog._dispatch` grows new `kind`
  handlers that re-fetch the message and call the existing `GalleryCog._publish`/
  `_unpublish` and `ReviewsCog._publish`/`_unpublish`. The shipped 🟢-marker idempotency
  IS the GAL-02 no-double-publish guarantee and satisfies the Phase-5 D-08 invariant
  ("the module owns idempotency").
- **D-09: Inline per-item status.** Working… → ✓ / ✗ (Phase-5 D-01/D-05) and the durable
  "bot offline — will run on reconnect" state (Phase-5 D-07) — no lost clicks.
- **D-10: Remove = confirm dialog; Approve = one-click.** Remove opens a confirm
  ("¿Quitar esta foto/reseña de la web?") — reversible (a removed item returns to Pending,
  re-approvable). Approve is single-click.
- **D-11: A moot/concurrent action resolves as a benign "already done" success, never a
  red error.** When a staff ✅/🌙 reaction (or a second Manager) already reached the target
  state, the bot's 🟢-marker check makes the dispatch a no-op. The panel must reflect this
  as a quiet success ("ya publicada"/"ya quitada"). **Implication:** the dispatch handler
  / status mapping must distinguish "no-op because already in the target state" (→
  success) from a genuine failure (→ ✗ + Retry, Phase-5 D-02).
- **D-12: Panel is approve/remove parity ONLY.** Editor-credit (`/galeria creditar`) and
  the NSFW flag stay Discord-only — deferred.
- **D-13: True end-to-end review anonymity is LOCKED (unchanged).** The push cache carries
  only "Anónimo" + text + date for an anonymous review; the submitter's name/id is NEVER
  written to shared sqlite. No tier (owner included) can de-anonymize.

### Claude's Discretion

- Exact push-cache table schema/column names and the precise refresh interval within
  ~30–60s; one shared cache table vs. one per module.
- Exact `action_queue` `kind` string names and payload shape (D-08).
- The precise Alpine short-poll interval (reuse the Phase-5 value).
- Whether the **published** list is sourced from the same push cache or read from the
  live `gallery.json`/`reviews.json` (both viable for *published*; only the push cache
  can carry *pending*).
- Lightbox implementation (native/Alpine) and grid breakpoints (D-05/D-07).
- All bilingual ES/EN copy: confirm dialogs, empty states, badges, "already done"/"bot
  offline" messages (Spanish-first house style).

### Deferred Ideas (OUT OF SCOPE)

- **Editor-credit + NSFW flag in the panel** (D-12) — stays available via
  `/galeria creditar` (Discord-only).
- **Owner-only de-anonymization of anonymous reviews** (D-13) — rejected, not merely
  deferred; breaks the anonymity guarantee.
- **Reviews collection panel management** (`panel_resenas`) from the dashboard — out of
  scope; client-facing Discord affordance.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GAL-01 | A Manager can see the queue of photos pending approval | New bot-side push-cache cog (mirrors `cogs/discord_names.py`) writes pending gallery rows into shared sqlite; new `app/routers/gallery.py` GET route reads them (mirrors `app/routers/reminders.py`) |
| GAL-02 | Approve publishes with ✅-flow parity, no double-publish on a concurrent reaction | `gallery_publish` `action_queue` kind re-invokes `GalleryCog._publish` verbatim — the existing 🟢-marker check inside `_publish` (line 159 of `cogs/gallery.py`) is the sole idempotency gate; nothing new needed |
| GAL-03 | Remove a published photo (🌙 parity) | `gallery_remove` kind re-invokes `GalleryCog._unpublish` verbatim — same 🟢-marker branch |
| REV-01 | Approve a pending review → publishes to `reviews.json` | `review_publish` kind re-invokes `ReviewsCog._publish` verbatim |
| REV-02 | Remove a published review from the website | `review_remove` kind re-invokes `ReviewsCog._unpublish` verbatim |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

No `./CLAUDE.md` file exists at the repository root. No `.claude/skills/`/`.agents/skills/`
directory was found either — no additional project-level directives beyond the locked
CONTEXT.md decisions and the established codebase idioms documented below.

## Standard Stack

No new external package is introduced this phase (verified — see Package Legitimacy Audit
below). Every building block is already installed and already used elsewhere in this
repository:

### Core (already installed, reused)
| Library | Version | Purpose | Why Standard (for this repo) |
|---------|---------|---------|-------------------------------|
| `discord.py` | (existing, unchanged) | Bot-side gateway/REST, reaction handling, message fetch | Already the bot's Discord client library — used unchanged by the new push-cache cog and the new `action_queue` dispatch handlers |
| `FastAPI` + `Jinja2Templates` + `starlette` | (existing, unchanged) | App routes, server-rendered templates, session | Already the app framework (`app/main.py`) — new routes follow `app/routers/reminders.py`'s router-module pattern |
| `Alpine.js` (vendored, `app/static/alpine.min.js`) | 3.15.12 (per `app/main.py` docstring) | Client-side tabs/lightbox/short-poll/inline-status | Already vendored, no CDN, no build step — reused verbatim per UI-SPEC |
| `sqlite3` (stdlib) via `core/db.py` | — | Shared bot↔app channel | The ONLY cross-process channel (locked) — `WAL` + `busy_timeout=8000` already configured in `_get_conn()` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `requests` (via `core/github_publish.py`) | (existing, unchanged) | Cross-repo commit transport | Unchanged — Phase 7 never calls it directly; only through the existing cog `_publish`/`_unpublish` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Bot→app sqlite push cache for BOTH pending and published rows | App reads live `gallery.json`/`reviews.json` from the public website for the *Published* tab only | Technically possible without credentials (public GitHub Pages JSON), but (a) unconfirmed whether `src/data/*.json` is actually copied into the deployed `public/` output at a stable public URL — Astro projects commonly do NOT expose `src/data/*.json` as a static asset unless explicitly re-exported (b) still can't resolve the poster/author display name (not stored in gallery.json) without falling back to a Discord fetch anyway (c) introduces a SECOND source-of-truth path (public HTTP fetch vs. sqlite cache) for what should be one snapshot mechanism. **Recommendation: push cache carries both pending AND published rows — single mechanism, unambiguous, no new failure mode.** [ASSUMED: gallery.json public-URL exposure unconfirmed]
| Wholesale DELETE+INSERT snapshot replace (`discord_names`/`replace_discord_names` idiom) | Upsert + prune idiom (`store_snapshot`/`upsert_store_snapshot`+`delete_store_snapshot` idiom) | Wholesale replace is simpler but forces re-resolving every published item's poster/author display name (a live Discord fetch) on EVERY cycle — expensive and unnecessary once a name is known. **Recommendation: upsert idiom** — resolve a poster/author name once, on first sight, then keep it; only re-resolve if a row transitions pending→published or is newly discovered. |

**Installation:** none — no `npm install`/`pip install` needed this phase.

**Version verification:** not applicable — no new package versions to verify.

## Package Legitimacy Audit

**Not applicable this phase.** No external package (npm/PyPI/cargo) is installed,
upgraded, or newly imported. Every module Phase 7 touches (`discord.py`, `FastAPI`,
`sqlite3`, `requests`, `Jinja2`, Alpine.js) is already a dependency of this repository,
already vetted in prior phases, and unchanged here.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | — | No new packages this phase |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
 DISCORD (source of truth for pending state)
   │
   │ ✅/🌙 reactions (unchanged, live)          message.author, attachments, reactions
   ▼
 ┌─────────────────────────── BOT PROCESS ───────────────────────────────────┐
 │                                                                            │
 │  cogs/gallery.py / cogs/reviews.py   (UNCHANGED — _publish/_unpublish,    │
 │        _is_published, _is_staff, _review_author_and_text)                 │
 │                                                                            │
 │  NEW: cogs/gallery_reviews_cache.py  (or two files)                       │
 │    ~30-60s loop → channel.history() scan (bounded) + _fetch_json(entries) │
 │    → classify pending/published via existing pure helpers                 │
 │    → resolve poster/author display_name from the live discord.Message    │
 │    → UPSERT into shared sqlite (gallery_queue / reviews_queue tables)     │
 │                                                                            │
 │  cogs/action_queue_worker.py  (EXTENDED — 4 new `kind` handlers)          │
 │    claim_next() → gallery_publish/gallery_remove/review_publish/          │
 │    review_remove → pre-state check (_is_published) → call existing        │
 │    cog._publish/_unpublish verbatim → post-state check → typed result     │
 │    → action_queue.complete(id, result) / .fail(id, error)                 │
 │                                                                            │
 └────────────┬───────────────────────────────────────────┬─────────────────┘
              │ writes (bot→app)                           │ reads (claims)
              ▼                                             ▲
        ┌───────────────────── SHARED SQLITE (WAL, busy_timeout=8000) ─────────────┐
        │  gallery_queue / reviews_queue (NEW, bot-written, app-read)              │
        │  action_queue (Phase 5, EXTENDED with 4 new `kind` values)               │
        └───────────────────┬───────────────────────────────────────┬─────────────┘
                             │ reads (SELECT only)                   │ writes (enqueue)
                             ▼                                       │
 ┌────────────────────────── FASTAPI APP PROCESS (NO Discord/GitHub creds) ────────┐
 │                                                                                   │
 │  NEW: app/routers/gallery.py, app/routers/reviews.py                            │
 │    GET /gallery, /reviews  → read cache → render gallery.html/reviews.html       │
 │    POST .../{message_id}/approve → require_manager → action_queue.enqueue(...)  │
 │    POST .../{message_id}/remove  → require_manager → action_queue.enqueue(...)  │
 │                                                                                   │
 │  REUSED: /api/actions/{action_id}  (app/main.py, unchanged) → inline status poll │
 │                                                                                   │
 └───────────────────────────────────┬───────────────────────────────────────────┘
                                      │ HTML + Alpine short-poll
                                      ▼
                              BROWSER (Manager's dashboard)
```

### Recommended Project Structure
```
cogs/
├── gallery.py                    # UNCHANGED — _publish/_unpublish/_is_published reused
├── reviews.py                    # UNCHANGED — same
├── gallery_reviews_cache.py      # NEW — bot-side push-cache cog (D-01/D-02)
└── action_queue_worker.py        # EXTENDED — 4 new `kind` handlers added to _dispatch

core/
├── db.py                         # EXTENDED — init_gallery_queue/init_reviews_queue +
│                                  #   upsert/prune helpers (mirrors store_snapshot idiom)
└── github_publish.py             # UNCHANGED

app/
├── main.py                       # EXTENDED — _ALLOWED_KINDS grows the 4 new kinds;
│                                  #   the /gallery and /reviews inline module-stub routes
│                                  #   are REMOVED (same precedent as Reminders, Phase 6)
├── routers/
│   ├── reminders.py               # UNCHANGED — precedent this phase mirrors
│   ├── gallery.py                # NEW
│   └── reviews.py                # NEW
└── templates/
    ├── gallery.html               # NEW — replaces module_stub.html for /gallery
    └── reviews.html                # NEW — replaces module_stub.html for /reviews
```

### Pattern 1: Bot-side push cache (D-01/D-02) — reuse `discord_names.py`'s SHAPE, but UPSERT not REPLACE

**What:** A `tasks.loop(seconds=45)` cog (matches `DiscordNamesCog`'s 5-minute loop
structurally, but at the D-02 "near-live" ~30-60s cadence) that scans the photo/reviews
channels, classifies every relevant message, and writes rows into a new sqlite table.

**When to use:** This is THE mechanism for D-01 (pending state cannot be read any other
way — it lives only in live Discord reaction state).

**Example (bot-side classification, reusing exported pure helpers — no duplicated logic):**
```python
# Source: cogs/gallery.py (existing, read verbatim) — _is_published is ALREADY a
# module-level pure function taking (message, entries=None); reuse it directly.
from cogs.gallery import _is_published as gallery_is_published, _image_attachments
from cogs.reviews import _is_published as reviews_is_published, _review_author_and_text

# Inside the new push-cache cog's periodic tick:
entries = await self._fetch_gallery_entries()   # _fetch_json via asyncio.to_thread, same as gallery.py's own backfill
async for message in channel.history(limit=_SCAN_LIMIT, oldest_first=False):
    if not _image_attachments(message):
        continue
    published = gallery_is_published(message, entries)
    # poster resolved HERE, from the live message — NOT from discord_names
    # (that table only ever caches channel/role names, never members).
    poster = message.author.display_name
```

**Bounded scan window — a design decision the planner must make explicitly (not left
implicit):** Unlike the one-time startup backfill (`channel.history(after=cursor,
limit=None)`), a cache-refresh tick that reruns forever cannot re-scan the ENTIRE channel
history every 30-60s once the channel has months of published photos — that is an
unbounded, ever-growing Discord REST cost. Two complementary techniques close this:
1. **Pending detection needs only a bounded recent window** (`limit=_SCAN_LIMIT`, e.g.
   200-500 messages, `oldest_first=False`) — a photo realistically sits pending for
   hours/days, not months; a bounded recent-window scan will always surface it.
2. **Published-item identity/content should come from `gallery.json`/`reviews.json`
   entries** (already fetched every tick for the `_is_published(message, entries)`
   check) — filename/caption/date/width/height are ALL already there, no per-message
   Discord fetch needed for content. Only the **poster name** requires a live message —
   and only needs to be fetched ONCE per message (see Pattern 2 below), not every tick.

### Pattern 2: Upsert-and-prune cache write (NOT wholesale replace)

**What:** Instead of `discord_names.py`'s `DELETE FROM ... ; INSERT ...` per cycle
(`replace_discord_names`), use the `store_snapshot` idiom (`upsert_store_snapshot` +
`delete_store_snapshot`) — an `INSERT ... ON CONFLICT(message_id) DO UPDATE` per row,
plus an explicit prune step for rows that dropped out of both the pending scan window
AND the published entries list (i.e., truly gone — dismissed pending or a message the
`on_raw_message_delete` handler already reconciled).

**When to use:** Any time a cached field is expensive to (re-)compute (here: the poster/
author display name, which needs a live Discord message fetch) and a wholesale replace
would force recomputing it every cycle for items that never change once published.

**Example:**
```python
# Source: core/db.py (existing idiom, read verbatim) — mirrors upsert_store_snapshot's
# shape exactly; NEW code, not yet in the codebase (write per this pattern).
def upsert_gallery_queue_row(message_id: int, state: str, poster: str, caption: str,
                             thumb_url: str, posted_at: str, message_link: str):
    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO gallery_queue
                (message_id, state, poster, caption, thumb_url, posted_at,
                 message_link, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                state=excluded.state, caption=excluded.caption,
                thumb_url=excluded.thumb_url, message_link=excluded.message_link,
                synced_at=excluded.synced_at
                -- NOTE: poster/posted_at deliberately NOT overwritten on conflict —
                -- once resolved they never change; this is what avoids the re-fetch.
        """, (message_id, state, poster, caption, thumb_url, posted_at,
              message_link, _now_iso()))
```
`thumb_url` (the Discord CDN signed URL) **DOES** need refreshing every cycle for
**pending** rows (D-02's "never a dead thumbnail" requirement) — so the `ON CONFLICT`
clause should update `thumb_url`/`state`/`caption` every cycle, but must NOT re-derive
`poster` from a fresh Discord fetch if a cached value already exists (accomplish this in
Python: only pass a fresh `poster` when the row is new, or add it to the `DO UPDATE`
list only when the caller explicitly knows the poster changed — in practice the poster of
a gallery message never changes, so simplest correct behavior is: never re-fetch a
message just to re-derive `poster`; only resolve it when first inserting a row for that
`message_id`).

### Pattern 3: Action-queue dispatch handler — pre/post 🟢-marker state check (THE central pattern)

**What:** The mechanism that makes D-11 ("no-op → quiet success, genuine failure → ✗ +
Retry") work WITHOUT modifying `cogs/gallery.py`/`cogs/reviews.py` at all.

**Why this is necessary (verified by direct read of `cogs/gallery.py` lines 153-234 and
`cogs/reviews.py` lines 301-363):** `GalleryCog._publish`/`_unpublish` and
`ReviewsCog._publish`/`_unpublish` **never raise and never return a value** on either
success OR failure. On a `GitHubPublishError`, they catch it internally, call
`self._surface_failure(message, verbo)` (adds a ⚠️ Discord reaction + a persisting
reply), and `return` — silently, from the caller's point of view. This is CORRECT for
the reaction flow (there is no return value to give a Discord reaction handler), but it
means `ActionQueueCog._run_once`'s `except Exception` branch (which is how failures reach
`action_queue.fail()`) **will never fire** for a wrapped call — every dispatch would
report `done`, even a transport failure, which is the opposite of what D-11/D-02 (Phase 5)
require.

**The fix — observe the 🟢-marker transition, not the call's return value:**
```python
# Source: NEW code in cogs/action_queue_worker.py, calling the UNCHANGED
# cogs/gallery.py helpers verbatim — no duplicated business logic (D-08).
from cogs.gallery import GalleryCog, _is_published as gallery_is_published

async def _handle_gallery_publish(self, payload: dict) -> dict:
    message_id = int(payload["message_id"])
    channel = self.bot.get_channel(config.PHOTO_CHANNEL_ID) or \
        await self.bot.fetch_channel(config.PHOTO_CHANNEL_ID)
    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        raise RuntimeError("el mensaje ya no existe · message no longer exists")

    was_published = gallery_is_published(message)          # pre-state
    gallery_cog = self.bot.get_cog("GalleryCog")
    await gallery_cog._publish(message)                     # existing logic, verbatim
    message = await channel.fetch_message(message_id)        # re-fetch: reactions changed
    is_published = gallery_is_published(message)             # post-state

    if is_published:
        return {"already": was_published}                   # committed OR moot success
    # Intended a publish; state did NOT change → genuine failure (GitHubPublishError
    # swallowed internally, OR the staff-authorship gate silently no-op'd, OR the
    # image-attachment gate found nothing publishable). Surface it to the queue.
    raise RuntimeError("no se pudo publicar · publish did not complete (see ⚠️ on the Discord message)")
```
The symmetric `_handle_gallery_remove` inverts the check (`was_published` should be
`True` going in; failure is `is_published` still `True` after the call). The SAME shape
applies verbatim to `review_publish`/`review_remove` against `ReviewsCog`'s
`_is_published`/`_publish`/`_unpublish`.

**This also correctly handles an edge case a naive "trust the call succeeded" approach
would get wrong:** if the original poster's staff role was revoked between posting and a
Manager clicking Approve, `GalleryCog._publish`'s own `_is_staff(author)` gate makes it a
silent no-op (WR-03, verified in `cogs/gallery.py` lines 162-169) — no 🟢 is added, no ⚠️
either. The pre/post check above correctly reports this as a **failure** (state did not
transition to the intended target), never a moot success, because "nothing happened and
it wasn't already-done" is exactly what should surface as ✗ + Retry.

**Registering the message id → payload shape**, the `kind` string, and wiring
`self.bot.get_cog(...)` (verified pattern: `bot.add_cog(GalleryCog(bot))` in
`cogs/gallery.py`'s `setup()` — `self.bot.get_cog("GalleryCog")` is the standard
discord.py accessor for a live cog instance from a sibling cog) are all planner-owned
details; the state-transition technique itself is the load-bearing finding.

### Anti-Patterns to Avoid
- **Calling `github_publish.publish_message`/`remove_message` (or `publish_review`/
  `remove_review`) directly from the app process or from a new bot-side helper that
  bypasses `GalleryCog._publish`/`_unpublish`.** This was explicitly flagged as the
  central hazard in prior Phase-5 research (`.planning/research/PITFALLS.md` Pitfall
  2/related notes, verified) — it duplicates the 🟢-marker check-then-commit sequence
  outside the place that owns it, reintroducing the exact double-publish race GAL-02
  exists to prevent.
- **Trusting `action_queue.complete()` gets called only on real success** without the
  pre/post state-transition check above — this is the #1 way this phase's D-11 contract
  silently breaks (see Pattern 3).
- **Wholesale-replacing the queue cache table every cycle** (`DELETE` + bulk `INSERT`,
  the `discord_names` idiom) for tables that need to remember an expensive-to-derive
  field (poster/author name) — see Pattern 2.
- **Re-deriving the poster name via the `discord_names` cache/member lookup** — that
  table has never cached member display names (verified: `cogs/discord_names.py`'s
  `_snapshot_rows` builds only `channel`/`role` rows); resolve `message.author.display_name`
  directly from the live `discord.Message` instead.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| No-double-publish idempotency | A new "is this message already queued/acted-on" DB flag | The EXISTING 🟢-marker check inside `GalleryCog._publish`/`ReviewsCog._publish` (verified, `cogs/gallery.py` line 159, `cogs/reviews.py` line 312) | It is already the single source of truth the reaction flow trusts; a second flag can drift from it (exact hazard called out in Phase-5 research) |
| App→bot durable action delivery, retry/backoff, stale-claim recovery | A new queue table/worker | The EXISTING `core/action_queue.py` + `cogs/action_queue_worker.py` (Phase 5, already shipped, already tested — `tests/test_action_queue_cog.py`) | D-08 explicitly requires reuse; the retry/backoff/stale-claim logic is already audited and load-tested (Phase-5 D-12 gate) |
| Inline per-action "Working…/✓/✗/offline" status UI | A new Alpine component/state machine | The EXISTING `actionProofApp()` state machine in `overview.html` (verified, lines 137-252) — reuse the SAME `stateKind()`/`statusCopy()` shape, resized for a card footer per UI-SPEC | Byte-identical D-09 wording/behavior is a locked requirement; reinventing risks copy/behavior drift |
| Confirm-before-destroy dialog | A new modal component | The EXISTING `.confirm-modal` shape from `reminders.html` (verified, lines 335-357) | Same `.modal-overlay`/`.modal-actions` pattern already built and CSS-styled |
| Cross-repo atomic commit (image blobs + JSON) | A new GitHub Git Data API caller | The EXISTING `core/github_publish.py::publish_message`/`remove_message`/`publish_review`/`remove_review`, called ONLY from inside the existing cog methods | Already handles ref-conflict retry, dedupe-by-id, no-op guards, and the PAT-never-logged discipline — reinventing any of this is strictly worse |
| Poster/author name resolution | A join against `discord_names` (channel/role cache) | Direct `message.author.display_name` read on the live `discord.Message`, resolved once per message id and cached (Pattern 2) | `discord_names` has never cached members (verified); there is no existing member-name cache to join against |

**Key insight:** virtually everything this phase needs already exists in this codebase.
The entire implementation surface is: (1) one new bot-side cache-push cog, (2) four new
thin `action_queue` `kind` handlers that are ~15 lines each (fetch → pre-check → call →
post-check → typed result), and (3) new but conventional FastAPI routes + Jinja templates
following `app/routers/reminders.py`'s exact shape. No new commit logic, no new
idempotency mechanism, no new retry/backoff.

## Common Pitfalls

### Pitfall 1: `_publish`/`_unpublish` swallow errors — a naive queue wrapper reports every dispatch as success
**What goes wrong:** A `kind` handler that does `await gallery_cog._publish(message); return {}` will make `action_queue.complete()` fire even when the underlying GitHub commit failed (the exception is caught and turned into a Discord ⚠️ reaction inside `_publish` itself, never propagated).
**Why it happens:** `_publish`/`_unpublish` were designed for a fire-and-forget reaction-event handler, where "surface the failure on the message" IS the UX. The `action_queue` dispatcher's success/failure signal is different: it needs an exception raised (see `cogs/action_queue_worker.py`'s `_run_once`, `except Exception as exc: ... action_queue.fail(...)`).
**How to avoid:** the pre/post 🟢-marker state-transition check (Pattern 3, above) — mandatory for all four new `kind` handlers.
**Warning signs:** a Manager clicks Approve, the panel shows "✓ Listo · Done", but the photo never appears on the live site and a ⚠️ sits on the Discord message — that is this pitfall manifesting.

### Pitfall 2: `discord_names` is NOT a member-name cache
**What goes wrong:** Assuming D-03's "poster resolved via the Phase-4 discord_names/push-cache poster field" means joining `gallery_queue.poster_id` against `discord_names` the way `app/routers/reminders.py::_render_rows` joins `channel_id`/`mention_id` against it.
**Why it happens:** `discord_names` genuinely IS the established push-cache PATTERN (D-01 says "follow the Phase-4 discord_names ... push idiom") — but the TABLE itself (verified: `cogs/discord_names.py::_snapshot_rows`) only ever writes `channel` and `role` rows from `guild.channels`/`guild.roles`. It has never iterated `guild.members`.
**How to avoid:** resolve `message.author.display_name` directly in the new gallery/reviews cache cog, at push time, and store the resolved string in the new cache table's own `poster`/`author` column — no join needed, no new member cache needed.
**Warning signs:** every gallery card in the panel shows a blank/missing poster name, or a `KeyError`/`None` where a display name was expected.

### Pitfall 3: unbounded channel history scan on every cache-refresh tick
**What goes wrong:** Reusing the FULL-history scan pattern from the one-time startup backfill (`channel.history(limit=None)`, both `cogs/gallery.py::_backfill` and `cogs/reviews.py::_backfill`) inside a cog that re-runs every 30-60s FOREVER. As the channel accumulates months of history, each tick's Discord REST cost grows unboundedly, eventually hitting rate limits or simply becoming slow.
**Why it happens:** The startup backfill's `limit=None` full scan is a ONE-TIME reconcile after downtime — a reasonable cost paid once per restart. Copy-pasting it into a recurring `tasks.loop` changes its cost profile entirely.
**How to avoid:** bound the live-scan window for PENDING detection (`limit=_SCAN_LIMIT`, recent messages only — see Pattern 1); source PUBLISHED item content from the already-fetched `gallery.json`/`reviews.json` entries (no per-item Discord fetch needed for content, only once for the poster name — see Pattern 2).
**Warning signs:** the bot's Discord REST client starts logging 429s, or the cache-refresh tick duration grows over weeks/months of production use.

### Pitfall 4: sqlite writer/writer contention as the panel adds write volume
**What goes wrong:** Multiple Managers triage-clicking Approve/Remove in a burst, overlapping with the bot's own writes (cache-refresh tick, backfill cursor, reminders scheduler tick) can surface `sqlite3.OperationalError: database is locked` if a write path skips the existing hardening.
**Why it happens:** documented and already mitigated at the infrastructure layer — `core/db.py::_get_conn()` sets `WAL` + `busy_timeout=8000` (verified), and `core/action_queue.py` wraps its write paths in `@_retry_on_locked` (verified, lines 21-37). This is Phase-5 `PITFALLS.md` Pitfall 3, already addressed by INFRA-02.
**How to avoid:** the new gallery/reviews cache write helpers (`core/db.py` additions) MUST follow the SAME `_get_conn()`/parameterized-SQL idiom as every other table in that file; if a write is expected to be higher-frequency than `discord_names`'s 5-minute cadence (it is — ~30-60s), consider applying the same `@_retry_on_locked` wrapper `action_queue.py` uses, since it is the closest-frequency precedent.
**Warning signs:** intermittent 500s or silently-swallowed exceptions on the cache-refresh tick or on an enqueue POST, correlated with concurrent Manager clicks.

### Pitfall 5: forgetting to extend `app/main.py::_ALLOWED_KINDS`
**What goes wrong:** A POST to a new enqueue route (or a POST to the existing generic `/api/actions` with the new `kind`) 422s with "unknown action kind" even though the `action_queue`/`ActionQueueCog` side is fully wired.
**Why it happens:** `_ALLOWED_KINDS = {"noop"}` (verified, `app/main.py` line 71) is a SEPARATE allowlist from `ActionQueueCog._dispatch`'s handler dict — both must be extended, and the code comment itself flags this ("Phases 6-9 extend this allowlist per module") but it is easy to update one and forget the other, especially if the planner introduces DEDICATED routes (`POST /gallery/{id}/approve`) that call `action_queue.enqueue` directly rather than going through the generic `/api/actions` endpoint (in which case `_ALLOWED_KINDS` may not even apply to the new dedicated routes — verify this at plan time and decide whether the dedicated routes should also validate against a kind allowlist for defense-in-depth).
**How to avoid:** treat `_ALLOWED_KINDS` and `ActionQueueCog._dispatch` as a matched pair; add both in the same task/commit.
**Warning signs:** enqueue succeeds via a dedicated route but the SAME kind sent through `/api/actions` (e.g. from a test or the Overview self-test pattern) 422s.

### Pitfall 6: message deleted between panel click and dispatch
**What goes wrong:** A Manager clicks Approve/Remove on a queue row that's since been deleted from Discord (another staff member deleted the message, or a race with the reaction flow's own `on_raw_message_delete` auto-unpublish). `channel.fetch_message(message_id)` raises `discord.NotFound`.
**Why it happens:** the queue action is enqueued with just a `message_id`; by the time the bot dispatches it (near-instant, ~1.5s tick, but not zero), the message may be gone.
**How to avoid:** catch `discord.NotFound` explicitly in each `kind` handler and `raise RuntimeError(...)` with a clear bilingual message so it surfaces as a genuine ✗ + Retry (Retry will correctly fail again with the same message, which is the honest outcome — the row should also be pruned from the queue cache on the NEXT cache-refresh tick since the message no longer shows up in the channel scan).
**Warning signs:** an action stuck retrying 3x then failing with a raw Python traceback string instead of a clear "message no longer exists" copy.

## Code Examples

### Extending `ActionQueueCog._dispatch` (the 4 new kinds)
```python
# Source: cogs/action_queue_worker.py (existing __init__, read verbatim) — add to the
# dict literal already there:
self._dispatch = {
    "noop": self._handle_noop,
    "gallery_publish": self._handle_gallery_publish,
    "gallery_remove": self._handle_gallery_remove,
    "review_publish": self._handle_review_publish,
    "review_remove": self._handle_review_remove,
}
```

### Reusing `discord.py`'s cross-cog accessor
```python
# Source: discord.py standard pattern (cogs/gallery.py's own setup() registers the cog
# under its class name via bot.add_cog(GalleryCog(bot)) — verified). A sibling cog
# retrieves the live instance the same way any discord.py cog resolves another:
gallery_cog = self.bot.get_cog("GalleryCog")
if gallery_cog is None:
    raise RuntimeError("GalleryCog no está cargado · GalleryCog is not loaded")
```

### New FastAPI router shape (mirrors `app/routers/reminders.py` exactly)
```python
# Source: app/routers/reminders.py (existing, read verbatim) — the established shape
# for a new dashboard module router:
from fastapi import APIRouter, Depends, HTTPException, Request
from app.deps import require_manager
from core import action_queue, db
from starlette.concurrency import run_in_threadpool

router = APIRouter()

@router.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request, roles: dict = Depends(require_manager)):
    pending = await run_in_threadpool(db.get_gallery_queue, "pending")
    published = await run_in_threadpool(db.get_gallery_queue, "published")
    return templates.TemplateResponse(request, "gallery.html", {
        "roles": roles, "active_section": "gallery",
        "pending_rows": pending, "published_rows": published, ...
    })

@router.post("/gallery/{message_id}/approve")
async def approve_gallery(message_id: int, roles: dict = Depends(require_manager)):
    action_id = await run_in_threadpool(
        action_queue.enqueue, "gallery_publish", {"message_id": message_id},
        str(roles["discord_id"]))
    return {"id": action_id}
```
`app/main.py` must then (a) `app.include_router(gallery_router.router)` /
`app.include_router(reviews_router.router)`, and (b) **remove** the existing inline
`gallery_page`/`reviews_page` `@app.get` handlers (verified at `app/main.py` lines
647-654) — otherwise FastAPI has two competing route registrations for the same path
(the router included later wins, but leaving the dead stub handler is confusing and the
`reminders_router` precedent removes the module from `_MODULE_SECTIONS`'s stub path
entirely once it has its own template).

### `open-in-Discord` link construction
```python
# CITED: Discord's documented deep-link URL shape — https://discord.com/channels/
# {guild_id}/{channel_id}/{message_id} — config.GUILD_ID is already a plain module
# constant (verified, config.py line 21), PHOTO_CHANNEL_ID/REVIEWS_CHANNEL_ID are
# tunables (settings.get shim, verified config.py lines 157-160).
message_link = f"https://discord.com/channels/{config.GUILD_ID}/{config.PHOTO_CHANNEL_ID}/{message_id}"
```

## State of the Art

Not applicable in the usual "library X moved to Y" sense — this phase touches no
external ecosystem. The one internal "old → new" shift worth naming:

| Old Approach (Phases 1-6) | New Approach (Phase 7) | When Changed | Impact |
|--------------------------|------------------------|---------------|--------|
| Bot→app cache = wholesale replace (`discord_names`) for STATIC data (channel/role lists that rarely change and are cheap to fully re-enumerate) | Bot→app cache = upsert+prune for data with an EXPENSIVE-to-derive field (poster/author name requiring a live Discord fetch) | This phase, by necessity | First cache table in this codebase that benefits from the `store_snapshot` upsert idiom instead of the `discord_names` replace idiom — worth flagging so the planner doesn't default to copy-pasting `discord_names.py` verbatim |

**Deprecated/outdated:** nothing in this codebase is deprecated by this phase; all four
existing publish/unpublish code paths are reused unchanged.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `src/data/gallery.json`/`reviews.json` are NOT confirmed to be served as public static assets at a stable URL on the deployed website (only confirmed as GitHub Contents-API-readable via the authenticated transport in `core/github_publish.py`) | Standard Stack → Alternatives Considered | If wrong (i.e. they ARE publicly served), the planner has a viable lower-cost alternative for the Published tab; if the plan is built assuming public exposure without confirming it, the Published tab could 404/fail at runtime |
| A2 | `self.bot.get_cog("GalleryCog")` / `"ReviewsCog"` are the correct string keys discord.py registers cogs under (inferred from `bot.add_cog(GalleryCog(bot))` / `bot.add_cog(ReviewsCog(bot))` in each module's `setup()`, matching discord.py's documented default of using the class name as the cog name) | Code Examples → Reusing `discord.py`'s cross-cog accessor | Low risk — this is standard, well-known discord.py behavior (class name is the default cog name unless overridden); worth a one-line runtime assertion/test rather than re-verification here |
| A3 | A ~30-60s bot-side cache-refresh tick with a bounded (e.g. 200-500 message) `channel.history()` scan will comfortably stay within Discord REST rate limits for this guild's actual gallery/reviews channel volume | Architecture Patterns → Pattern 1 | If the channel volume is far higher than assumed, the scan window/cadence may need tuning; low risk given both channels are already documented as staff-curated/low-volume in the existing cogs' own docstrings (`cogs/reviews.py`: "the reviews channel is low volume") |

**If this table is empty:** N/A — see rows above; none of these are load-bearing for the
overall architecture (all are tuning/confirmation details a planner can resolve without
blocking the plan's shape).

## Open Questions

1. **Exact `action_queue` `kind` string names and payload shape**
   - What we know: CONTEXT.md D-08 suggests `gallery_publish`/`gallery_remove`/
     `review_publish`/`review_remove` as examples, explicitly leaving exact naming to the
     planner. The payload only strictly needs `message_id` (everything else is re-derived
     from the live Discord message + `gallery.json`/`reviews.json` inside the handler).
   - What's unclear: whether the payload should also carry a `channel_id` (redundant with
     `config.PHOTO_CHANNEL_ID`/`REVIEWS_CHANNEL_ID`, which are already tunables the bot
     reads) — likely unnecessary, but worth an explicit planner decision.
   - Recommendation: use the CONTEXT.md-suggested names verbatim; payload =
     `{"message_id": <int>}` only.

2. **Whether dedicated per-module POST routes or the generic `/api/actions` endpoint should
   receive the approve/remove clicks**
   - What we know: `/api/actions` (generic, `kind`+`payload` body) already exists and is
     proven (Overview's `actionProofApp` self-test). `app/routers/reminders.py` instead
     uses fully dedicated, resource-shaped routes (`POST /reminders/{id}/pause`) that do
     NOT go through `action_queue` at all (reminders are a direct-DB CRUD module, no bot
     round-trip needed).
   - What's unclear: gallery/reviews approve/remove DO need `action_queue` (bot round-trip,
     D-08) — CONTEXT.md D-08 says routes "enqueue typed actions," implying dedicated
     routes that internally call `action_queue.enqueue`, not raw calls to `/api/actions`
     from the frontend JS.
   - Recommendation: dedicated routes (`POST /gallery/{message_id}/approve`, etc.) that
     validate the message_id against the cache (404 if not a known pending/published row)
     THEN call `action_queue.enqueue()` internally — gives the route a chance to 404 early
     on a stale/removed row rather than enqueuing a doomed action, and keeps the existing
     generic `/api/actions` endpoint reserved for the Overview self-test as originally
     scoped.

3. **Precise cache-refresh interval and scan-window size**
   - What we know: D-02 specifies "~30-60s, planner picks the exact interval" and the
     rationale (thumbnail URL freshness, near-live feel). Pitfall 3 above establishes that
     the scan window must be BOUNDED, not full-history, on every recurring tick.
   - What's unclear: the exact numeric bound (e.g. 200 vs 500 messages) that balances
     "never miss a stale pending item" against Discord REST cost — depends on actual
     gallery/reviews channel volume, which was not measured in this research pass.
   - Recommendation: start at 45s cadence (midpoint of the D-02 band, matching
     `bot_heartbeat`'s ~45s cadence already used elsewhere for consistency) with a
     `limit=300` bounded history scan; treat both as easily-tunable constants, not
     load-bearing architecture.

## Environment Availability

Skipped — this phase has no NEW external dependency (tool/service/runtime/CLI). Every
dependency (Discord gateway connection, GitHub REST API, sqlite) is already required and
already verified operational by Phases 1-6.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest` + `pytest-anyio` (verified: `tests/test_action_queue_cog.py` uses `@pytest.mark.anyio`, `tests/conftest.py` exists) |
| Config file | none found at repo root (`pytest.ini`/`pyproject.toml`/`setup.cfg` absent) — anyio backend fixture is defined per-test-file (`anyio_backend()` fixture, verified) |
| Quick run command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_gallery_cog.py tests/test_reviews_cog.py tests/test_action_queue_cog.py -x` (per user's saved environment note: use the conda python, not PowerShell's Python314, which has no pytest installed) |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| GAL-01 | Pending gallery queue is visible/populated from the cache | unit (cache-cog classification logic) + integration (route reads cache) | `pytest tests/test_gallery_reviews_cache_cog.py -x` | ❌ Wave 0 |
| GAL-02 | Approve publishes; concurrent reaction does not double-publish | unit (dispatch handler pre/post-state logic, mock `_publish`) | `pytest tests/test_action_queue_cog.py -k gallery_publish -x` | ❌ Wave 0 (extend existing file) |
| GAL-03 | Remove a published photo (🌙 parity) | unit (dispatch handler) | `pytest tests/test_action_queue_cog.py -k gallery_remove -x` | ❌ Wave 0 |
| REV-01 | Approve a pending review → publishes | unit (dispatch handler) | `pytest tests/test_action_queue_cog.py -k review_publish -x` | ❌ Wave 0 |
| REV-02 | Remove a published review | unit (dispatch handler) | `pytest tests/test_action_queue_cog.py -k review_remove -x` | ❌ Wave 0 |
| (all) | Manager-gated routes reject non-Manager, enqueue correctly | integration (FastAPI `TestClient`, mirrors `tests/test_app_reminders.py`/`tests/test_app_actions.py`) | `pytest tests/test_app_gallery.py tests/test_app_reviews.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the relevant single test file (e.g.
  `pytest tests/test_action_queue_cog.py -x`)
- **Per wave merge:** `pytest tests/test_gallery_cog.py tests/test_reviews_cog.py tests/test_action_queue_cog.py tests/test_app_gallery.py tests/test_app_reviews.py tests/test_app_actions.py -x`
- **Phase gate:** full suite (`pytest`) green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_gallery_reviews_cache_cog.py` — covers GAL-01 (pending classification,
      poster resolution, upsert-not-replace behavior) and the reviews analog
- [ ] Extend `tests/test_action_queue_cog.py` with 4 new test functions (one per `kind`)
      covering: fresh success, moot/already-done success (D-11), and genuine failure
      (message deleted / swallowed `GitHubPublishError` simulated via a monkeypatched
      `_publish`) — covers GAL-02/GAL-03/REV-01/REV-02
- [ ] `tests/test_app_gallery.py`, `tests/test_app_reviews.py` — new, mirror
      `tests/test_app_reminders.py`'s `TestClient` + `require_manager` monkeypatch shape
- [ ] Framework install: none — `pytest`/`pytest-anyio` already present and used

## Security Domain

`workflow.nyquist_validation`/`security_enforcement` are both absent from
`.planning/config.json` — treated as enabled per the default rule.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (new surfaces) | Unchanged — Discord OAuth session cookie, already covered by Phase 2/3 |
| V3 Session Management | no (new surfaces) | Unchanged — `SessionMiddleware` (signed, `https_only`, `same_site=lax`, short TTL), already covered |
| V4 Access Control | yes | `require_manager` dependency (verified, `app/deps.py`) gates every new route — owner OR Manager only, same as every other operational module |
| V5 Input Validation | yes | `message_id` path/body param MUST be validated as a positive integer before use in a sqlite query or Discord fetch; the enqueue payload allowlist (`_ALLOWED_KINDS`) is the queue-side validation gate |
| V6 Cryptography | no | Unchanged — no new secret/crypto surface this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A Manager enqueues an action for a `message_id` that does not belong to the gallery/reviews channel (IDOR-adjacent: acting on an arbitrary Discord message id) | Tampering / Elevation of Privilege | The dispatch handler MUST fetch the message from the SPECIFIC configured channel (`config.PHOTO_CHANNEL_ID`/`REVIEWS_CHANNEL_ID`) via `channel.fetch_message(message_id)`, never a bare cross-channel `bot.get_message`/global fetch — a message id from another channel will simply 404 against the wrong channel object, which is the existing, correct behavior of `channel.fetch_message` (verified: this is exactly how the live reaction handlers already scope their fetch, `cogs/gallery.py` lines 140-142) |
| SQL injection via `message_id` or cache column values | Tampering | Every new `core/db.py` write/read helper MUST use parameterized `?` placeholders exclusively — the established, audited pattern throughout `core/db.py` (verified, every existing function) |
| A crafted `kind` string reaching `ActionQueueCog._dispatch` that isn't one of the four new handlers | Tampering | Already handled generically: `_dispatch.get(row["kind"])` returning `None` raises `ValueError` inside `_run_once`'s try/except, which routes to `action_queue.fail()` (verified, `cogs/action_queue_worker.py` lines 42-44) — no new code needed, but the NEW routes must still validate `kind`/`message_id` shape before calling `enqueue` so a malformed request 422s at the API boundary rather than silently enqueuing garbage |
| Leaking an anonymous review's true author through the new cache | Information Disclosure | The push-cache cog MUST call the SAME `_review_author_and_text` seam the reviews cog already uses (verified, never bypass it) — for an anonymous review this returns `(None, text)`, and the cache write path must map `None` → the fixed `"Anónimo"` string (or store `None`/`is_anonymous=True` and let the template render the fixed label) — NEVER store `message.author.display_name` for a review the seam marked anonymous |

## Sources

### Primary (HIGH confidence — direct codebase read, this session)
- `cogs/gallery.py` (666 lines, read in full) — `_publish`/`_unpublish`/`_is_published`/
  `_is_staff`/`_image_attachments`/`_build_filename`/backfill/reconcile, editor-credit
  command (deferred, D-12)
- `cogs/reviews.py` (684 lines, read in full) — `_publish`/`_unpublish`/`_is_published`/
  `_review_author_and_text`/`_is_own_review_embed`/anonymity contract/backfill
- `core/github_publish.py` (1176 lines, read in full) — the Git Data API transport,
  `_commit_lock`, `_commit_with_retry`, `publish_message`/`remove_message`/
  `publish_review`/`remove_review`
- `core/action_queue.py` (142 lines, read in full) — `enqueue`/`claim_next`/`complete`/
  `fail`/`retry`/`recover_stale_claims`/`_retry_on_locked`
- `cogs/action_queue_worker.py` (65 lines, read in full) — `ActionQueueCog._dispatch`,
  `_run_once`, the 1.5s tick, `_handle_noop`
- `core/db.py` (798 lines, read in full) — every existing table/idiom: `discord_names`
  (replace), `store_snapshot` (upsert), `bot_heartbeat`, `jinxxy_sync_status`,
  `activity_log`, `action_queue`, `reminders`
- `cogs/discord_names.py` (75 lines, read in full) — confirms the push-cache cog is
  channel/role ONLY, never members
- `app/main.py` (1176 lines, read in full) — `_MODULE_SECTIONS`, `_ALLOWED_KINDS`,
  `/api/actions`/`/api/actions/{id}`/`/api/actions/{id}/retry`, `gallery_page`/
  `reviews_page` (to be removed), `require_manager` usage
- `app/deps.py` (186 lines, read in full) — `require_manager`/`require_owner`/
  `require_editor`/`TierForbidden`
- `app/routers/reminders.py` (461 lines, read in full) — the exact router-module
  precedent this phase's new routes should follow
- `app/templates/overview.html` (255 lines, read in full) — `actionProofApp()`, the
  exact D-09 inline-status state machine to reuse
- `app/templates/reminders.html` (655 lines, read in full) — `remindersApp()`,
  `.confirm-modal`, toast pattern
- `app/templates/module_stub.html` (16 lines, read in full) — what `/gallery`/`/reviews`
  currently render (to be replaced)
- `app/static/dashboard.css` (grepped for `.gcard`/`.tabs`/`.mod-hdr`/`.confirm-modal`/
  `.status-badge`/`--accent-gallery`/`--accent-reviews`) — confirms `.gcard`'s 12px body
  padding exception exists in the CSS variable/selector set but the `.gcard` RULE itself
  is not yet written (Phase 7 ships it, per UI-SPEC)
- `config.py` (170 lines of 200+, read) — `PHOTO_CHANNEL_ID`/`GALLERY_STAFF_ROLE_IDS`/
  `REVIEWS_CHANNEL_ID`/`REVIEWS_STAFF_ROLE_IDS`/`WEBSITE_GALLERY_JSON`/
  `WEBSITE_REVIEWS_JSON`/`WEBSITE_REPO`/`WEBSITE_BRANCH`/`DB_PATH`/`GUILD_ID`, the
  `_SAFE_TUNABLE_KEYS` settings-store shim
- `tests/test_action_queue_cog.py` (96 lines, read in full) — the exact pytest+anyio+
  monkeypatch testing idiom to follow for the new dispatch handlers
- `tests/test_gallery_cog.py` (first 90 lines, read) — the `SimpleNamespace`+`AsyncMock`
  Discord-object faking idiom
- `.planning/phases/07-gallery-reviews-approval-queues/07-CONTEXT.md` (298 lines, read in
  full) — locked decisions, canonical refs
- `.planning/phases/07-gallery-reviews-approval-queues/07-UI-SPEC.md` (301 lines, read in
  full) — approved visual/copy contract
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md` — phase requirement IDs, the
  explicitly-flagged research gap this document resolves
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-CONTEXT.md` and
  `.planning/research/PITFALLS.md` (Pitfall 2/3 sections, grepped and read in context) —
  confirms the "never call the transport directly from a second writer" and "surface
  panel state from the SAME source of truth as the reaction flow" guidance this research
  builds on directly

### Secondary (MEDIUM confidence)
- None — no WebSearch/external source was needed; this phase is entirely internal-codebase
  research.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every reused module verified by direct read
- Architecture: HIGH — the push-cache and action-queue patterns are both already shipped
  and tested in this exact codebase (Phase 4/5); the pre/post state-check technique is a
  direct, verifiable consequence of reading `_publish`/`_unpublish`'s actual control flow
- Pitfalls: HIGH for Pitfalls 1/2/4/5 (directly verified by code read); MEDIUM for
  Pitfall 3 (the unbounded-scan risk is a reasoned inference from the existing
  `channel.history(limit=None)` backfill pattern, not yet load-tested against this
  guild's actual channel volume — see Open Question 3 / Assumption A3)

**Research date:** 2026-07-23
**Valid until:** effectively indefinite for the architecture (internal, no external
dependency drift) — re-verify only if `cogs/gallery.py`/`cogs/reviews.py`/
`core/action_queue.py` change before this phase is planned/executed
