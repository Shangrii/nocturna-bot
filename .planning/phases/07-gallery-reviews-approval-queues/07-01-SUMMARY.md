---
phase: 07-gallery-reviews-approval-queues
plan: 01
subsystem: database
tags: [discord.py, sqlite, push-cache, gallery, reviews]

requires:
  - phase: 05-sqlite-hardening-action-queue-infrastructure
    provides: WAL/busy-timeout shared sqlite access
  - phase: 04-settings-migration-name-resolution
    provides: bot-to-app periodic push-cache pattern
provides:
  - Gallery and reviews queue cache tables with upsert/read/delete helpers
  - Bounded 45-second Discord push-cache cog
  - Anonymity-safe review snapshots and bot-reply exclusion
affects: [07-02, 07-03, gallery, reviews, action-queue]

tech-stack:
  added: []
  patterns:
    - bot-to-app cache via shared sqlite
    - upsert mutable fields while preserving resolved identity/date fields

key-files:
  created:
    - cogs/gallery_reviews_cache.py
    - tests/test_gallery_reviews_cache_cog.py
  modified:
    - core/db.py
    - bot.py

key-decisions:
  - "Use a bounded 300-message scan every 45 seconds."
  - "Store author=None for anonymous reviews; never persist the submitter display name."
  - "Reuse gallery/reviews pure helpers as the only classification and bot-exclusion seams."

patterns-established:
  - "Queue cache writes refresh mutable content while preserving first-resolved poster/author/date fields."
  - "Rows absent from both the bounded Discord scan and published JSON entries are pruned."

requirements-completed: [GAL-01, REV-01]

duration: 12min
completed: 2026-07-24
---

# Phase 7 Plan 01: Gallery and Reviews Queue Cache Summary

**A bounded Discord push-cache now exposes pending and published gallery/review items through anonymity-safe shared-sqlite tables.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-24T05:48:00Z
- **Completed:** 2026-07-24T06:00:24Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added parameterized gallery/reviews queue schemas plus upsert, filtered read, row lookup, and scoped delete helpers.
- Added a registered 45-second cache cog that scans at most 300 messages per channel and classifies through existing pure helpers.
- Preserved end-to-end anonymous-review privacy and excluded non-review bot replies from the moderation queue.

## Task Commits

1. **Task 1: core/db.py gallery_queue + reviews_queue helpers** - `c981f21`
2. **Task 2: GalleryReviewsCacheCog + bot registration** - `0a77d79`

## Files Created/Modified

- `core/db.py` - Queue table schemas and parameterized cache helpers.
- `cogs/gallery_reviews_cache.py` - Periodic bounded bot-to-app cache writer.
- `bot.py` - Loads the gallery/reviews cache extension.
- `tests/test_gallery_reviews_cache_cog.py` - DB, classification, anonymity, exclusion, and pruning contracts.

## Decisions Made

- Used existing `_is_published`, `_image_attachments`, `_review_author_and_text`, and `_is_own_review_embed` helpers rather than duplicating reaction-flow logic.
- Kept anonymous review `author` as `NULL`; `REVIEW_ANON_LABEL` remains a presentation concern.
- Used existing gallery entry parsing to retain old published rows that fall outside the bounded live scan.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The sandbox could not access pytest's Windows temporary directory. Verification was rerun with approved elevated execution; no code change was required.

## User Setup Required

None - no external service configuration required.

## Verification

- `C:\Users\Shangri\miniconda3\python.exe -m pytest tests/test_gallery_reviews_cache_cog.py -x` - 8 passed.
- `C:\Users\Shangri\miniconda3\python.exe -c "import cogs.gallery_reviews_cache"` - passed.
- Scope check confirmed `cogs/gallery.py` and `cogs/reviews.py` were unchanged.
- Diff review found no new SQL value interpolation.

## Self-Check: PASSED

## Next Phase Readiness

- Queue cache tables and bot-side snapshots are ready for `07-03`.
- `07-02` must add and verify the action dispatch handlers before the app routes can be wired.

---
*Phase: 07-gallery-reviews-approval-queues*
*Completed: 2026-07-24*
