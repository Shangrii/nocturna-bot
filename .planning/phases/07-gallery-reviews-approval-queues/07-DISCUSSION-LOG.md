# Phase 7: Gallery + Reviews Approval Queues - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-23
**Phase:** 7-Gallery + Reviews Approval Queues
**Areas discussed:** Queue data + freshness, Photo preview UI, Destructive-action friction, Action scope + anonymity

---

## Queue data + freshness

### Queue freshness

| Option | Description | Selected |
|--------|-------------|----------|
| Near-live push + auto-refresh | Bot re-pushes snapshot ~30-60s (heartbeat-style); panel Alpine short-polls, new items appear without reload | ✓ |
| Push + manual 'Refresh now' | Bot pushes on its cadence; a Manager can force a fresh scan via action_queue | |
| Snapshot on page-load only | Cache kept current on the loop; panel shows what's cached at load, no auto-refresh | |

**User's choice:** Near-live push + auto-refresh
**Notes:** The push cadence also keeps Discord CDN signed thumbnail URLs fresh (~24h expiry), so a queued photo never shows a dead thumbnail.

### Pending gallery row fields

| Option | Description | Selected |
|--------|-------------|----------|
| Full context | Thumbnail + poster + caption + posted-at + open-in-Discord link | ✓ |
| Thumbnail + caption only | Minimal card, no poster/timestamp/jump | |
| You decide | Match reaction-flow context and house style | |

**User's choice:** Full context

### Review row fields

| Option | Description | Selected |
|--------|-------------|----------|
| Author/Anónimo + text + date + badge | Named display name / fixed 'Anónimo', full text, date, named/anon badge; anon identity never shown | ✓ |
| Author/Anónimo + text + date | Same without the explicit badge | |
| You decide | Consistent with gallery row + anonymity contract | |

**User's choice:** Author/Anónimo + text + date + badge

---

## Photo preview UI

### Gallery presentation

| Option | Description | Selected |
|--------|-------------|----------|
| Responsive thumbnail grid | Each photo a card in a responsive grid (image + fields + actions) | ✓ |
| List rows with small thumbnail | Reminders-style table, small thumbnail per row | |
| You decide | Best fit for a photo-approval surface | |

**User's choice:** Responsive thumbnail grid

### Pending vs published organization

| Option | Description | Selected |
|--------|-------------|----------|
| Two labeled groups, one page | 'Pending' top, 'Published' below, both visible | |
| Tabs: Pending \| Published | Tab switch between the two lists | ✓ |
| One list + status filter | Single list with Pending/Published/All toggle | |

**User's choice:** Tabs: Pending | Published

### Full-size preview

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — click to expand (lightbox) | Click a thumbnail to inspect full-size before acting | ✓ |
| No — thumbnail is enough | Use the open-in-Discord link for detail | |

**User's choice:** Yes — click to expand (lightbox)

---

## Destructive-action friction

### Remove confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| Confirm dialog | Short confirm before enqueuing a live-content removal | ✓ |
| No confirm | Act immediately; rely on re-approve reversibility | |
| No confirm + undo toast | Act immediately with an Undo toast | |

**User's choice:** Confirm dialog

### Approve friction

| Option | Description | Selected |
|--------|-------------|----------|
| One-click, no confirm | Single click + inline Working…→✓ status | ✓ |
| Confirm dialog too | Symmetric friction before publishing | |

**User's choice:** One-click, no confirm

### Concurrent / already-moot actions

| Option | Description | Selected |
|--------|-------------|----------|
| Benign 'already done' success | 🟢-marker no-op reflected as a quiet success (ya publicada/quitada), true parity | ✓ |
| Show as failure/error | Surface the no-op as a red error state | |

**User's choice:** Benign 'already done' success

---

## Action scope + anonymity

### Gallery panel scope (editor-credit / NSFW)

| Option | Description | Selected |
|--------|-------------|----------|
| Approve/remove only (credit/NSFW deferred) | Match the roadmap boundary; credit/NSFW stay on `/galeria creditar` | ✓ |
| Add editor-credit + NSFW to the panel | Scope expansion: credit dropdown + NSFW toggle on cards | |
| You decide | Weigh workflow gap vs scope | |

**User's choice:** Approve/remove only (credit/NSFW deferred)

### Anonymous-review identity visibility

| Option | Description | Selected |
|--------|-------------|----------|
| Never — identity never reaches the panel | Cache carries only 'Anónimo' + text + date; no tier can de-anonymize | (see reconcile) |
| Owner-only reveal | Owner tier can reveal the submitter for moderation | (initially chosen) |

**User's choice:** Initially "Owner-only reveal" — flagged by Claude as conflicting with the existing hard anonymity contract (`ReviewModal` T-07-02) AND the submitter-facing promise "Reseña anónima — se publica sin ningún dato tuyo." Reconciled below.

#### Reconcile: reveal vs the "sin ningún dato tuyo" promise

| Option | Description | Selected |
|--------|-------------|----------|
| Keep reveal, make the promise honest | Owner reveal + update collection-panel copy to disclose staff visibility | |
| Drop reveal, keep true anonymity | Identity never stored; promise stands; no tier can de-anonymize | ✓ |
| Reveal, but store minimally | Owner reveal storing only the Discord user id, resolved live | |

**User's choice:** Drop reveal, keep true anonymity
**Notes:** Final decision (D-13) preserves the shipped end-to-end anonymity contract — no cog rewrite, no trust-boundary change, no consent-copy change.

---

## Claude's Discretion

- Exact push-cache table schema/column names + precise refresh interval within the ~30-60s envelope; one shared cache table vs one per module.
- Exact `action_queue` `kind` names and payload shape.
- The Alpine short-poll interval (reuse the Phase-5 value).
- Whether the Published list is sourced from the push cache or read from gallery.json/reviews.json.
- Lightbox implementation and grid breakpoints.
- All bilingual ES/EN copy (confirm dialogs, empty states, badge, "already done"/offline messages), Spanish-first.

## Deferred Ideas

- Editor-credit + NSFW flag in the panel (deferred to a later phase; stays on `/galeria creditar`).
- Owner-only de-anonymization of anonymous reviews (rejected, not just deferred — breaks anonymity guarantee + submitter promise).
- Reviews collection panel (`panel_resenas`) management from the dashboard (out of scope — client-facing Discord affordance).
