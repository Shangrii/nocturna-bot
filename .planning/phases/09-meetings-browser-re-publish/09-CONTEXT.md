# Phase 9: Meetings Browser + Re-publish - Context

**Gathered:** 2026-07-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Give meetings durable sqlite storage, a Manager-facing history browser, and the ability
to edit a meeting's summary and re-publish it by **editing the existing forum post** —
never duplicating, even on double-click/retry.

Covers requirements **MEET-01** (persist transcript + summary), **MEET-02** (Manager browses
history with transcript + summary), **MEET-03** (Manager edits a summary and re-publishes to
the forum, editing the existing post).

Today the meetings feature (`cogs/meeting.py`) records voice → transcribes (faster-whisper) →
summarizes (Ollama) → `_publish` creates a **forum thread** (summary = starter-message embed,
transcript = attached `.md`) and writes `log_activity("meeting_posted")`. **Nothing is persisted
to sqlite** — a meeting exists only as its forum post. This phase closes that gap and builds the
browse/edit/re-publish loop on top of it.

**Not in this phase:** changing how meetings are recorded/transcribed/summarized; editing the
transcript; any new capture capability.

</domain>

<decisions>
## Implementation Decisions

### Meeting record & post identity
- **D-01:** Persist a **full meeting record**: topic (`tema`), started/ended timestamps,
  participant/attendee names, written notes, full transcript, summary, and the forum
  **thread id + starter-message id**. Nothing is lost when the embed is trimmed.
- **D-02:** Tie each meeting row to its forum post via the **starter-message id** (and thread id).
  `forum.create_thread(...)` returns both the thread and its starter message — persist the
  starter-message id so re-publish edits that exact message's embed directly (no lookup, and the
  no-duplicate guarantee falls out of the stored id).
- **D-03:** Store **attendee names** (names only, no Discord ids) captured from the voice session,
  for browser display and informative activity logging.

### Re-publish idempotency & scope
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

### History browser presentation (UI hint: yes → feeds UI-SPEC)
- **D-08:** **Reverse-chronological rows** (newest first). Each row shows topic, date/time,
  attendee count, and a 1–2 line summary preview; clicking a row opens the full detail
  (transcript + editable summary). Manager-gated route, mirroring the Phase-8 `/jinxxy` panel shape.
- **D-09:** Transcript shown **collapsible inline** in the detail view (collapsed by default so the
  summary is front-and-center), plus a link to the forum `.md` for full download. Backfilled
  meetings with no stored transcript show a "transcript unavailable" state.
- **D-10:** Summary edited via an **inline textarea** with a **single "Save & re-publish" button**
  that saves to sqlite AND enqueues the deduped re-publish. Alpine state machine
  (disabled / spinner / result) mirrors the Phase-8 sync button.

### Backfill of existing forum-only meetings
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing meetings feature (the thing being extended)
- `cogs/meeting.py` — `MeetingCog`, `MeetingSession`, `_process_meeting`, and `_publish`
  (`forum.create_thread(name, embed, file)` → the thread + starter message that must be persisted
  and later edited). The forum fallback to a text channel lives here too (D-14).
- `core/summarizer.py` — `summarize(transcript)` (Ollama); produces the summary being persisted/edited.
- `core/transcription.py` — `transcribe(path)`; produces the transcript being persisted.

### Idempotent panel→bot action pattern (reuse for re-publish)
- `core/action_queue.py` — `enqueue_deduped` and the queue lifecycle (D-04).
- `cogs/action_queue_worker.py` — `ActionQueueCog._dispatch` + handler shape; add a
  `meeting_republish` dispatch kind following the Phase-8 `_handle_jinxxy_sync` analog.
- `.planning/phases/08-jinxxy-manual-sync/08-CONTEXT.md` — the dedupe / attribution / bilingual-copy /
  activity-log decisions this phase mirrors (D-04, D-07).

### Manager-gated dashboard section pattern (reuse for the browser)
- `app/routers/jinxxy.py` — Manager-gated page + status JSON + POST-enqueue router shape.
- `app/templates/jinxxy.html` + `app/static/dashboard.css` — status card + one-click button +
  Alpine state machine to mirror for the meetings browser/editor (D-08, D-10).
- `app/deps.py` — Manager gating / OAuth session (source of the editor's display name, D-07).

### Storage idioms
- `core/db.py` — `log_activity` (already called by `_publish`) and the table/migration idioms
  (new table + ADD-COLUMN) to follow for the meetings table.

_No external ADR/spec docs — requirements captured in the decisions above and in `.planning/REQUIREMENTS.md` (MEET-01/02/03)._

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/action_queue.enqueue_deduped` + `cogs/action_queue_worker.py` dispatch: the proven
  idempotent path for the re-publish button (Phase 8).
- `app/routers/jinxxy.py` / `app/templates/jinxxy.html` / `dashboard.css`: a near-complete template
  for a Manager-gated section with a status card, action button, and Alpine polling.
- `db.log_activity`: already invoked from `_publish`; reuse for re-publish attribution.

### Established Patterns
- Bilingual copy ("… · …"), Manager gating, and OAuth-display-name attribution (Phase 8 D-07/D-12).
- `core/db.py` new-table + ADD-COLUMN migration idiom (Phases 5 & 8); upsert (not INSERT OR REPLACE).

### Integration Points
- `cogs/meeting.py::_publish` — persist the meeting row here (capturing thread + starter-message ids),
  and keep the text-channel fallback persisting rows without forum ids (D-14).
- New sqlite `meetings` table in the shared DB.
- New `meeting_republish` dispatch kind in `cogs/action_queue_worker.py`.
- New Manager-gated `/meetings` router + template in `app/`.

</code_context>

<specifics>
## Specific Ideas

- Re-publish must edit the **starter message's embed** of the meeting's forum thread — the exact post,
  identified by the stored starter-message id.
- Browser detail view keeps the summary front-and-center; transcript collapsed by default with a
  "transcript unavailable" state for backfilled rows lacking a stored transcript.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. (Backfill of old forum meetings was explicitly folded
INTO scope as D-11–D-13, not deferred.)

</deferred>

---

*Phase: 9-meetings-browser-re-publish*
*Context gathered: 2026-07-29*
