# Phase 8: Jinxxy Manual Sync - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-24
**Phase:** 8-Jinxxy Manual Sync
**Areas discussed:** Overlap guard behavior, In-flight state across sessions, Result & error feedback, Jinxxy section page content

---

## Overlap guard behavior

### Q1 — A Manager clicks Sync while the scheduled `_poll` is already mid-sync. What should happen?

| Option | Description | Selected |
|--------|-------------|----------|
| Benign "already syncing" success | Dispatch detects a sync in flight and returns a quiet success, never a red ✗. Mirrors Phase-7 D-11. Returns instantly, so the serialized queue slot is never blocked. | ✓ |
| Coalesce — run right after | Action stays pending and dispatches once the poll releases. Requires a re-queue-and-return design to avoid stalling the single dispatch slot. | |
| Hold the action until free | Handler blocks on the lock. Simplest code, but parks the dispatch slot for the whole poll duration. | |

**User's choice:** Benign "already syncing" success → **D-01**

### Q2 — Where should the "a sync is running" state live?

| Option | Description | Selected |
|--------|-------------|----------|
| asyncio.Lock + DB mirror | In-process lock is authoritative (both triggers funnel through `_run_sync` in one process); a `running` state in `jinxxy_sync_status` is the panel-visible mirror. | ✓ |
| asyncio.Lock only | Correct and minimal, zero schema change — but the app can never show "sync in progress". | |
| DB flag only | Visible and restart-surviving, but a row read/write is not a mutex and a crash leaves it stuck. | |

**User's choice:** asyncio.Lock + DB mirror → **D-02**

### Q3 — The poll's tick fires while a manual sync is running. What should the poll do?

| Option | Description | Selected |
|--------|-------------|----------|
| Skip the tick, log only | No sync, no announce; next cadence runs normally. Symmetric back-off. | ✓ |
| Poll waits, then runs | Cadence never skipped, but a redundant full re-enumeration seconds after one completed. | |
| Poll wins — manual backs off | Inverts the guard: an explicit click loses to a background timer. | |

**User's choice:** Skip the tick, log only → **D-03**

### Q4 — Back-to-back syncs: two Managers each click, or one clicks right after a run finishes.

| Option | Description | Selected |
|--------|-------------|----------|
| Dedupe at enqueue | If a `jinxxy_sync` action is pending/claimed, return that id instead of enqueuing a second. Closes the hole the concurrent guard misses. | ✓ |
| Dedupe + short cooldown | Adds a minimum interval after a completed run. Strictest on API cost; a second rule and second state to test. | |
| No extra guard | Only the concurrent guard applies; each click pays a full redundant enumeration. | |

**User's choice:** Dedupe at enqueue → **D-04**

---

## In-flight state across sessions

### Q1 — Should the panel's busy state reflect all three sync entry points?

| Option | Description | Selected |
|--------|-------------|----------|
| Any sync shows busy | The mirror wraps `_run_sync`, so poll / `/tienda sync` / panel are all covered for free. Every Manager sees it; survives a reload. | ✓ |
| Only panel-triggered shows busy | Busy derived from the `action_queue` row alone. No new column, but an idle-looking button during a poll. | |

**User's choice:** Any sync shows busy → **D-05**

### Q2 — Bot crashes mid-sync, leaving the mirror stuck on "running".

| Option | Description | Selected |
|--------|-------------|----------|
| Clear on startup + heartbeat staleness | `JinxxyCog.__init__` clears the mirror; the app voids it when `bot_heartbeat` is stale. No sweeper, no timeout constant. | ✓ |
| Timeout on the mirror | Treat `running` older than N minutes as stale. N is a guess in both directions. | |
| Clear on startup only | Correct once the bot returns, but a phantom "in progress" for the whole outage. | |

**User's choice:** Clear on startup + heartbeat staleness → **D-06**

### Q3 — What does the panel render while a sync runs?

| Option | Description | Selected |
|--------|-------------|----------|
| Spinner + elapsed + source | "Sincronizando… 1:20" plus what started it. Derivable from the mirror row; no new bot→app machinery. | ✓ |
| Spinner + elapsed only | No source column needed, but an unexplained sync reads as the panel acting on its own. | |
| Plain spinner | Pure Phase-5 pattern, zero additions — can't tell slow from hung on a multi-minute run. | |

**User's choice:** Spinner + elapsed + source → **D-07**

### Q4 — A click while the bot is offline: keep Phase-5 D-07 durable-queue behavior?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — lands as "already syncing" | On reconnect the `_poll` startup tick takes the lock; the queued action resolves as D-01's benign success. The two guards compose. | ✓ |
| Expire a stale queued sync | Cleaner semantics, but breaks Phase-5's "the queue never silently drops an action" invariant for one kind. | |
| Don't enqueue while offline | Avoids the question but discards the "no lost clicks" property Phase 5 built. | |

**User's choice:** Yes — lands as "already syncing" → **D-08**

---

## Result & error feedback

### Q1 — What should the panel show on success?

| Option | Description | Selected |
|--------|-------------|----------|
| Counts, and persist them | Show added/updated/removed from the action result AND widen `jinxxy_sync_status` so poll- and Discord-triggered runs are equally informative. | ✓ |
| Counts from the action result only | Zero schema change, but counts exist only for panel-triggered syncs. | |
| Bare ✓ + product count | Nothing new at all — hides the one thing the Manager clicked to learn. | |

**User's choice:** Counts, and persist them → **D-09**

### Q2 — How much failure detail does the panel show?

| Option | Description | Selected |
|--------|-------------|----------|
| Category from exception type | Fixed bilingual reason per exception type; no raw third-party string rendered. Honors the errors-to-logs rule and the no-secrets invariant while staying actionable. | ✓ |
| Short raw reason | Most diagnostic and consistent with Phase-5 D-02 — but the text originates from third-party clients. | |
| Generic only | Maximally safe, but a Manager can't tell a Jinxxy outage from a GitHub failure without shell access. | |

**User's choice:** Category from exception type → **D-10**

**Notes:** A deliberate divergence from Phase-5 D-02's "short raw reason", justified by the exception text originating outside this codebase.

### Q3 — Should a panel-triggered sync post the public store-news announce embed?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — announce, same rules | Handler calls `_run_sync` then `_announce`, exactly like `/tienda sync`. D-06 keeps no-change silent; the guards prevent repeat posts. | ✓ |
| No — panel syncs stay silent | Keeps the announce channel tied to the two existing flows, but an identical sync would announce from Discord and not from the panel. | |

**User's choice:** Yes — announce, same rules → **D-11**

### Q4 — Should the activity line and status card name the trigger source?

| Option | Description | Selected |
|--------|-------------|----------|
| Attribute the trigger | Names the source using `requested_by` (already on the queue row) and the source column added for the in-flight label. Ops audit trail. | ✓ |
| Keep the generic line | Nothing changes in existing instrumentation, but the Overview feed can't answer "who kicked that off?" | |

**User's choice:** Attribute the trigger → **D-12**

---

## Jinxxy section page content

### Q1 — What should the `/jinxxy` section contain?

| Option | Description | Selected |
|--------|-------------|----------|
| Status + button + read-only list | Adds a read-only table from `store_snapshot` — local data the bot already owns, no credentials, no new cache. Read-only display, so no new capability. | ✓ |
| Status + button + totals | Closest to the roadmap's literal wording; one screenful, nothing to scroll. | |
| Status + button only | Smallest surface — but the section holds one button. | |

**User's choice:** Status + button + read-only list → **D-13**

**Notes:** Flagged during discussion — `store_snapshot` carries only sync-owned fields; staff-supplied images/description/editor live only in `store.json` and cannot appear.

### Q2 — How should the read-only list render?

| Option | Description | Selected |
|--------|-------------|----------|
| Compact table | Reuses the shipped Reminders table styling; scans well; no modal needed since nothing is editable. | ✓ |
| Card grid | Closer to the Gallery section, but with no image available these are picture-less cards. | |
| Collapsed by default | Least competition with the primary action; one more interaction to verify what synced. | |

**User's choice:** Compact table → **D-14**

### Q3 — What shows before any sync has ever run?

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit never-synced state | "Nunca se ha sincronizado" + "Aún no hay productos sincronizados", button enabled and prominent. Distinguishes "never ran" from "ran and found nothing". | ✓ |
| Reuse the Overview dash | Consistent with the shipped tile, but a dash reads as "unknown". | |
| Hide the list until first sync | Cleanest first run, but the page changes shape and empty-after-sync looks identical to never-synced. | |

**User's choice:** Explicit never-synced state → **D-15**

### Q4 — Does the Sync button confirm?

| Option | Description | Selected |
|--------|-------------|----------|
| One-click, no confirm | A sync only makes the store match Jinxxy — the same reconcile the poll runs unattended. Matches `/tienda sync` and Phase-7's one-click Approve. | ✓ |
| Confirm dialog | Consistent with Phase-7's Remove confirm, but gates an action the scheduler performs unattended anyway. | |

**User's choice:** One-click, no confirm → **D-16**

---

## Claude's Discretion

Left to research/planning (see CONTEXT.md `<decisions>` → *Claude's Discretion* for the full list):
the `kind` string and payload shape; new column names on `jinxxy_sync_status` and how the
ADD-COLUMN widening is applied; the exact dedupe query; short-poll intervals and elapsed
formatting; table columns, sort order, and any filter; whether the Overview tile also gains the
counts; all bilingual ES/EN copy; and the design of the automated overlap test that roadmap
criterion #2 requires.

## Deferred Ideas

- Editing store metadata from the panel (images/description via `/tienda medios`, credited
  editor via `/tienda editar`) — stays on the Discord commands (D-17).
- A time-based cooldown between manual syncs — redundant once duplicates dedupe at enqueue.
- Surfacing the counts on the Overview tile — planner's discretion.
- Per-step sync-progress detail — rejected in favor of spinner + elapsed; would need new
  bot→app progress pushes.
