# Phase 6: Reminders CRUD - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-23
**Phase:** 6-Reminders CRUD
**Areas discussed:** Pause/resume semantics, Table view & readable names, Biweekly frequency (folded in), Create/edit modal & pickers, Delete/edit-during-fire behavior

---

## Pause/resume semantics

### Resume behavior for a recurring reminder paused across occurrences
| Option | Description | Selected |
|--------|-------------|----------|
| Clean resume — next future occurrence | Recompute next_fire forward; no backfill | ✓ |
| Catch-up one, then resume | Fire the missed one ⏰, then continue | |
| Freeze & thaw | Preserve stored next_fire; fire at that instant | |

**User's choice:** Clean resume — next future occurrence.

### One-off whose date passed while paused, on resume
| Option | Description | Selected |
|--------|-------------|----------|
| Fire once on resume (overdue) | Fires once ⏰ atrasado, then deletes | ✓ |
| Block resume — must reschedule | Reject; force a new future date | |
| Silently expire | Mark expired/deleted, no message | |

**User's choice:** Fire once on resume (overdue).
**Notes:** Owner chose this over the recommended "block resume" — a one-off is a specific message they still want delivered, just late. Deliberately differs from the recurring clean-resume rule.

### Does pausing suppress an imminent (seconds-away) fire?
| Option | Description | Selected |
|--------|-------------|----------|
| Pause wins if it lands first | due-query excludes paused; best-effort, accepts one-tick race | ✓ |
| Always let the in-flight one fire | Pause affects only future occurrences | |
| Hard-stop — never fire once paused | Re-check paused immediately before send | |

**User's choice:** Pause wins if it lands first.

### Editing a currently-paused reminder — does saving change paused state?
| Option | Description | Selected |
|--------|-------------|----------|
| Stays paused | Edit and pause orthogonal; resume explicitly | ✓ |
| Edit auto-resumes it | Saving any edit clears paused | |
| Ask on save | Prompt keep-paused vs resume | |

**User's choice:** Stays paused.

---

## Table view & readable names

### How channel/mention role appear in the table & modal
| Option | Description | Selected |
|--------|-------------|----------|
| Readable names via the cache | #channel / @role + raw ID beneath | |
| Readable names, no fallback ID | #channel / @role only, no ID clutter | ✓ |
| Raw IDs only | Numeric IDs | |

**User's choice:** Readable names, no fallback ID.

### Table columns
| Option | Description | Selected |
|--------|-------------|----------|
| Name · Schedule · Channel · Next fire · Status | Full scannable set + row actions; message in modal | ✓ |
| Add a message preview column | Same + truncated body preview | |
| Minimal — Name · Schedule · Status | Compact; channel/next-fire in modal | |

**User's choice:** Name · Schedule · Channel · Next fire · Status (+ Edit / Pause-Resume / Delete).

### "Next fire" for a paused reminder
| Option | Description | Selected |
|--------|-------------|----------|
| Show — (dash), Status says Paused | No misleading countdown | ✓ |
| Show where it WOULD fire, greyed | Greyed next occurrence | |
| Show its stored next_fire | Whatever is stored (can be stale) | |

**User's choice:** Show — (dash), Status says Paused.

### Cache miss (channel/role unresolvable) with no raw ID shown
| Option | Description | Selected |
|--------|-------------|----------|
| Placeholder + ID on hover | '#unknown-channel' + raw ID on hover | ✓ |
| Fall back to raw ID for that cell only | Only unresolved cells show ID | |
| Show a warning marker | ⚠ 'name unavailable' badge | |

**User's choice:** Placeholder + ID on hover.

---

## Biweekly frequency (folded in)

### How to handle the biweekly request (mid-discussion user request)
| Option | Description | Selected |
|--------|-------------|----------|
| Fold into Phase 6 scope | Add biweekly as a 4th frequency this phase | ✓ |
| Note for roadmap backlog | Defer as a follow-up phase | |
| Decide later, note it prominently | Park in Deferred Ideas | |

**User's choice:** Fold into Phase 6 scope.
**Notes:** Flagged as a scope expansion past the original roadmap boundary — reaches into the bot's schedule engine and the Discord command. ROADMAP.md/REQUIREMENTS.md to be updated (candidate REM-04).

### Biweekly anchoring
| Option | Description | Selected |
|--------|-------------|----------|
| Chosen start date | Manager picks first-fire date; +14 days from there | ✓ |
| Anchor from creation | Weekday+time; creation week = week 0 | |
| ISO even/odd week | Pure calendar parity rule | |

**User's choice:** Chosen start date.
**Notes:** Reuses the one-off date-picker for the anchor + the weekly time; DST-correct via ZoneInfo. Past anchor dates are valid for biweekly (parity only) though rejected for one-offs.

---

## Create/edit modal & pickers

### Channel & mention role input
| Option | Description | Selected |
|--------|-------------|----------|
| Searchable dropdown from the cache | <select> from discord_names + typed-ID fallback | ✓ |
| Typed ID with live name preview | Paste ID, resolve name live | |
| Plain typed ID | Raw ID field, shape-validated | |

**User's choice:** Searchable dropdown from the cache.

### Which fields the panel modal exposes
| Option | Description | Selected |
|--------|-------------|----------|
| Full parity | Everything Discord has, incl. mention + reactions | ✓ |
| Core fields, reactions hidden | Drop seeded reactions from the panel | |
| Minimal | Name/frequency/schedule/channel/message only | |

**User's choice:** Full parity.

### Live next-fire preview before save
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, live next-fire preview | Live team-tz preview as they type | ✓ |
| No preview, validate on save | Result shows in the table afterward | |
| Preview only on the confirmation step | Show in a confirm/summary step | |

**User's choice:** Yes, live next-fire preview.
**Notes:** Implies schedule math must be reachable from the app process — extract a shared framework-agnostic module. Validation feedback (inline per-field + validate-then-write) carried forward from the Phase 2 settings panel, not re-decided.

---

## Delete/edit-during-fire behavior

### Delete confirmation
| Option | Description | Selected |
|--------|-------------|----------|
| Confirm dialog, with mid-send warning | Confirm + warning when within ~1 tick of firing | ✓ |
| Plain confirm dialog | Confirm, no special warning | |
| No confirm — instant delete + undo | Undo toast instead of dialog | |

**User's choice:** Confirm dialog, with mid-send warning.

### Edit-during-imminent-fire caveat
| Option | Description | Selected |
|--------|-------------|----------|
| Same caveat, only when imminent | Silent normally; caveat within ~1 tick | ✓ |
| Silent — edits never warn | Always save quietly | |
| Always confirm edits too | Confirm every edit | |

**User's choice:** Same caveat, only when imminent.
**Notes:** "Never lose the edit to the scheduler write-back" is locked by REM-03 and proven under a concurrent-edit test; the delete-fires-once edge is accepted+documented (Pitfall 7).

---

## Claude's Discretion

- Scheduler-race guard mechanism (optimistic version column vs. re-fetch-before-act) — delegated to research/planner per PITFALLS.md Pitfall 7.
- Factoring of the shared schedule-math module; whether biweekly reuses `run_date` or a new anchor column.
- Exact "within ~1 tick of firing" threshold for the imminent warnings.
- Table sort order and empty-state copy (bilingual ES/EN).

## Deferred Ideas

- Message-preview column in the table (rejected D-07; revisit on demand).
- Catch-up-on-resume for recurring reminders (rejected D-01; revisit on demand).
- Roadmap/REQUIREMENTS bookkeeping for the biweekly scope expansion (add REM-04).
