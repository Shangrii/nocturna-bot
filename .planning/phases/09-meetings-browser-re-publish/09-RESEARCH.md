# Phase 9: Meetings Browser + Re-publish - Research

**Researched:** 2026-07-29
**Domain:** discord.py forum-thread editing, sqlite persistence (ADD-COLUMN idiom), FastAPI
Manager-gated CRUD panel, action-queue-based idempotent panel→bot writes
**Confidence:** HIGH (core design resolved against actual repo source + discord.py 2.5.2
installed source + Discord's official developer docs); MEDIUM on a few Discretion items
explicitly left open by CONTEXT.md

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Meeting record & post identity
- **D-01:** Persist a **full meeting record**: topic (`tema`), started/ended timestamps,
  participant/attendee names, written notes, full transcript, summary, and the forum
  **thread id + starter-message id**. Nothing is lost when the embed is trimmed.
- **D-02:** Tie each meeting row to its forum post via the **starter-message id** (and thread id).
  `forum.create_thread(...)` returns both the thread and its starter message — persist the
  starter-message id so re-publish edits that exact message's embed directly (no lookup, and the
  no-duplicate guarantee falls out of the stored id).
- **D-03:** Store **attendee names** (names only, no Discord ids) captured from the voice session,
  for browser display and informative activity logging.

#### Re-publish idempotency & scope
- **D-04:** Enforce "edit the existing post, never duplicate (even on double-click/retry)" by
  **reusing the Phase-8 action-queue pattern**: the panel enqueues a **deduped** `meeting_republish`
  action (`core/action_queue.enqueue_deduped`), the worker dispatches it once. Concurrent
  clicks/retries collapse to one job; the stored starter-message id means it always **edits**,
  never creates.
- **D-05:** On re-publish, update the **summary embed only**. The transcript `.md` attachment stays
  the **immutable** original record — editing a summary never rewrites history.
- **D-06:** In the browser editor, the **summary is editable; the transcript is read-only**.
- **D-07:** Re-publish records the **editing Manager's OAuth display name** in the activity log
  (reuse Phase-8 D-07/D-12 attribution), and edits the forum post **silently** — no new
  store/forum announcement for a summary correction.

#### History browser presentation
- **D-08:** **Reverse-chronological rows** (newest first). Each row shows topic, date/time,
  attendee count, and a 1–2 line summary preview; clicking a row opens the full detail
  (transcript + editable summary). Manager-gated route, mirroring the Phase-8 `/jinxxy` panel shape.
- **D-09:** Transcript shown **collapsible inline** in the detail view (collapsed by default so the
  summary is front-and-center), plus a link to the forum `.md` for full download. Backfilled
  meetings with no stored transcript show a "transcript unavailable" state.
- **D-10:** Summary edited via an **inline textarea** with a **single "Save & re-publish" button**
  that saves to sqlite AND enqueues the deduped re-publish. Alpine state machine
  (disabled / spinner / result) mirrors the Phase-8 sync button.

#### Backfill of existing forum-only meetings
- **D-11:** **Backfill** existing meetings-forum threads into sqlite (a one-time import), so old
  meetings become browsable and editable.
- **D-12:** **Best-effort import**: for every meetings-forum thread, take the summary from the embed
  and the thread + starter-message ids; if the `.md` is downloadable, store the transcript, else
  leave transcript null and log the gap. Maximizes coverage; gaps render as "transcript unavailable".
- **D-13:** Backfill is **idempotent** — upsert keyed on the forum **thread id**, skipping meetings
  already persisted. Safe to re-run after a partial failure.
- **D-14:** **Persist every meeting** at publish time regardless of publish target (forum success OR
  text-channel fallback). Store forum ids only when the forum post succeeded; the "Save & re-publish"
  action is **enabled only for rows that have a forum message to edit**.

### Claude's Discretion
- Exact sqlite schema/column names and migration mechanics (planner/researcher decide, following the
  `core/db.py` ADD-COLUMN / new-table idioms proven in Phases 5 & 8).
- Precise discord.py API for editing a forum thread's starter-message embed, and for walking the
  forum + downloading attachments during backfill.
- Backfill trigger mechanics (command vs guarded startup task) — must satisfy D-13 idempotency.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (Backfill of old forum meetings was explicitly folded
INTO scope as D-11–D-13, not deferred.)
</user_constraints>

## Summary

This phase adds durable sqlite storage for meetings, a Manager-facing browser/editor, and a
retry-safe "edit the existing forum post" re-publish flow. Every piece of infrastructure it
needs already exists in the repo in a directly reusable shape: the ADD-COLUMN migration idiom
(`core/db.py`), the Manager-gated router+template shape (`app/routers/jinxxy.py` +
`jinxxy.html`), and the panel→bot action queue (`core/action_queue.py` +
`cogs/action_queue_worker.py`). The one genuinely new problem — flagged in STATE.md as an
unresolved research gap — is that `action_queue.enqueue_deduped` dedupes **globally by
`kind`**, which is correct for Jinxxy's single global sync but WRONG for meetings: two
different Managers re-publishing two different meetings at the same moment would collapse
into one queued action targeting the wrong forum post. This research resolves that gap with a
minimal, backward-compatible `dedupe_key` column added to `action_queue` (Code Examples
section) — `kind` stays `"meeting_republish"` for dispatch, `dedupe_key` becomes
`f"meeting_republish:{meeting_id}"` for correct per-meeting collapsing.

The second load-bearing discord.py finding: meeting forum threads WILL be archived by the time
a Manager edits a summary days/weeks later (Discord auto-archives threads after inactivity),
and **archived threads cannot have their messages edited** by a bot without `MANAGE_THREADS`
permission first unarchiving them [CITED: docs.discord.com/developers/topics/threads]. The
republish handler must defensively unarchive → edit → restore the archived state, not assume
the thread is still active.

**Primary recommendation:** Reuse the Phase 8 action-queue/router/template shapes verbatim;
add a `dedupe_key` column to `action_queue` for correct per-entity dedup; capture
`created.message.id` (from `ForumChannel.create_thread`'s `ThreadWithMessage` return) as the
starter-message id at publish time; and always check `thread.archived` before editing in the
republish handler.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Meeting persistence (transcript/summary/forum ids) | Database (shared sqlite) | Bot process (writer) | `cogs/meeting.py::_publish` is the only writer, same as every other Phase 5-9 table (bot-writes/app-reads discipline, INFRA-01/T-03-08) |
| Meeting history browse (list + detail) | API/Backend (FastAPI) | Database (read) | Manager-gated FastAPI route reads sqlite directly (no bot round-trip needed for reads — mirrors jinxxy's `_products()`) |
| Summary edit + re-publish trigger | API/Backend (FastAPI) | Bot process (Discord write) | Panel writes the new summary to sqlite directly (fast, no Discord dependency) THEN enqueues the Discord-editing side-effect through the action queue — panel never touches Discord credentials (INFRA-01) |
| Forum post edit (starter-message embed) | Bot process (discord.py) | — | Only the bot process holds the Discord token; this is the entire reason the action queue exists |
| Backfill (walk forum, import threads) | Bot process (discord.py) | Database (write) | Requires bot-token forum/thread/attachment reads — a guarded startup task on the bot process, not a panel-triggered endpoint (mirrors `GalleryCog`'s `on_ready` backfill exactly) |
| Browser UI chrome (page, table, textarea) | Frontend Server (SSR Jinja2) | Browser (Alpine) | Server-rendered page + Alpine state machine identical to jinxxy's `jinxxySyncApp`, no client framework |

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEET-01 | Meetings (transcript+summary) persisted in shared sqlite, survive restart | New `meetings` table (Code Examples) + `_publish` write-through in `cogs/meeting.py`; backfill (D-11..D-13) covers pre-existing forum-only meetings |
| MEET-02 | Manager browses history with transcript + summary | New `app/routers/meetings.py` (list + detail routes) reusing `require_manager` + the jinxxy router/template shape |
| MEET-03 | Manager edits summary, re-publishes editing the existing post (no duplicate, even on double-click/retry) | `dedupe_key`-extended `action_queue.enqueue_deduped` (per-meeting collapsing) + stored `starter_message_id` (edit-in-place, no lookup) + archived-thread defensive unarchive/edit/restore |

## Standard Stack

No new external packages are required. Every dependency this phase touches is already pinned
and in use:

| Library | Version (installed) | Purpose | Why Standard (for this repo) |
|---------|------|---------|--------------|
| discord.py[voice] | 2.5.2 installed / 2.7.1 pinned in requirements.txt [VERIFIED: `pip index versions discord.py` + local `discord.__version__`] | Forum thread creation/editing, attachment download | Already the bot's only Discord client library |
| FastAPI + Jinja2Templates | already in `app/` | Manager-gated router + server-rendered page | Matches every other dashboard module (jinxxy/gallery/reviews/reminders) |
| Alpine.js (vendored, not CDN) | already vendored in `app/static/` | Save & re-publish state machine | Locked project-wide, no component framework (per UI-SPEC) |
| sqlite3 (stdlib) | n/a | `meetings` table, `action_queue.dedupe_key` column | Same shared-sqlite/WAL setup as every other table (`core/db.py::_get_conn`) |

**Version note (Environment Availability):** the installed venv currently has discord.py
**2.5.2**, while `requirements.txt` pins **2.7.1** [VERIFIED: `pip index versions discord.py`
shows 2.7.1 as latest; local `python -c "import discord; print(discord.__version__)"` returns
2.5.2]. Every API surface this research depends on (`ForumChannel.create_thread` →
`ThreadWithMessage`, `Thread.get_partial_message`, `Thread.edit(archived=...)`,
`Thread.fetch_message`, `ForumChannel.archived_threads`) was confirmed present and
identically-shaped on the installed 2.5.2 — so this gap does not block the phase — but the
planner should flag re-running `pip install -r requirements.txt` in the actual deployment venv
as a pre-flight check, since 2.6.x/2.7.x introduced DAVE-voice changes the repo's own
`core/dave_voice.py` docstring explicitly depends on ("discord.py 2.7+ establece la sesión
MLS"). This is a pre-existing environment drift, not something this phase's code needs to fix.

**Installation:** none — no `pip install` step needed for this phase.

## Package Legitimacy Audit

Not applicable — this phase adds zero new external packages (confirmed above; the only new
surface is a sqlite column, two DB tables' worth of new columns, and repo-internal Python
code). The Package Legitimacy Gate is skipped per its own trigger condition ("every phase that
installs external packages").

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │            Bot process (discord.py)      │
                         │                                           │
  /reunion parar ───────▶│  cogs/meeting.py::_process_meeting        │
                         │        │                                  │
                         │        ▼                                  │
                         │  transcribe (faster-whisper) + summarize   │
                         │  (Ollama)                                  │
                         │        │                                  │
                         │        ▼                                  │
                         │  _publish(): forum.create_thread(...)      │
                         │        │        → ThreadWithMessage        │
                         │        │           (thread, message)       │
                         │        ▼                                  │
                         │  db.insert_meeting(... thread_id,          │
                         │      starter_message_id ...)  ────────────┼──▶ [sqlite: meetings]
                         │                                           │
                         │  on_ready() [guarded, once]                │
                         │        │                                  │
                         │        ▼                                  │
                         │  _backfill_meetings(): walk forum.threads  │
                         │  + forum.archived_threads(limit=None)      │
                         │        │                                  │
                         │        ▼                                  │
                         │  db.insert_meeting_if_absent(thread_id,...)┼──▶ [sqlite: meetings]
                         │                                           │
                         │  ActionQueueCog._tick (1.5s loop)          │
                         │        │                                  │
                         │        ▼                                  │
                         │  _handle_meeting_republish(payload)        │
                         │        │  1. read meeting row (DB, NOT     │
                         │        │     the payload) for thread_id/   │
                         │        │     starter_message_id/summary    │
                         │        │  2. resolve thread; if archived,  │
                         │        │     unarchive                     │
                         │        │  3. partial_message.edit(embed)   │
                         │        │  4. restore archived state        │
                         │        └─────────────────────────────────┐│
                         └──────────────────────────────────────────┼┘
                                          ▲                          │
                                          │ claim/complete/fail      │ Discord REST
                                    [sqlite: action_queue]           ▼
                                          ▲                    [Discord forum thread
                                          │ enqueue_deduped     starter message — EDITED,
                                          │ (dedupe_key=         never a new post]
                                          │ "meeting_republish:{id}")
                         ┌────────────────┴──────────────────────────┐
                         │        FastAPI app (app/routers/meetings.py)│
                         │                                             │
  Manager browser ──────▶│  GET /meetings          (list, reverse-chron)
                         │  GET /meetings/{id}     (detail: transcript +
                         │                          editable summary)   │
                         │  POST /meetings/{id}/republish                │
                         │        1. UPDATE meetings SET summary=... │
                         │        2. enqueue_deduped("meeting_republish",│
                         │           {"meeting_id": id, "actor_name":..},│
                         │           dedupe_key=f"meeting_republish:{id}")│
                         │                                             │
                         │  GET /api/actions/{id}  (existing poll target)│
                         └─────────────────────────────────────────────┘
```

### Recommended Project Structure

```
app/
├── routers/
│   └── meetings.py          # NEW — list/detail/republish routes (mirrors jinxxy.py)
├── templates/
│   ├── meetings.html        # NEW — list page (table, reverse-chron, mirrors jinxxy.html)
│   └── meeting_detail.html  # NEW — detail page (transcript collapse + summary editor)
cogs/
├── meeting.py                # MODIFIED — persist on _publish; startup backfill; _republish()
└── action_queue_worker.py    # MODIFIED — new "meeting_republish" dispatch entry
core/
├── db.py                     # MODIFIED — init_meetings/insert/get/list/update; dedupe_key column
└── action_queue.py           # MODIFIED — enqueue_deduped(..., dedupe_key=None) param
```

### Pattern 1: Per-entity dedup via a composite `dedupe_key`, decoupled from dispatch `kind`

**What:** `action_queue.enqueue_deduped` currently dedupes on `kind` alone
(`core/action_queue.py` lines 50-73), which is correct ONLY because Jinxxy sync is a single
global singleton action. Meetings republish is per-entity: two Managers clicking "Save &
re-publish" on two DIFFERENT meetings at the same moment must NOT collapse into one job.

**When to use:** Any future per-entity deduped action (this is the second consumer of
`enqueue_deduped` after Jinxxy — the pattern must generalize now or every future per-entity
dedup need reinvents this).

**Example (recommended `core/action_queue.py` change — additive, backward compatible):**
```python
# Source: this repo's core/action_queue.py, generalized for per-entity dedup.
@_retry_on_locked
def enqueue_deduped(kind: str, payload: dict, requested_by: str,
                     dedupe_key: str | None = None) -> int:
    """D-04 dedupe-at-enqueue. ``dedupe_key`` defaults to ``kind`` (unchanged behavior for
    jinxxy_sync's single global singleton). Pass an entity-scoped key (e.g.
    f"meeting_republish:{meeting_id}") so two DIFFERENT entities' actions never collapse
    into one job while two clicks on the SAME entity still collapse correctly."""
    key = dedupe_key or kind
    with db._get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM action_queue WHERE dedupe_key = ? "
            "AND status IN ('pending', 'claimed') ORDER BY id LIMIT 1",
            (key,),
        ).fetchone()
        if existing is not None:
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO action_queue "
            "(kind, payload_json, status, requested_by, requested_at, dedupe_key) "
            "VALUES (?, ?, 'pending', ?, ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso(), key),
        )
        return cur.lastrowid
```
`init_action_queue()` gets one more ADD-COLUMN line (`dedupe_key TEXT`), following the exact
idiom already used for `jinxxy_sync_status`'s seven bolted-on columns. The existing
`db.py::init_action_queue` `CREATE INDEX IF NOT EXISTS idx_action_queue_status` should get a
sibling `idx_action_queue_dedupe_key` index since every dedupe check filters on it. The
existing Jinxxy caller (`app/routers/jinxxy.py::trigger_jinxxy_sync`) needs ZERO changes — it
keeps calling `enqueue_deduped("jinxxy_sync", {...}, requested_by)` with no `dedupe_key`,
defaulting to the same global-by-kind behavior it has today.

### Pattern 2: `kind` for dispatch, `dedupe_key` for collapsing — never conflate them

**What:** `cogs/action_queue_worker.py::_run_once` dispatches on `row["kind"]` via
`self._dispatch.get(row["kind"])` (a plain dict lookup). Keep `kind = "meeting_republish"`
literal (not `f"meeting_republish:{id}"`) so this dict lookup keeps working unmodified — only
`dedupe_key` carries the per-meeting identity.

**Anti-pattern to avoid:** Encoding the meeting id INTO `kind` (e.g. `"meeting_republish:42"`)
to get per-entity dedup "for free" off the existing kind-only dedupe. This breaks the
dispatch dict lookup (`self._dispatch.get("meeting_republish:42")` → `None` → `ValueError:
unknown action kind`) unless the worker's dispatch resolution is ALSO changed to strip a
suffix — a second, uglier, more error-prone code path than adding one column.

### Pattern 3: Read the mutation target from the DB row, never trust the queue payload for it

**What:** The `meeting_republish` payload should carry only `{"meeting_id": ..., "actor_name":
...}` — the handler reads `thread_id`/`starter_message_id`/`summary`/`tema`/`notes` fresh from
the `meetings` table by `meeting_id`, never from the payload. This mirrors the repo's existing
IDOR discipline (`app/deps.py::require_editor` — identity always re-read from session, never
trusted from the request body) applied to the queue boundary: a stale or tampered payload can
never redirect an edit at an arbitrary message id.

### Pattern 4: Archived-thread defensive edit (unarchive → edit → restore)

**What:** [CITED: docs.discord.com/developers/topics/threads] "Users cannot edit messages...
in archived threads" — the exception is a caller with `MANAGE_THREADS` permission, which the
bot's role may or may not have been granted on the meetings forum. Meeting threads WILL become
archived between the meeting and a later summary correction (Discord's default
`auto_archive_duration` is far shorter than a plausible "Manager corrects the acta a week
later" gap, and `cogs/meeting.py::_publish` does not currently pass `auto_archive_duration=` to
`create_thread`, so the guild/channel default applies).

**Example:**
```python
# Source: derived from discord.py 2.5.2 installed Thread.edit signature
# (archived: bool, ...) and docs.discord.com/developers/topics/threads.
async def _republish_meeting_embed(thread: discord.Thread, starter_message_id: int,
                                    embed: discord.Embed):
    was_archived = thread.archived
    if was_archived:
        await thread.edit(archived=False)   # requires Manage Threads on the bot's role
    try:
        partial = thread.get_partial_message(starter_message_id)
        await partial.edit(embed=embed)
    finally:
        if was_archived:
            await thread.edit(archived=True)  # restore visible state (D-07: silent edit)
```
If the bot's role lacks `Manage Threads`, the first `thread.edit(archived=False)` raises
`discord.Forbidden` — this surfaces as a normal action-queue `fail()` → retry/failed-status
flow (identical UX to a Jinxxy sync failure), which is an acceptable fallback but worth a
one-time manual permission check on the live server (see Open Questions).

### Pattern 5: Capture `ThreadWithMessage.message`, not just `.thread`

**What:** `ForumChannel.create_thread(...)` returns a `ThreadWithMessage` namedtuple
`(thread, message)` [VERIFIED: discord.py 2.5.2 installed source,
`inspect.signature(discord.ForumChannel.create_thread)` return annotation]. The CURRENT
`cogs/meeting.py::_publish` only keeps `created.thread` (line 278: `created =
await forum.create_thread(...)`) — it discards `created.message`. Since the thread's id and
its starter message's id are the SAME snowflake for both message-threads and forum-created
threads [CITED: `discord.Thread.starter_message` docstring, "the thread starter message ID is
the same ID as the thread"], `starter_message_id` could technically be read as
`created.thread.id` with no need for `created.message` at all — but CONTEXT.md D-02
explicitly directs "persist the starter-message id ... no lookup", so store BOTH
`created.thread.id` (thread_id) and `created.message.id` (starter_message_id) even though they
are provably identical today — this is intentionally redundant against a future Discord API
change and matches the literal decision text, at zero extra cost.

### Pattern 6: Guarded one-time startup backfill (reuse `GalleryCog`'s exact idiom)

**What:** `cogs/gallery.py::on_ready` (lines 362-371) is a byte-for-byte precedent for D-11's
backfill trigger discretion: `self._backfilled = False` in `__init__`, flip-and-guard in
`on_ready` (which "can re-fire on reconnects"), delegate to a `try/except`-wrapped
`_backfill()` that logs and swallows any exception so a broken backfill never crashes the bot.

**Recommendation (resolves the Claude's Discretion "command vs guarded startup task"):** reuse
this exact idiom for `MeetingCog` rather than adding a slash command or a panel button. It
satisfies D-13's idempotency requirement trivially (guard + upsert-by-`thread_id` make re-runs
safe), needs no new UI surface (UI-SPEC explicitly permits this: "a one-time startup-guarded
import with no button is equally valid per D-13"), and needs no new action-queue kind. A panel
button remains a valid Claude's-Discretion alternative if a manual re-trigger becomes wanted
later, but is not required to satisfy any decision in CONTEXT.md.

```python
# Source: pattern lifted directly from cogs/gallery.py::on_ready / _backfill (D-20 idiom).
@commands.Cog.listener()
async def on_ready(self):
    if self._backfilled:
        return
    self._backfilled = True
    try:
        await self._backfill_meetings()
    except Exception:
        log.exception("meeting startup backfill failed")
```

### Anti-Patterns to Avoid

- **SQLite `ON CONFLICT(thread_id) DO NOTHING` against a partial unique index:** a partial
  unique index (`WHERE thread_id IS NOT NULL`) as an `ON CONFLICT` target requires the
  `ON CONFLICT` clause's own `WHERE` predicate to match the index's predicate exactly, or
  SQLite raises "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint".
  Simpler and equally safe for a bot-process-only, guarded, single-run backfill: an explicit
  `SELECT id FROM meetings WHERE thread_id = ?` existence check before `INSERT`, with no
  index-conflict cleverness. This is a one-time startup task on a single bot process — there
  is no concurrent-writer race to defend against here (unlike the high-frequency
  `action_queue` writes that `core/db.py`'s `_retry_on_locked` guards).
- **Regenerating the embed title/notes from "now" on re-publish:** the embed rebuild for
  re-publish MUST reuse the ORIGINAL `tema` + `started_at` (stored at publish time) and the
  ORIGINAL notes — only the summary/description field changes. Recomputing "now" as the
  displayed date on edit would silently rewrite the meeting's identity every time a Manager
  fixes a typo.
- **Skipping the 4096/1024-char truncation on rebuild:** the live `_publish` truncates
  `summary[:4096]` (embed description limit) and the notes field to `[:1024]` (embed field
  value limit). The republish rebuild MUST apply the identical truncation, or a longer edited
  summary will make Discord's edit API reject the PATCH outright (400).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Panel→bot idempotent write | A custom lock/mutex or a bespoke "already editing" flag on the meeting row | `action_queue.enqueue_deduped` (extended with `dedupe_key`, Pattern 1) | Already proven correct under concurrency (Phase 8's `test_action_queue_dedupe.py`), including the claimed-row and post-completion re-enqueue edge cases |
| Retry-safe forum edit | A new lookup-the-post-by-content-match fallback | The stored `thread_id`+`starter_message_id` (D-02) | Eliminates an entire class of "which message was it?" bugs; the id pair is the whole point of persisting it |
| Manager-gated route auth | A new permission check per route | `Depends(require_manager)` (`app/deps.py`) | Already the single choke point every other operational module uses; re-deriving auth per-route is how ACCESS-02 regressions happen |
| Action status polling UI | A new polling/state-machine pattern | Copy `jinxxySyncApp`'s Alpine shape (`jinxxy.html`) almost verbatim | UI-SPEC explicitly mandates matching this shape byte-for-byte for consistency across dashboard modules |

**Key insight:** every piece of this phase's "hard problem" (idempotent panel-triggered Discord
writes) already has a working, tested reference implementation one file away
(`cogs/jinxxy.py` + `action_queue_worker.py::_handle_jinxxy_sync`). The only genuinely new
engineering is recognizing that Jinxxy's dedup was accidentally singleton-shaped and
generalizing it — not building a new mechanism from scratch.

## Common Pitfalls

### Pitfall 1: Global-by-`kind` dedupe silently misroutes concurrent per-entity actions
**What goes wrong:** Manager A clicks "Save & re-publish" on meeting #12; within the same
1.5s dispatch tick, Manager B clicks it on meeting #47. With the CURRENT (kind-only)
`enqueue_deduped`, B's click returns A's already-queued action id — meeting #47's summary
never gets its forum post edited, and the panel shows B's request as "done" (it silently
attached to A's unrelated job).
**Why it happens:** `enqueue_deduped`'s `WHERE kind = ?` was written for Jinxxy's single
global sync, where "there can only be one" is actually true. Reusing it verbatim for a
per-entity action inherits that assumption incorrectly.
**How to avoid:** Pattern 1's `dedupe_key` column, keyed `f"meeting_republish:{meeting_id}"`.
**Warning signs:** any test that only exercises ONE meeting id would pass even with the
broken kind-only version — the regression test MUST enqueue two DIFFERENT meeting ids and
assert they get DIFFERENT action ids (mirrors none of the existing `test_action_queue_dedupe.py`
cases, all of which use one fixed kind with no entity dimension — this is a genuinely new test
shape for the suite).

### Pitfall 2: Editing an archived thread's starter message without unarchiving first
**What goes wrong:** `discord.Forbidden` (403) raised from `PartialMessage.edit(...)` on an
archived thread, surfacing as an opaque queue failure with no obvious cause unless the log
message explicitly calls out "archived".
**Why it happens:** meeting threads are typically edited long after the meeting (that's the
whole point of MEET-03), by which time Discord has auto-archived them.
**How to avoid:** Pattern 4 (check `thread.archived`, unarchive, edit, restore).
**Warning signs:** re-publish works in manual testing IMMEDIATELY after recording a test
meeting (thread still active) but fails days later in production — a classic "worked in dev,
broke in prod" timing bug if this isn't handled from the start.

### Pitfall 3: Notes/title get regenerated instead of reused on rebuild
See Anti-Patterns above — flagged again here because it is the easiest one-line coding
mistake (a caller who builds the embed with `datetime.now()` instead of the stored
`started_at`).

### Pitfall 4: `/meetings` route conflict between the existing stub and the new router
**What goes wrong:** `app/main.py` (lines 645-647, CURRENT state) already defines
`@app.get("/meetings")` → `_module_stub_page(request, "meetings", roles)` rendering
`module_stub.html`. If the planner adds a NEW `app/routers/meetings.py` with its own
`GET /meetings` and includes it via `app.include_router(...)` WITHOUT deleting the existing
stub function, both routes exist in `app.routes` for the identical path.
**Why it happens:** Phase 8 (Jinxxy) established the "replace the stub" pattern but the
`meetings` stub route (and its `_MODULE_SECTIONS["meetings"]` dict entry) was never removed
because Phase 9 hadn't shipped yet — this phase IS the one that must remove it.
**How to avoid:** delete the `@app.get("/meetings")` function (lines 645-647) and
`app.include_router(meetings_router.router)` alongside the other four router includes
(lines 331-334). `_MODULE_SECTIONS["meetings"]` becomes dead (same as the already-dead
`"gallery"`/`"reviews"`/`"reminders"`/`"jinxxy"` entries in that same dict — confirmed
[VERIFIED: grep of `app/main.py` shows `_module_stub_page` has exactly one remaining caller,
the `/meetings` stub] — leaving it is harmless but is pre-existing dead-code debt, not a
regression this phase introduces).
**Warning signs:** if registration ORDER is gotten backwards (stub decorator executes before
`include_router`), Starlette's first-match-wins routing means the STUB route wins and the new
router's `/meetings` page silently never renders — a confusing "I wrote the code but the old
stub still shows" bug.

### Pitfall 5: Attendee names captured too early or too late
**What goes wrong:** `session.recorder.users` (used today for transcription) only contains
users whose audio the recorder actually started a track for — someone who joined and never
spoke may be entirely absent from it, undercounting attendees (D-03/UI-SPEC "N attendee(s)").
**Why it happens:** `DaveVoiceRecorder.users` is populated lazily on first audio frame per
user (see `core/dave_voice.py`), not eagerly from channel membership.
**How to avoid:** snapshot `[m.display_name for m in session.voice_channel.members if not
m.bot]` at teardown time (before `vc.disconnect()`), unioned with any names already in
`session.recorder.users` (covers someone who spoke then left before `/reunion parar`). Either
source alone under-counts a real edge case; capturing both and de-duplicating by name is the
robust choice.

### Pitfall 6: Backfilled meetings and the "no forum post to edit" contract
**What goes wrong:** D-14 requires the Save & re-publish button to be absent entirely (not
merely disabled) for rows with no forum message to edit. A backfilled row whose original
thread was later manually deleted from Discord (rare but possible) still has a stored
`thread_id`/`starter_message_id` in sqlite even though the underlying Discord message is gone
— the button would render (ids are non-null) but the actual edit would 404 at dispatch time.
**Why it happens:** "has ids stored" and "the Discord message still exists" are different
facts; only the former is knowable without a live API call at render time.
**How to avoid:** this is an acceptable, narrow edge case — surface it via the existing
`discord.NotFound` → action-queue `fail()` path (same as `_handle_gallery_publish`'s
`_fetch_message` helper, which already converts `NotFound` into a clean bilingual "message no
longer exists" error). Do NOT attempt a live existence check on every page render just to
decide whether to show the button — that would add a Discord API round-trip to every list-page
view for a rare edge case the failure path already handles gracefully.

## Code Examples

### Meetings table schema (new `core/db.py` function, follows the `init_gallery_state`/
`init_reminders` ADD-COLUMN idiom)
```python
# Source: this repo's core/db.py idiom (CREATE TABLE IF NOT EXISTS + defensive ALTER loop).
def init_meetings():
    """Create the durable meetings table if it doesn't exist (MEET-01).

    thread_id/starter_message_id are NULLable — D-14 persists every meeting regardless of
    forum success, storing forum ids ONLY when the forum post succeeded. The cog calls this
    in its __init__ (same pattern as init_gallery_state), NOT init_db().
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meetings (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                tema               TEXT    NOT NULL DEFAULT '',
                started_at         TEXT    NOT NULL,   -- ISO 8601 UTC
                ended_at           TEXT,
                attendees_json     TEXT    NOT NULL DEFAULT '[]',
                notes_json         TEXT    NOT NULL DEFAULT '[]',
                transcript         TEXT,                -- NULL = unavailable (D-12 gap)
                summary            TEXT    NOT NULL DEFAULT '',
                thread_id          INTEGER,              -- NULL = text-channel fallback (D-14)
                starter_message_id INTEGER,
                created_at         TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meetings_thread_id ON meetings(thread_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_meetings_started_at ON meetings(started_at)"
        )


def insert_meeting(tema, started_at, ended_at, attendees, notes, transcript, summary,
                    thread_id=None, starter_message_id=None) -> int:
    """Insert one meeting row (live publish path). Always a NEW row — never upserts."""
    with _get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO meetings
                (tema, started_at, ended_at, attendees_json, notes_json,
                 transcript, summary, thread_id, starter_message_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tema, started_at, ended_at, json.dumps(attendees), json.dumps(notes),
              transcript, summary, thread_id, starter_message_id,
              datetime.now(timezone.utc).isoformat()))
        return cur.lastrowid


def get_meeting_by_thread_id(thread_id: int) -> sqlite3.Row | None:
    """Existence check for the backfill's idempotent import (D-13) — plain SELECT, not an
    ON CONFLICT target (see RESEARCH.md Anti-Patterns re: partial-index conflict targets)."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT id FROM meetings WHERE thread_id = ?", (thread_id,)
        ).fetchone()
```

### Dispatch handler (new entry in `cogs/action_queue_worker.py`)
```python
# Source: mirrors _handle_jinxxy_sync's delegate-to-cog shape exactly.
async def _handle_meeting_republish(self, payload: dict) -> dict:
    meeting_id = int(payload["meeting_id"])
    meeting_cog = self.bot.get_cog("Meeting")   # name="Meeting" GroupCog kwarg, not class name
    if meeting_cog is None:
        raise RuntimeError("MeetingCog no está cargado · MeetingCog is not loaded")
    return await meeting_cog._republish(meeting_id)
```
And in `__init__`'s `self._dispatch` dict: `"meeting_republish": self._handle_meeting_republish,`.

### Router POST (new `app/routers/meetings.py`, mirrors `jinxxy.py::trigger_jinxxy_sync`)
```python
@router.post("/meetings/{meeting_id}/republish")
async def republish_meeting(meeting_id: int, request: Request,
                             roles: dict = Depends(require_manager)):
    body = await request.json()
    new_summary = (body.get("summary") or "").strip()
    await run_in_threadpool(db.update_meeting_summary, meeting_id, new_summary)
    actor_name = roles.get("username") or str(roles["discord_id"])
    action_id = await run_in_threadpool(
        action_queue.enqueue_deduped,
        "meeting_republish",
        {"meeting_id": meeting_id, "actor_name": actor_name},
        str(roles["discord_id"]),
        dedupe_key=f"meeting_republish:{meeting_id}",
    )
    return JSONResponse({"id": action_id})
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| n/a — greenfield persistence for this feature | n/a | n/a | This phase has no prior "old approach" to migrate away from; it's adding a first-time durable layer under an existing feature |

**Deprecated/outdated:** none identified — discord.py's `ForumChannel.create_thread` /
`Thread.get_partial_message` / `Thread.edit(archived=...)` APIs used here are the current,
non-deprecated surface on both the installed 2.5.2 and the pinned 2.7.1.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Meeting forum threads use Discord's default `auto_archive_duration` (not explicitly set in `create_thread` today) and will plausibly be archived by the time a Manager corrects a summary | Pattern 4 / Pitfall 2 | Low — the defensive unarchive/edit/restore code is a no-op cost if the thread happens to still be active, so this assumption being wrong doesn't break anything, it just means Pattern 4's code path is exercised less often than expected |
| A2 | The bot's Discord role may or may not currently hold `MANAGE_THREADS` on the meetings forum channel | Pattern 4 | If the role lacks it, unarchive fails with `Forbidden` and re-publish always fails for archived threads until a server admin grants the permission — this is a one-time, out-of-band Discord server config check, not something the code can self-heal |
| A3 | `session.recorder.users` under-counts attendees who never spoke; snapshotting `voice_channel.members` at teardown is the better source | Pitfall 5 | Low — attendee count is a display nicety (UI-SPEC "N attendee(s)"), not load-bearing for MEET-01/02/03's pass/fail criteria |

**If this table is empty:** N/A — see entries above.

## Open Questions (RESOLVED)

1. **Does the bot's Discord role currently hold `MANAGE_THREADS` on the meetings forum
   channel?**
   - **RESOLVED: deferred to human-verify** — adopted as a `checkpoint:human-verify` step in plan 09-05 (Task 2, step 1). Code degrades gracefully either way.
   - What we know: the code can create forum threads (requires "Create Posts"/"Send Messages"
     in a forum channel), which is a DIFFERENT permission than `MANAGE_THREADS`.
   - What's unclear: whether the bot's existing role grant on the live Discord server already
     includes `MANAGE_THREADS` (this research has no access to the live server's permission
     overwrites).
   - Recommendation: the planner should add a `checkpoint:human-verify` task instructing the
     owner to confirm (or grant) `MANAGE_THREADS` for the bot's role on the meetings forum
     channel as part of phase verification — the code's defensive unarchive path degrades
     gracefully (clean, logged failure) either way, so this is a "verify, don't block" item.

2. **Exact attendee-capture snapshot point.**
   - What we know: `session.voice_channel.members` is available up until
     `session.vc.disconnect()` in `_teardown`.
   - What's unclear: whether to snapshot in `parar()` (before teardown) or inside `_teardown`
     itself — both work; CONTEXT.md leaves this to Claude's Discretion.
   - Recommendation: snapshot at the START of `_teardown` (before `stop_listening()`/
     `disconnect()`), unioned with `recorder.users` names, as covered in Pitfall 5.
   - **RESOLVED: recommendation adopted** — implemented verbatim in plan 09-03 (Task 2).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py | Forum thread create/edit, attachment download | ✓ | 2.5.2 installed (2.7.1 pinned in requirements.txt) | Re-sync venv to 2.7.1 before deploy if DAVE-voice features are exercised; not required for this phase's API surface |
| sqlite3 (stdlib) | `meetings` table, `action_queue.dedupe_key` | ✓ | stdlib, matches every other table | — |
| Ollama | Summary generation (unchanged, pre-existing dependency of `_process_meeting`) | not probed (out of scope — this phase does not change summarization) | — | Existing `core/summarizer.py` already degrades to an inline warning message if Ollama is down; unaffected by this phase |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:** discord.py version drift (2.5.2 vs. pinned 2.7.1) —
every API this phase needs is present on both; treat as a pre-existing deploy hygiene item, not
a phase blocker.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (no dedicated `pytest.ini`/`pyproject.toml` `[tool.pytest]` section found — `tests/conftest.py` only adds the repo root to `sys.path`) |
| Config file | none — see Wave 0 |
| Quick run command | `python -m pytest tests/test_db_meetings.py tests/test_action_queue_dedupe.py -x` (use the conda interpreter per project convention: `C:\Users\Shangri\miniconda3\python.exe -m pytest ...`, NOT PowerShell's `Python314`) |
| Full suite command | `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEET-01 | `insert_meeting`/`get_meeting`/`list_meetings` round-trip survives a fresh connection (persistence) | unit | `pytest tests/test_db_meetings.py -x` | ❌ Wave 0 |
| MEET-01 | `_publish` writes a meetings row on BOTH the forum-success path and the text-channel-fallback path (D-14) | unit (cog, mocked discord objects) | `pytest tests/test_meeting_cog.py -x` | ❌ Wave 0 |
| MEET-02 | `GET /meetings` renders reverse-chronological rows; `GET /meetings/{id}` renders transcript + summary, 404 on unknown id | integration (FastAPI TestClient, mirrors `test_app_jinxxy.py`) | `pytest tests/test_app_meetings.py -x` | ❌ Wave 0 |
| MEET-03 | Two enqueue_deduped calls for the SAME meeting id collapse to one action; two calls for DIFFERENT meeting ids do NOT collapse | unit | `pytest tests/test_action_queue_dedupe.py -x` (extend existing file) | Existing file, new cases needed |
| MEET-03 | `_handle_meeting_republish` resolves the cog, calls `_republish`, and maps a `discord.Forbidden`/`NotFound` to a clean queue failure | unit (mocked bot/cog, mirrors `test_action_queue_cog.py`'s `_DISPATCH_CASES` shape) | `pytest tests/test_action_queue_cog.py -x` (extend existing file) | Existing file, new case needed |
| MEET-03 | Re-publish on an ARCHIVED thread unarchives, edits, and restores archived state | unit (mocked `discord.Thread`) | `pytest tests/test_meeting_cog.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the quick-run command above (targeted new/changed test files)
- **Per wave merge:** full suite command
- **Phase gate:** full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_db_meetings.py` — covers MEET-01 (new file, no existing precedent for
  meeting-table CRUD)
- [ ] `tests/test_meeting_cog.py` — covers MEET-01 (`_publish` persistence) and MEET-03
  (archived-thread republish) — **no test file for `cogs/meeting.py` exists at all today**,
  this is a genuine coverage gap predating this phase
- [ ] `tests/test_app_meetings.py` — covers MEET-02 (new file, follow `test_app_jinxxy.py`'s
  `_configure_app`/`_manager_override`/`client` fixture shape verbatim)
- [ ] Extend `tests/test_action_queue_dedupe.py` — add a per-entity (`dedupe_key`) case; every
  existing case in that file only exercises the kind-only path and would NOT catch Pitfall 1
  as written today
- [ ] Extend `tests/test_action_queue_cog.py` — add a `meeting_republish` case to the existing
  `_DISPATCH_CASES` parametrized table shape (lines 40-70)
- Framework install: none — pytest is already the project's test runner, no new install needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (new surface) | Reuses existing OAuth session (`app/deps.py`), unchanged by this phase |
| V3 Session Management | no (new surface) | Same signed session cookie, unchanged |
| V4 Access Control | yes | `Depends(require_manager)` on every new route — owner OR Manager only, same as every other operational module (ACCESS-02) |
| V5 Input Validation | yes | Summary text: strip + reasonable length cap before the embed-truncation logic (Discord's own 4096/1024 hard limits are the real backstop, but rejecting a pathologically huge POST body before it reaches sqlite is good hygiene, mirroring `save_editor`'s `ValidationError` handling) |
| V6 Cryptography | no | No new secrets/crypto surface introduced |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR via a client-supplied `meeting_id` targeting another meeting's forum post | Tampering | Already structurally impossible here: the republish payload only ever carries the `meeting_id` the Manager is editing; the FORUM TARGET (thread_id/starter_message_id) is always re-read from the `meetings` table server-side (Pattern 3), never trusted from the payload |
| Reflected/stored XSS via a malicious summary containing `<script>` | Tampering/Info Disclosure | Jinja2's autoescaping (already the project default — no `\| safe` filter is used anywhere in the reviewed templates) neutralizes this on render; no new escaping logic needed |
| Double-submit race on "Save & re-publish" (double-click, or a client retry after a dropped response) | Repudiation/DoS-adjacent | `dedupe_key`-scoped `enqueue_deduped` collapses concurrent duplicate submissions to one job (the entire point of Pattern 1) |

## Sources

### Primary (HIGH confidence)
- Local repo source: `cogs/meeting.py`, `core/action_queue.py`, `cogs/action_queue_worker.py`,
  `core/db.py`, `cogs/gallery.py`, `app/routers/jinxxy.py`, `app/templates/jinxxy.html`,
  `app/deps.py`, `app/main.py`, `core/summarizer.py`, `core/dave_voice.py`,
  `tests/test_action_queue_dedupe.py`, `tests/test_action_queue_cog.py`,
  `tests/test_app_jinxxy.py`, `tests/conftest.py`
- discord.py 2.5.2 (installed venv) introspected directly via `inspect.signature` /
  `inspect.getsource` — `ForumChannel.create_thread`, `Thread.get_partial_message`,
  `Thread.fetch_message`, `Thread.edit`, `Thread.starter_message`,
  `ForumChannel.archived_threads`
- `.planning/phases/09-meetings-browser-re-publish/09-CONTEXT.md`,
  `09-UI-SPEC.md`, `09-DISCUSSION-LOG.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`

### Secondary (MEDIUM confidence)
- [docs.discord.com/developers/topics/threads](https://docs.discord.com/developers/topics/threads)
  — archived-thread message-edit restriction and the `MANAGE_THREADS` exception (fetched via
  WebFetch, official Discord developer docs, redirected from discord.com/developers/docs)

### Tertiary (LOW confidence)
- General WebSearch results on `ThreadWithMessage`/thread-id-equals-starter-message-id (used
  only to form the initial hypothesis; CONFIRMED against the installed discord.py source and
  the official docs above before being stated as fact in this document)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every existing dependency's relevant API was
  introspected directly against the installed library
- Architecture: HIGH — the dedupe-key gap and archived-thread edit pitfall were both derived
  from direct code/API inspection, not inference
- Pitfalls: HIGH for Pitfalls 1/2/4 (source-verified); MEDIUM for Pitfall 5/6 (reasonable
  design judgment, not independently verified against a live Discord server)

**Research date:** 2026-07-29
**Valid until:** 2026-08-28 (30 days — stable domain; discord.py API surface used here has not
changed across the 2.5.x-2.7.x range per the version-drift check above)
