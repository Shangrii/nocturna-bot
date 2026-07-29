# Phase 10: Editors Section Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-29
**Phase:** 10-editors-section-integration
**Areas discussed:** Integration depth, Editor sidebar view, Editor entry + access, Scope boundaries, Vanity URLs, Editor polish

---

## Integration depth (shell chrome for the editor page)

| Option | Description | Selected |
|--------|-------------|----------|
| Full shell wrap | editor.html extends _dashboard_base.html; two-pane editor becomes content block; most uniform, editor.css/dashboard.css must coexist | ✓ |
| Sidebar rail only | Add just the sidebar rail; keep editor's own topbar/editor.css/fonts | |
| Reachability only | Keep editor.html standalone; formalize as a labeled shell section/route | |

**User's choice:** Full shell wrap
**Notes:** Chose the most complete integration despite the editor.css↔dashboard.css reconciliation cost.

---

## Editor sidebar view (what an editor sees inside the shell)

| Option | Description | Selected |
|--------|-------------|----------|
| Full sidebar, locked | All 7 operational sections with 🔒 + Editor section unlocked; identical shell to owner/Manager (D-14/D-15) | ✓ |
| Editor-only sidebar | Show only the Editor section for editor-tier users; cleaner but breaks uniform-shell promise | |

**User's choice:** Full sidebar, locked
**Notes:** Uniform "everyone sees the same shell" model wins; editor clicking a locked item hits forbidden.html.

---

## Editor entry + access (nav promotion + who can reach it)

| Option | Description | Selected |
|--------|-------------|----------|
| 8th section, editor-only | Promote bolt-on .editor-link to a data-driven sections[] entry tier:'editor'; editor-role users only | ✓ |
| 8th section, owner too | Same promotion but owner can also open it (needs empty/preview state for an owner w/o editors.json entry) | |
| Keep bolt-on link | Leave the separate .editor-link block as-is | |

**User's choice:** 8th section, editor-only
**Notes:** Honors Phase 3 additive-tier rule (Manager without editor role gets no editor page).

---

## Scope boundaries (what to confirm OUT of scope)

| Option | Description | Selected |
|--------|-------------|----------|
| Vanity URLs deferred | Keep vanity URLs deferred to their own phase/backlog | |
| Counter app untouched | Confirm counter_app.py stays untouched | |
| Editor internals frozen | Confirm block-editor/upload/OAuth stay unchanged | |

**User's choice:** "none of them, I want full experience"
**Notes:** Pivotal answer — reversed the out-of-scope framing. The owner wants Phase 10 to deliver the full editor experience, pulling every candidate INTO scope. Triggered the two follow-up questions below.

---

## Vanity URLs (newly in-scope — follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Slug = vanity URL, redirect old | Editor's chosen slug becomes /{slug}; old/long links 301-redirect; reuses resolve_slug | ✓ |
| Slug = vanity URL, hard cut | New /{slug} only; old URLs 404 | |
| Separate vanity field | Distinct vanity handle separate from page slug; more UI + new field | |

**User's choice:** Slug = vanity URL, redirect old
**Notes:** Backward-compatible; example URL the owner has in mind: nocturna-avatars.site/shangri.

---

## Editor polish (newly in-scope — follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Match dashboard look | Visual consistency with dashboard.css tokens/topbar/type; workflow intact | |
| Match + UX cleanups | Visual consistency AND targeted UX improvements (save/publish clarity, upload feedback, mobile), each defined in UI-SPEC; behavior guarded (SC2 parity) | ✓ |
| Let UI-SPEC decide | Defer polish scope entirely to /gsd:ui-phase | |

**User's choice:** Match + UX cleanups
**Notes:** Broadens the phase; exact changes to be enumerated/approved in the UI-SPEC pass, with the SC2 workflow-parity guard (OAuth/save/uploads behavior unchanged).

---

## Claude's Discretion

- editor.css/dashboard.css reconciliation strategy
- Sidebar section ordering (editor entry placement) and nav wording
- Exact UX-cleanup change list (proposed in the UI-SPEC pass for owner approval)

## Deferred Ideas

None — the owner chose the full-experience release and pulled every candidate into Phase 10.
Standing PROJECT.md Out-of-Scope items (multi-guild, secret editing, log viewer, Overview
quick actions) remain out and were not raised.

## Scope-expansion note

Phase 10 grew beyond the roadmap's "lowest-risk integration" framing. Bookkeeping the
planner/transition must handle: add REQUIREMENTS EDIT-02 (vanity URLs), soften EDIT-01/SC2
from "unchanged" to workflow-parity-with-defined-polish, and update the ROADMAP Phase 10
goal/success-criteria to the three deliverables (shell integration, vanity URLs, polish).
