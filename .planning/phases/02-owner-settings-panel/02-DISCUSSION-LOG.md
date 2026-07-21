# Phase 2: Owner Settings Panel - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 2-owner-settings-panel
**Areas discussed:** Submission model, Save & error atomicity, TZ & role-list fields, Discoverability & copy, all_for_ui metadata, Owner/editor auth

---

## Submission model

| Option | Description | Selected |
|--------|-------------|----------|
| Server-rendered POST | Plain HTML form → POST → server re-renders whole page with banner (design-spec default) | |
| Alpine.js fetch/JSON | Alpine posts JSON via fetch(), inline banner/field errors, no full reload — mirrors the existing editor surface | ✓ |

**User's choice:** Alpine.js fetch/JSON
**Notes:** Chosen for consistency with the existing editor app. Implies GET renders values server-side and Alpine hydrates + saves via fetch (mirrors editor_page → editor.html).

---

## Save & error atomicity

| Option | Description | Selected |
|--------|-------------|----------|
| Atomic all-or-nothing | Validate every field first; if any invalid, write nothing and return all errors at once; persist all only when clean | ✓ |
| Per-field independent save | Each field saves on its own; valid fields persist, only the bad field is flagged | |
| Save-all, first error only | One save, but stop at first invalid field and show only that error | |

**User's choice:** Atomic all-or-nothing
**Notes:** Safest reading of PANEL-03 ("rejected before any write"); owner sees every problem in one pass. Handler must collect errors per-field rather than relying on settings.set's first-failure raise.

---

## TZ & role-list fields

| Option | Description | Selected |
|--------|-------------|----------|
| TZ: `<select>` of IANA zones | Dropdown from zoneinfo.available_timezones(), current value pre-selected | ✓ |
| TZ: validated text input | Plain text; server rejects unresolvable zones | |
| Role lists: comma-separated text | One input holding "123, 456"; matches config.py parsing + validator | ✓ |
| Role lists: repeatable add/remove rows | Each ID its own input with +/− (Alpine array) | |

**User's choice:** TZ `<select>` of IANA zones; role lists as comma-separated text field
**Notes:** Repeatable rows judged over-built for v1 (guild dropdown is the real v2 answer, POLISH-01).

---

## Discoverability & copy

| Option | Description | Selected |
|--------|-------------|----------|
| Owner-only link on dashboard | `⚙ Ajustes / Settings` link on editor page, rendered only when is_owner; route still gated by require_owner | ✓ |
| Standalone URL only | No UI link; owner navigates to /admin/settings directly | |
| Copy: Bilingual ES–EN | Match the house style used throughout the app | ✓ |
| Copy: English-only | Owner-only technical editor, English only | |
| Copy: Spanish-only | Owner-facing, Spanish-first | |

**User's choice:** Owner-only dashboard link + Bilingual ES–EN copy
**Notes:** Route remains gated by require_owner regardless of link visibility; link visibility driven by an is_owner flag in the editor_page template context.

---

## all_for_ui metadata

| Option | Description | Selected |
|--------|-------------|----------|
| Extend all_for_ui() | Add structured render metadata (min/max, options, label) to the schema descriptor and surface it; single source of truth | ✓ |
| Panel derives it | Leave all_for_ui() untouched; route derives TZ options, hardcodes/omits int min-max, maps labels panel-side | |

**User's choice:** Extend all_for_ui()
**Notes:** Additive change to the completed/tested Phase-1 module; avoids drift between validation bounds and the form. tests/test_settings.py all_for_ui assertions must be updated.

---

## Owner/editor auth

| Option | Description | Selected |
|--------|-------------|----------|
| Owner has editor role | Owner logs in through existing OAuth (editor-role gate), require_owner narrows to discord_id; no login change | ✓ |
| Make owner login independent | Modify login so the owner is admitted by discord_id even without the editor role | |

**User's choice:** Owner has editor role (confirmed assumption)
**Notes:** No change to the login gate. Fallback (independent owner login) noted as deferred if the owner ever stops holding the editor role.

---

## Claude's Discretion

- Exact route/template file names and Jinja2 structure (mirror editor.html conventions incl. `?v=<mtime>` cache-buster).
- Precise multi-error collection mechanism in POST (no partial write is the only hard constraint).
- Internal shape of the all_for_ui() metadata extension (dataclass fields vs computed dict), schema staying single source of truth.
- Whether POST writes only changed fields or all fields (idempotent upsert; either is fine).
- Bilingual copy wording.

## Deferred Ideas

- Guild-populated channel/role dropdowns → v2 (POLISH-01).
- Making owner login independent of the editor role → only if the owner ever stops holding it (D-11 fallback).
- Editing secrets/structural values, ops console/monitoring, multi-admin, live interval hot-swap → out of scope permanently.
