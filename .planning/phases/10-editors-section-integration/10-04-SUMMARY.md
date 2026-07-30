---
phase: 10-editors-section-integration
plan: 04
subsystem: ui
tags: [jinja2, sidebar, tier-gating, dashboard-shell]

# Dependency graph
requires:
  - phase: 10-01
    provides: RED tests defining the target shell/sidebar behavior (test_editor_page_renders_in_shell is 10-05's gate, not this plan's)
  - phase: 10-03
    provides: --accent-editor CSS token in dashboard.css, referenced by the new sections[] entry
provides:
  - Editor promoted to a uniform, data-driven 8th sidebar section (sections[] entry, tier "editor")
  - Single widened `unlocked` Jinja boolean expression (no if/elif chain) covering owner/manager/editor tiers
  - Bolt-on {% if roles.is_editor %}<div class="editor-link">...{% endif %} block deleted
  - Topbar's unconditional, latently-buggy "Back to editor" link removed
  - Bottom-of-nav separator preserved by migrating dashboard.css's border-top rule from `.side .editor-link` onto `.side .nav-item:last-child`
affects: [10-05, 10-06, 10-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sidebar sections[] list + single unlocked boolean expression is the sole tier-lock mechanism; new tiers are added as an additional `or` clause, never an if/elif chain"

key-files:
  created: []
  modified:
    - app/templates/_sidebar.html
    - app/templates/_dashboard_base.html
    - app/static/dashboard.css

key-decisions:
  - "Migrated the bottom-of-nav separator CSS rule from the now-deleted `.side .editor-link` wrapper selector onto `.side .nav-item:last-child` (dashboard.css) rather than reintroducing a wrapper div in the template — the separator now follows whichever section is structurally last in sections[] with zero extra markup, satisfying the plan's 'inline/utility class on the last entry' option without a new class"

patterns-established:
  - "Adding a new tiered sidebar section = one sections[] entry + one `or` clause on the shared `unlocked` expression; no other template change needed"

requirements-completed: [EDIT-01]

# Metrics
duration: 6min
completed: 2026-07-30
---

# Phase 10 Plan 04: Editor Sidebar Section Promotion Summary

**Editor promoted from a bolt-on `{% if roles.is_editor %}` link into a uniform 8th `sections[]` entry (tier "editor", accent `var(--accent-editor)`) sharing the same server-rendered lock predicate as the other 7 sections; the topbar's unconditional, 403-prone "Back to editor" link is removed.**

## Performance

- **Duration:** ~6 min (commit-to-commit)
- **Started:** 2026-07-30T12:07-06:00 (after 10-02 completion)
- **Completed:** 2026-07-30T12:11:33-06:00
- **Tasks:** 2
- **Files modified:** 3 (2 planned + 1 deviation: dashboard.css)

## Accomplishments
- `_sidebar.html`'s `sections[]` list now has 8 entries; Editor sits last (position 8, after Settings) with `tier: "editor"`, label "Editor", icon "✎", `accent: var(--accent-editor)`, `route: /editor`.
- The single `unlocked` Jinja expression gained one `or` clause — `(section.tier == "editor" and roles.is_editor)` — no if/elif chain introduced, matching the existing owner/manager pattern exactly.
- The bolt-on `{% if roles.is_editor %}<div class="editor-link">...{% endif %}` block is fully deleted; `grep -c editor-link app/templates/_sidebar.html` returns 0.
- Locked "Editor" nav item still links to the real `/editor` route (no disabled/`#` variant) — a non-editor click reaches the existing forbidden.html 403 dead-end (D-16, unchanged, gate lives in 10-02's route code).
- `_dashboard_base.html`'s unconditional `<a class="btn ghost" href="/editor">Volver al editor · Back to editor</a>` is deleted; the topbar now collapses to wordmark + spacer + logout, identical to every other shell page. `git diff` confirms a single-line deletion, no structural change.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add the 8th editor sections[] entry with a uniform is_editor lock branch** - `cdade54` (feat)
2. **Task 2: Remove the unconditional "Back to editor" topbar link** - `3a1415c` (fix)

**Plan metadata:** (this commit)

## Files Created/Modified
- `app/templates/_sidebar.html` - 8th `sections[]` entry (tier "editor"), widened `unlocked` expression, bolt-on `.editor-link` block removed
- `app/templates/_dashboard_base.html` - unconditional "Back to editor" topbar link removed
- `app/static/dashboard.css` - `.side .editor-link` separator selector renamed to `.side .nav-item:last-child` (deviation, see below)

## Decisions Made
- Preserved the bottom-of-nav visual separator by retargeting the existing CSS rule's selector (`.side .editor-link` → `.side .nav-item:last-child`) instead of wrapping the new last `sections[]` entry in a div — zero new markup, and the separator now automatically follows whichever section is structurally last, which is more maintainable than a hardcoded wrapper.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migrated the orphaned `.side .editor-link` CSS selector**
- **Found during:** Task 1 (deleting the bolt-on `.editor-link` wrapper div)
- **Issue:** `dashboard.css` had a `.side .editor-link { margin-top; padding-top; border-top }` rule providing the bottom-of-nav separator. Deleting the template's wrapper div (per the plan's explicit instruction) would silently orphan this CSS rule, losing the visual separator the plan's own acceptance criteria requires to be preserved.
- **Fix:** Renamed the CSS selector from `.side .editor-link` to `.side .nav-item:last-child` in `app/static/dashboard.css` — the plan itself names this exact fallback ("e.g. a `.nav-item:last-child` rule ... coordinate with the CSS in 10-03 if a rule move is needed"). No new class introduced; the separator now attaches to whichever `.nav-item` is structurally last.
- **Files modified:** `app/static/dashboard.css` (not in the plan's `files_modified` frontmatter list, but explicitly anticipated by the plan's own task instructions)
- **Verification:** Full test suite (888 passed, 1 pre-existing RED unrelated to this plan); manual grep confirms no remaining `.editor-link` references in either the template or the stylesheet.
- **Committed in:** `cdade54` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug/data-loss prevention, explicitly anticipated by the plan's own instructions)
**Impact on plan:** Necessary to satisfy the plan's own "separator must be preserved" acceptance criterion. No scope creep — the plan text itself named this exact CSS selector move as the expected fallback.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Editor is now a fully data-driven, uniformly tier-gated 8th sidebar section; 10-05 (editor.html shell wrap) and 10-06/10-07 can build on this without further sidebar changes.
- `test_editor_page_renders_in_shell` remains the one intentionally-RED test in the suite (888 passed / 1 RED) — this is 10-05's responsibility (wrapping `editor.html` with `_dashboard_base.html`), not a regression introduced here.
- Visual confirmation of lock states (editor sees Editor unlocked + 7 locked; owner/Manager-without-editor sees Editor 🔒) is deferred to the 10-07 human-verify checkpoint per this plan's own `<verification>` section.

## Self-Check: PASSED
- FOUND: app/templates/_sidebar.html (8th sections[] entry present, editor-link block absent)
- FOUND: app/templates/_dashboard_base.html (Back to editor link absent)
- FOUND: app/static/dashboard.css (.side .nav-item:last-child rule present)
- FOUND: cdade54 (git log)
- FOUND: 3a1415c (git log)

---
*Phase: 10-editors-section-integration*
*Completed: 2026-07-30*
