# Phase 9: Meetings Browser + Re-publish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-29
**Phase:** 9-meetings-browser-re-publish
**Areas discussed:** Meeting record & post identity, Re-publish idempotency & scope, History browser presentation, Backfill of old meetings

---

## Meeting record & post identity

| Option | Description | Selected |
|--------|-------------|----------|
| Full record | topic, timestamps, participants, notes, transcript, summary, forum ids | ✓ |
| Minimal record | summary + transcript + forum ids only | |
| Full minus transcript | everything except full transcript (kept as .md attachment) | |

**User's choice:** Full record

| Option | Description | Selected |
|--------|-------------|----------|
| Thread id + starter-message id | edit that message's embed directly; no lookup | ✓ |
| Thread id only | look up starter message at edit time | |
| You decide | pick during planning | |

**User's choice:** Store thread id + starter-message id

| Option | Description | Selected |
|--------|-------------|----------|
| Store attendee names | names only, from voice session | ✓ |
| Skip participants | topic/date/summary/transcript only | |

**User's choice:** Yes — store attendee names

---

## Re-publish idempotency & scope

| Option | Description | Selected |
|--------|-------------|----------|
| Action queue + enqueue_deduped | reuse Phase-8 pattern; dedups concurrent clicks/retries | ✓ |
| Stored-message-id guard only | if id → edit, else create; in-process lock | |
| You decide | pick during planning | |

**User's choice:** Action queue + enqueue_deduped

| Option | Description | Selected |
|--------|-------------|----------|
| Summary embed only | transcript .md stays immutable | ✓ |
| Embed + re-sync .md | re-upload the .md on every edit | |
| Embed + notes field | edit summary + notes together | |

**User's choice:** Summary embed only

| Option | Description | Selected |
|--------|-------------|----------|
| Summary editable, transcript read-only | matches MEET-03 exactly | ✓ |
| Summary + notes editable | also fix the notes | |
| Everything editable | summary, notes, transcript | |

**User's choice:** Summary editable, transcript read-only

---

## History browser presentation

| Option | Description | Selected |
|--------|-------------|----------|
| Reverse-chron rows w/ preview | topic, date, attendee count, summary preview → detail | ✓ |
| Compact rows, detail on click | topic + date only | |
| Grouped by date | Today/This week/earlier buckets | |

**User's choice:** Reverse-chron rows with preview

| Option | Description | Selected |
|--------|-------------|----------|
| Collapsible inline | collapsed by default + forum .md link | ✓ |
| Download-only | .md link, never rendered | |
| Always inline in full | no collapse | |

**User's choice:** Collapsible inline

| Option | Description | Selected |
|--------|-------------|----------|
| Inline textarea + 'Save & re-publish' | one button saves + enqueues re-publish | ✓ |
| Save and re-publish as separate actions | two buttons | |
| Modal editor | edit in a modal over the list | |

**User's choice:** Inline textarea + single 'Save & re-publish'

---

## Backfill of old meetings

| Option | Description | Selected |
|--------|-------------|----------|
| Start fresh | persistence begins now; old posts not in dashboard | |
| Backfill from forum threads | import existing threads into rows | ✓ |
| Manual backfill later | ship fresh, defer import idea | |

**User's choice:** Backfill from forum threads

| Option | Description | Selected |
|--------|-------------|----------|
| Persist every meeting; re-publish only when forum post exists | always write row, forum ids when posted | ✓ |
| Only persist forum-posted meetings | skip text-channel fallback meetings | |

**User's choice:** Persist every meeting; re-publish only when a forum post exists

| Option | Description | Selected |
|--------|-------------|----------|
| Best-effort import | summary+ids always; transcript when .md downloadable; log gaps | ✓ |
| Strict format-match only | only exact-format threads | |
| Embed-only, never fetch .md | no stored transcript for backfilled | |

**User's choice:** Best-effort import

| Option | Description | Selected |
|--------|-------------|----------|
| Idempotent, dedup on thread id | upsert keyed on thread id; safe to re-run | ✓ |
| One-shot with completion flag | runs once; manual reset to retry | |

**User's choice:** Idempotent, dedup on thread id

---

## Claude's Discretion

- Exact sqlite schema/column names and migration mechanics (follow `core/db.py` idioms).
- discord.py API specifics for editing a forum starter-message embed and for the backfill walk/download.
- Backfill trigger mechanics (command vs guarded startup task), constrained by the idempotency decision.

## Deferred Ideas

None — discussion stayed within phase scope. Backfill was folded into scope, not deferred.

## Accepted defaults (no objection)

- Re-publish records the editing Manager's OAuth display name in the activity log (Phase-8 attribution).
- Editing a summary silently edits the forum post — no new announcement.
