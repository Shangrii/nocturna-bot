# Phase 6: Reminders CRUD - Context

**Gathered:** 2026-07-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Bring the **reminder lifecycle** — currently manageable **only** through the
Discord `/recordatorio` slash-command group (`cogs/reminders.py`) — into the
**staff dashboard** as a **table + modal** CRUD surface, add **pause/resume**,
and add a **scheduler-race guard** so a panel edit or delete never fires stale
data and is never clobbered by the bot's write-back (REM-01, REM-02, REM-03).

**Pure DB CRUD — bypasses the `action_queue`** (locked in Phase 5 / ARCHITECTURE.md):
the FastAPI app writes the `reminders` table directly and the bot's 1-minute
scheduler reads at-use. No bot round-trip, no queue.

**⚠ SCOPE EXPANSION (owner decision, 2026-07-23):** This phase now **also adds a
new `biweekly` frequency to the reminder engine** (see D-05/D-06). That reaches
past the original roadmap boundary ("panel CRUD + pause/resume + race guard")
into `cogs/reminders.py`'s schedule engine **and** the Discord `/recordatorio`
command (parity). ROADMAP.md / REQUIREMENTS.md should be updated to reflect the
wider scope (candidate new requirement, e.g. REM-04: biweekly recurrence).

</domain>

<decisions>
## Implementation Decisions

### Pause / resume semantics (REM-02) — new `paused` column
- **D-01: Clean resume — next future occurrence.** Resuming a recurring reminder
  recomputes `next_fire_utc` **forward** from now to the next scheduled slot.
  Nothing fires for the paused window (no backfill). Rationale: pause means "stop
  bugging us"; a resume must never dump a stale weekly — and the existing
  catch-up grace is only hours, so a multi-occurrence miss would `skip` anyway.
- **D-02: Overdue one-off fires once on resume.** A one-off whose date passed
  while paused, when resumed, **fires once immediately marked ⏰ atrasado, then is
  deleted** (its normal one-off lifecycle). The message still matters — the owner
  explicitly chose to resume it. (Note: this intentionally differs from D-01's
  "no stale dump" for recurring — a one-off is a specific deferred message the
  Manager still wants delivered.)
- **D-03: Pause suppression is best-effort.** The scheduler's due-query excludes
  paused rows (`WHERE paused = 0`). If Pause commits before the tick reads the
  row, that occurrence is suppressed; if the tick already fetched it, it may fire
  once — the **same accepted one-tick race as delete** (Pitfall 7). No stale fire.
- **D-04: Editing a paused reminder keeps it paused.** Edit and pause are
  orthogonal concerns; the Manager resumes explicitly when ready. (Rejected:
  edit-auto-resumes, ask-on-save.)

### Biweekly frequency (SCOPE EXPANSION — new engine capability)
- **D-05: `biweekly` is a 4th frequency**, added to both the panel modal and the
  Discord `/recordatorio crear`/`editar` choices (full parity). Requires: new
  schedule-math (`next_biweekly_fire`), validation, `schedule_summary` handling
  (e.g. "Cada 2 semanas · <día> HH:MM"), and the frequency choice list wherever
  the other three appear.
- **D-06: Anchored on a chosen start date.** The Manager picks a first-fire date
  (+ time) at creation; the reminder then fires **every 14 days from that anchor**
  (`anchor + 14·n` for the smallest `n` giving an instant ≥ now). Reuses the
  one-off date-picker for the anchor plus the weekly time input. Build local wall
  times via `zoneinfo.ZoneInfo` so DST zones stay correct (matches the existing
  frequencies). (Rejected: anchor-from-creation, ISO even/odd-week parity.)
  **Derived rule:** a *past* anchor date is **valid** for biweekly (it only sets
  parity/cadence) even though a past date is *rejected* for a one-off.

### Table view (REM-01)
- **D-07: Columns = Name · Schedule summary · Channel · Next fire (relative) ·
  Status (Active/Paused)**, plus per-row actions **Edit / Pause-Resume / Delete**.
  The message body lives in the modal, not the table. (Rejected: message-preview
  column; minimal 3-column table.)
- **D-08: Readable names only — no raw ID alongside.** Resolve `channel_id` →
  `#channel` and the mention role → `@role` via the Phase 4 `discord_names` cache
  (`core/db.py::get_discord_names`). The raw ID is **not** shown next to the name.
- **D-09: Cache-miss degradation.** When the cache can't resolve a channel/role,
  show a muted placeholder (`#unknown-channel` / `#deleted`) with the **raw ID on
  hover/tooltip** — graceful, never a dead blank, no ID clutter in the happy path.
- **D-10: Paused rows show "—" for Next fire.** A live "in 3 days" on a paused row
  would be a lie; the Status badge carries the paused state. (Consistent with the
  D-01 clean-resume model where the stored `next_fire` is stale until resume.)

### Create/edit modal (REM-01)
- **D-11: Searchable channel/role dropdowns from the cache**, populated from
  `discord_names` (showing `#channel` / `@role`), with a **typed-ID fallback**
  field for a channel/role not yet in the cache. Prevents bad IDs; matches D-08.
- **D-12: Full field parity with Discord.** The modal exposes name, frequency
  (weekly/biweekly/monthly/oneoff) + its schedule field, channel, message body,
  optional mention role, and optional seeded reactions (emoji list, cap 6). A
  panel-created reminder is indistinguishable from a Discord-created one.
- **D-13: Live next-fire preview.** As frequency + schedule are filled, the modal
  shows the computed next fire in team timezone, updating live — catches mistakes
  before save, especially for biweekly (confirms anchor/parity) and month-end
  clamps (day 31 → Feb 28). **Implication:** the schedule math must be reachable
  from the app process (see `<code_context>` extract-shared-math integration point).
- **D-14: Validation carried forward (locked).** Inline per-field errors +
  server-side validate-then-write, reusing the Phase 2 settings-panel pattern.
  Not re-decided here. One frequency's schedule field applies at a time; a partial
  edit can never persist an inconsistent schedule (mirrors the existing `editar`
  cross-field validation).

### Delete / edit-during-fire behavior (REM-03)
- **D-15: Delete confirms with a mid-send warning when imminent.** Delete always
  opens a confirm dialog ("Delete '{name}'?"). If the reminder is within ~1
  scheduler tick of firing, the dialog adds: *"This reminder may already be
  mid-send; deleting stops future occurrences."* Honest about the D-17 accepted
  risk. (Rejected: plain confirm; no-confirm + undo toast.)
- **D-16: Edits save silently, same caveat only when imminent.** An edit normally
  saves without friction; if the reminder is within ~1 tick of firing, show a
  brief note: *"Your change applies from the next fire; the imminent one may
  already be sending."* Symmetric with delete, low-noise. (Rejected: always-silent;
  always-confirm-edits.)
- **D-17: "Never lose the edit to the scheduler's write-back" is LOCKED (REM-03),
  proven under a concurrent-edit test.** The guard **mechanism** — optimistic
  `version`/`updated_at` column with conditional `set_next_fire`/`delete_reminder`
  (`WHERE id=? AND version=?`) **vs.** re-fetch-before-act in `_process_due` — is
  **delegated to research/planner** per PITFALLS.md Pitfall 7. Whichever is chosen
  ships **in this phase** with a test simulating "panel edits row X between
  `due_reminders()` fetch and write-back," asserting the final persisted state
  reflects the edit, not the stale in-flight computation.
- **D-18: The "fires once more after delete" edge is an accepted, documented
  risk** (the Discord message may already be sent before the delete is observed).
  Surfaced via the D-15 confirmation copy rather than eliminated. Same spirit as
  existing accepted-risk entries in this codebase.

### Claude's Discretion
- The scheduler-race guard mechanism (version column vs. re-fetch) — D-17.
- How/where the shared schedule-math module is factored (see `<code_context>`).
- Whether `biweekly`'s anchor reuses the existing `run_date` column or a new
  `anchor_date`/`start_date` column — planner's call, constrained by D-06.
- The exact "within ~1 tick of firing" threshold used to trigger the D-15/D-16
  imminent warnings.
- Table sort order and empty-state copy (bilingual ES/EN, house style).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — **REM-01** (Manager can create/edit/delete via
  table+modal), **REM-02** (pause/resume), **REM-03** (never fires stale, never
  loses the edit to the scheduler write-back; version/re-fetch guard proven under
  concurrent-edit test). **Note the scope expansion:** biweekly (D-05/D-06) is a
  new capability not yet in REQUIREMENTS — a candidate REM-04.
- `.planning/ROADMAP.md` — Phase 6 goal + three success criteria. Also update for
  the biweekly scope expansion.

### Milestone research (directly blueprints this phase — MUST read)
- `.planning/research/ARCHITECTURE.md` — the reminders module is **pure DB CRUD,
  no queue** (`app/routers/reminders.py` NEW; "only a `paused` column is new");
  the reminders row-shape and the "read-at-use / no new integration" statement
  (lines ~40, ~78, ~111, ~382).
- `.planning/research/PITFALLS.md` — **Pitfall 7** (lines 378–447): the
  scheduler-race that REM-03 guards against, with the two mitigation options
  (optimistic version column **or** re-fetch-before-act) and the required
  concurrent-edit test. This is the authoritative source for D-17/D-18. (Pitfall
  1 = per-row try/except; DST/next-fire pitfalls inform biweekly math.)

### Existing implementation (this phase extends it)
- `cogs/reminders.py` — the entire existing reminder engine: schedule math
  (`next_weekly_fire`/`next_monthly_fire`/`next_oneoff_fire`/`compute_next`/
  `classify_fire`/`_clamp_day`), validators, `schedule_summary`, the
  `MensajeModal` create/edit flow, the `@tasks.loop(minutes=1)` scheduler with
  **advance-after-send** crash semantics, and the `/recordatorio`
  crear/listar/borrar/editar commands. Biweekly (D-05/D-06) extends this;
  D-13's preview and app-side create/edit need this math (see extract note).
- `core/db.py` (lines ~245–366) — `init_reminders`, `add_reminder`,
  `list_reminders`, `get_reminder`, `update_reminder` (+ `_REMINDER_UPDATABLE`
  allowlist — **must grow** to include `paused` and any biweekly anchor column),
  `delete_reminder`, `due_reminders` (**must gain `AND paused = 0`** for D-03),
  `set_next_fire`. Phase 4 `discord_names` helpers (`get_discord_names`) back
  D-08/D-09/D-11.

### Prior phase context (patterns this rides on)
- `.planning/phases/05-sqlite-hardening-action-queue-infrastructure/05-CONTEXT.md`
  — establishes that **reminders deliberately bypass the `action_queue`** (pure
  DB CRUD) and the `busy_timeout` global hardening reminders inherit.
- `.planning/phases/04-settings-migration-name-resolution/04-CONTEXT.md` — the
  `discord_names` bot→app name cache reused by D-08/D-09/D-11.
- `.planning/phases/03-dashboard-shell-tiered-access/03-CONTEXT.md` — the
  `require_manager` tier gate (reminders routes are manager-gated), the Alpine
  table+modal conventions, `dashboard.css` per-module accents
  (`--accent-reminders`), and POST-only bilingual conventions.

### Prior design / spec
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — the
  validate-then-write / inline-per-field-error pattern D-14 carries forward.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`cogs/reminders.py` schedule math** — `next_weekly_fire`, `next_monthly_fire`,
  `next_oneoff_fire`, `compute_next`, `classify_fire`, `_clamp_day`, the
  validators, and `schedule_summary` are the deterministic core the panel needs.
- **`core/db.py` reminder helpers** — full CRUD already exists; the panel router
  reuses `add_reminder`/`update_reminder`/`delete_reminder`/`list_reminders`/
  `get_reminder`, extended for `paused` + biweekly.
- **Phase 4 `discord_names` cache** (`get_discord_names`) — backs readable names
  and the modal's searchable channel/role dropdowns (D-08/D-09/D-11).
- **Phase 3 dashboard shell** — `/reminders` route + `_module_stub_page` (to be
  replaced with the real table+modal), `_sidebar.html` entry, `require_manager`
  gate, `--accent-reminders` (#38bdf8), Alpine (`app/static/alpine.min.js`).
- **Phase 2 settings panel** — the inline-per-field-error + validate-then-write
  template D-14 reuses.

### Established Patterns
- **Shared sqlite (`DB_PATH`, WAL) is the only bot↔app channel** — reminders CRUD
  is pure DB, no queue, no IPC (locked). The bot reads at-use every tick.
- **DB idiom:** fresh-connection-per-call; `init_reminders()` from the cog's
  `__init__`; parameterized SQL only; **explicit column allowlist**
  (`_REMINDER_UPDATABLE`) for dynamic updates — grow it for `paused`/anchor, never
  bypass it.
- **Manager-gated, POST-only, bilingual (ES/EN)** for all panel mutations.
- **Advance-after-send** scheduler crash-semantics + per-row try/except (Pitfall 1)
  — the race guard (D-17) must layer onto this without breaking it.

### Integration Points
- **Extract shared schedule math (KEY):** D-13's live preview and app-side
  create/edit both need next-fire computation, but the math lives in
  `cogs/reminders.py` which imports `discord`. Planner should factor the pure
  functions into a framework-agnostic `core/` module (e.g.
  `core/reminder_schedule.py`) that **both** the bot cog and the FastAPI
  router/preview import — matching the house pattern (`core/settings.py`,
  `core/store_sync.py` are pure, cogs/routers are thin adapters). Biweekly math
  lands here too.
- **New:** `app/routers/reminders.py` (manager-gated CRUD + pause/resume +
  next-fire-preview endpoint), reminders table+modal templates, and Alpine
  wiring; `core/db.py` gains a `paused` column (+ biweekly anchor), `due_reminders`
  gains `AND paused = 0`, and the race-guard column/logic (D-17).
- **Discord parity:** the `biweekly` choice + its schedule input must be added to
  `/recordatorio crear` and `editar` in `cogs/reminders.py`.

</code_context>

<specifics>
## Specific Ideas

- **Mid-send warning copy (delete):** "This reminder may already be mid-send;
  deleting stops future occurrences." (bilingual ES/EN).
- **Mid-send caveat (edit):** "Your change applies from the next fire; the
  imminent one may already be sending."
- **Biweekly summary label:** e.g. "Cada 2 semanas · <día> HH:MM".
- **Cache-miss placeholders:** `#unknown-channel` / `#deleted`, raw ID on hover.
- **Overdue-one-off-on-resume** reuses the existing ⏰ **atrasado** late marker.

</specifics>

<deferred>
## Deferred Ideas

- **Message-preview column in the table** — considered, rejected (D-07) in favor
  of showing the body only in the modal; revisit if Managers ask for at-a-glance
  content.
- **Catch-up-on-resume for recurring reminders** — rejected (D-01) in favor of
  clean forward resume; revisit only if a real "I want the missed one" need appears.
- **Roadmap/requirements update for biweekly** — not a deferral of the feature
  (it's folded in), but a follow-up bookkeeping task: add REM-04 (biweekly) to
  REQUIREMENTS.md and note the scope expansion in ROADMAP.md Phase 6.

</deferred>

---

*Phase: 6-Reminders CRUD*
*Context gathered: 2026-07-23*
