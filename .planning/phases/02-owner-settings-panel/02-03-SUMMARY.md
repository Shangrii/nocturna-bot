---
phase: 02-owner-settings-panel
plan: 03
subsystem: ui
tags: [jinja2, alpine.js, fastapi-templates, css]

# Dependency graph
requires:
  - phase: 02-owner-settings-panel (plan 02-01)
    provides: "core/settings.py::all_for_ui() render metadata (label/min/max/options), validate_only()"
  - phase: 02-owner-settings-panel (plan 02-02)
    provides: "require_owner dependency in app/deps.py"
provides:
  - "app/templates/settings.html — SSR + Alpine-hydrate settings form rendering all 7 type_tags with a per-field inline-error surface and JSON save() client"
  - "editor.html owner-only ⚙ Ajustes · Settings link (is_owner-guarded, D-12)"
  - "editor.css .field-error / .field--invalid inline validation classes"
affects: [02-04-routes-plan, owner-settings-panel-post-route]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "settings.html mirrors editor.html's single-quoted x-data hydrate idiom exactly, swapping entry|tojson for groups|tojson and editorApp for settingsApp"
    - "Client-side bilingual group-name lookup table (groupLabel()) since all_for_ui() groups are keyed by plain schema group id, not a bilingual label"
    - "Per-field errors map (save() populates BOTH a toast banner and errors{KEY:reason}) — first per-field error UI in this codebase, built fresh per D-03's JSON contract"

key-files:
  created:
    - app/templates/settings.html
    - tests/test_settings_template.py
  modified:
    - app/templates/editor.html
    - app/static/editor.css

key-decisions:
  - "Added a client-side groupLabel() bilingual lookup table (gallery/reviews/reminders/jinxxy/meetings/forum) because all_for_ui()'s group field is the plain schema group id, not a bilingual string — the plan/UI-SPEC both require a bilingual legend"
  - "Rule 1 fix: added input[type=\"number\"] to editor.css's existing text-input selector so int_range fields (this phase's only new field type needing it) render with the app's dark-theme chrome instead of unstyled browser defaults"

requirements-completed: [PANEL-02]

# Metrics
duration: 25min
completed: 2026-07-21
---

# Phase 2 Plan 3: Settings Form UI Summary

**New `settings.html` renders all 7 typed settings controls (SSR + Alpine hydrate, single-quoted `x-data='settingsApp(...)'`) with a fresh per-field inline-error surface and a `fetch('/admin/settings')` JSON save client; `editor.html` gains an owner-only `⚙ Ajustes · Settings` link and `editor.css` gains the `.field-error`/`.field--invalid` classes.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-21 (worktree execution)
- **Completed:** 2026-07-21
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `app/templates/settings.html`: mirrors `editor.html`'s doctype/head/topbar/toast/script-ordering exactly (3-family font subset only, no curated theme fonts, no Sortable.min.js); groups render as `<fieldset class="theme-group">` in `all_for_ui()` payload order with bilingual `<legend>` labels
- All 7 `type_tag`s render their UI-SPEC-prescribed control: `snowflake` (numeric text + pattern), `role_list` (comma-separated text), `int_range` (`<input type="number" :min :max>`), `timezone` (`<select>` over `options`), `free_string` (text), `url` (`<input type="url">`), `lang` (fixed es/en `<select>`)
- `settingsApp(initial)` flattens the grouped payload into a `values` map for `x-model` binding while keeping `groups` intact for rendering metadata (label/hint/min/max/options); `save()` posts JSON, branches on `{ok,message}` vs `{errors:{KEY:reason}}`, and populates BOTH a toast banner and a per-field `errors` map
- `tests/test_settings_template.py`: 6 new tests render the template through the app's real Jinja2 environment (`app.main.templates`) with a payload from a real `settings.all_for_ui()` call over a tmp DB; assert the single-quoted hydrate, the `fetch`/JSON contract, the timezone `<select>`/int_range `type="number"` controls, the inline-error classes, vendored-defer Alpine with no Sortable reference, and secret absence
- `editor.html`: `{% if is_owner %}`-guarded `<a class="btn btn--ghost" href="/admin/settings">⚙ Ajustes · Settings</a>` inserted between the unpublish button and the sign-out link
- `editor.css`: appended `.field--invalid input, .field--invalid select { border-color: var(--red-on-ink); }` and `.field-error { ... color: var(--red-on-ink); }` verbatim from the UI-SPEC's New Elements block
- Full repo suite: 630 passed (up from 620 baseline after 02-01/02-02)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create settings.html (SSR + Alpine hydrate, typed fields, per-field errors)** - `bf72bcf` (feat)
2. **Task 2: Owner-only editor link + inline-error CSS** - `5ba161e` (feat)

**Plan metadata:** (this SUMMARY commit, follows)

## Files Created/Modified
- `app/templates/settings.html` - NEW: SSR + Alpine-hydrate settings form, 7 typed controls, per-field error surface, `save()` JSON client
- `tests/test_settings_template.py` - NEW: 6-test render smoke suite (hydrate, fetch contract, controls, error CSS classes, vendored-Alpine ordering, secret absence)
- `app/templates/editor.html` - owner-only `⚙ Ajustes · Settings` link, `is_owner`-guarded
- `app/static/editor.css` - `.field-error`/`.field--invalid` classes; `input[type="number"]` added to the existing text-input selector

## Decisions Made
- Built a client-side `groupLabel()` bilingual lookup (gallery→"Galería · Gallery", etc.) because `all_for_ui()`'s `group` field is the plain schema group id, not a bilingual string, and both the plan's task action and the UI-SPEC explicitly require a bilingual `<legend>`
- Kept `POST /admin/settings` wiring entirely out of scope — this plan only builds the client against the already-locked D-03 JSON contract; the route itself is 02-04's responsibility

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added `input[type="number"]` to editor.css's text-input selector**
- **Found during:** Task 2 (Owner-only editor link + inline-error CSS)
- **Issue:** `editor.css`'s existing input selector (`input[type="text"], input[type="url"], textarea, select`) did not include `input[type="number"]`. Since Task 1's `int_range` fields render as `<input type="number">`, they would have fallen back to unstyled browser-default (light background) inputs against this app's dark theme — a visibly broken control for a field type this very phase introduces.
- **Fix:** Added `input[type="number"]` to the existing selector so number inputs share the same dark-ink background, border, padding, and touch-target sizing as every other text control.
- **Files modified:** `app/static/editor.css`
- **Verification:** `grep 'input\[type="number"\]' app/static/editor.css` finds the updated selector; full suite (630 tests) still green.
- **Committed in:** `5ba161e` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug/visual-correctness fix)
**Impact on plan:** Necessary for the int_range control this phase itself introduces to render correctly against the existing dark-theme chrome. No scope creep — no new classes or files beyond what the plan already specified for `editor.css`.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`settings.html` is ready for 02-04 to wire the `GET`/`POST /admin/settings` routes:
- `GET /admin/settings` needs only to call `settings.all_for_ui()` and render
  `templates.TemplateResponse(request, "settings.html", {"groups": groups, "asset_v": asset_v})` —
  the template's `x-data='settingsApp({{ groups | tojson }})'` hydrate contract is already built
  and tested against a real `all_for_ui()` payload shape.
- `POST /admin/settings` needs to satisfy the `{ok:true, message}` / `{errors:{KEY:reason}}`
  JSON contract that `save()` already branches on (this plan's client is built and tested
  against that exact shape).
- `editor_page`'s Jinja context needs to supply `is_owner` for the new topbar link to
  conditionally render (currently absent from context — the link exists in the template guarded
  by `{% if is_owner %}` but is falsy/undefined until 02-04 wires it).
- No blockers. Full suite (630 tests) green; the isolated `tests/test_settings_template.py`
  suite (6 tests) covers this plan's entire surface independent of routing/auth.

## Self-Check: PASSED

- FOUND: app/templates/settings.html (contains `x-data='settingsApp(`, `fetch('/admin/settings'`, `type="number"`, `class="field-error"`, `field--invalid`)
- FOUND: tests/test_settings_template.py (6 tests, all passing)
- FOUND: app/templates/editor.html (contains `{% if is_owner %}` guard + `/admin/settings` link)
- FOUND: app/static/editor.css (contains `.field-error`, `.field--invalid`, `var(--red-on-ink)`, `input[type="number"]`)
- FOUND commits bf72bcf, 5ba161e in `git log --oneline --all`
- `pytest tests/test_settings_template.py -x` → 6 passed
- `pytest` (full repo suite) → 630 passed

---
*Phase: 02-owner-settings-panel*
*Completed: 2026-07-21*
