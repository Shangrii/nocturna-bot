---
phase: 10-editors-section-integration
plan: 06
subsystem: infra
tags: [astro, static-site, routing, redirect, vanity-url]

# Dependency graph
requires: []
provides:
  - Root-level vanity route `/{slug}` serving the full editor profile page (Website repo)
  - Legacy `/e/{slug}` build-time redirect stub forwarding to `/{slug}`
affects: [10-07-editors-section-integration-verify]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Astro build-time redirect stub (define:vars + location.replace + noscript meta-refresh + rel=canonical), mirrored from [lang]/[concept]/[slug].astro one cartesian dimension shallower"

key-files:
  created:
    - "../Website/src/pages/e/[slug].astro (redirect stub, replaces the moved full-page render)"
  modified:
    - "../Website/src/pages/[slug].astro (new root-level vanity page, moved via git mv from src/pages/e/[slug].astro; import depths ../../ -> ../)"

key-decisions:
  - "Website repo commits kept separate from nocturna-bot commits (cross-repo plan); each task committed atomically inside ../Website with the plan's conventional-commit messages"
  - "npm run build gate ran locally (Node v24.13.0 available) rather than deferred to CI, since a local toolchain was present"

patterns-established:
  - "Astro redirect-stub quadruple (define:vars target, location.replace, noscript meta-refresh, rel=canonical) confirmed reusable at a shallower cartesian depth (single slug param, no locale loop)"

requirements-completed: [EDIT-02]

# Metrics
duration: 8min
completed: 2026-07-30
---

# Phase 10 Plan 06: Editor Vanity URL Route Move Summary

**Moved the editor profile page to a root-level `/{slug}` Astro route and turned the old `/e/{slug}` path into a build-time redirect stub, both verified with a green local `npm run build`.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-07-30T17:39:00Z
- **Completed:** 2026-07-30T17:46:52Z
- **Tasks:** 2
- **Files modified:** 2 (Website repo only)

## Accomplishments
- Editor profile page now serves from the root vanity route `/{slug}` (Astro literal-route-over-dynamic-route priority preserved — `/en/*`, `/es/*`, and `public/gallery`/`public/store`/`public/fonts` static folders still resolve, confirmed by a full build)
- Legacy `/e/{slug}` links keep working via a new build-time redirect stub to `/{slug}`, replicating the exact `location.replace` + `define:vars` + `<noscript>` meta-refresh + `rel="canonical"` pattern already shipped at `[lang]/[concept]/[slug].astro`
- Open-redirect guard preserved end-to-end: `target` is a build-time literal derived from `Astro.params.slug` inside `getStaticPaths`, never a runtime-read value, with no `?next=` param

## Task Commits

Both tasks committed in the sibling **Website** repo (`../Website`, not this repo):

1. **Task 1: Move the editor profile page to the root vanity route** - `b412143` (feat) — `git mv src/pages/e/[slug].astro src/pages/[slug].astro`; shifted every relative import one level up (`../../` -> `../`), including the inline `<script>`'s `gallery.ts` import; `getStaticPaths`/`Astro.props`/render body left byte-identical.
2. **Task 2: Replace e/[slug].astro with a build-time redirect stub** - `e9dc794` (feat) — new `getStaticPaths` filters `published === true` + non-empty slug, dedupes by slug, emits one stub per editor; `target = \`/${slug}\`` baked via `define:vars`.

**Plan metadata:** (this commit, in `nocturna-bot`) — SUMMARY.md + STATE.md/ROADMAP.md tracking.

_Note: no TDD tasks in this plan (Astro static routing, not test-driven)._

## Files Created/Modified

**Website repo (`C:\Users\Shangri\Pictures\Nocturna Avatars\Coding\Website`):**
- `src/pages/[slug].astro` - root-level vanity route; full editor profile render moved here from `src/pages/e/[slug].astro`, import depths corrected
- `src/pages/e/[slug].astro` - now a build-time redirect stub to `/{slug}` (previously the full-page render)

**nocturna-bot repo (this repo):**
- `.planning/phases/10-editors-section-integration/10-06-SUMMARY.md` - this summary
- `.planning/STATE.md` - position/progress update
- `.planning/ROADMAP.md` - plan progress update

## Decisions Made
- Kept the Website repo's commits fully separate from this repo's tracking commit, per the plan's cross-repo instructions — code changes committed inside `../Website` with conventional-commit messages, SUMMARY/STATE/ROADMAP committed here.
- Ran `npm run build` locally rather than deferring to CI: Node v24.13.0 / npm 11.6.2 were available in this environment, so the Pitfall 5 route-priority gate could be empirically verified immediately rather than flagged for the 10-07 human-verify checkpoint.

## Deviations from Plan

None - plan executed exactly as written. One incidental doc-comment update beyond the mechanical import-depth shift: the moved `[slug].astro` file's header docblock referenced the old `/e/<slug>` path in its description; updated the prose to describe the new root-level route and note the redirect-stub relationship, for continuity of that file's inline documentation. This is a comment-only change with zero effect on behavior, `getStaticPaths`, `Astro.props`, or the render body — included as normal task execution, not tracked as a deviation.

## Issues Encountered

None. Both `npm run build` runs succeeded on the first attempt:
- Task 1 build: 22 pages generated, including `/imp/index.html` and `/shangri/index.html` (new root vanity pages) alongside `/en/galeria`, `/en/servicios`, `/es/*` routes and the copied `public/gallery`/`public/store`/`public/fonts` static folders — no route-priority regression.
- Task 2 build: 24 pages generated (adds `/e/imp/index.html` and `/e/shangri/index.html` stubs). Verified the compiled stub HTML for `/e/imp` contains `target = "/imp"`, `href="/imp"`, and `url=/imp` — confirming the build-time literal resolves to the root path with no `/e/` prefix and no runtime-read redirect target.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both Astro routing changes are committed and build-verified locally; ready for the 10-07 human-verify checkpoint to confirm live resolution of `nocturna-avatars.site/{slug}` and the `/e/{slug}` -> `/{slug}` redirect after deploy.
- No blockers. This plan had no dependencies (Wave 1, parallel with everything) and touches no files shared with any other Phase 10 plan.

---
*Phase: 10-editors-section-integration*
*Completed: 2026-07-30*
