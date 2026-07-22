# Phase 4: Settings Migration + Name Resolution - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-22
**Phase:** 04-settings-migration-name-resolution
**Areas discussed:** Settings page composition, Name display treatment, Unknown/stale ID handling, Live vs render-only resolution

---

## Settings page composition — layout

| Option | Description | Selected |
|--------|-------------|----------|
| One page, feature groups | Single scrolling page; role→tier mapping becomes an "Access" fieldset group; one Save | ✓ |
| Sub-tabs within Settings | Split into tabs (Access vs Bot config); new UI pattern + per-tab save story | |

**User's choice:** One page, feature groups.

## Settings page composition — old `/admin/settings` URL

| Option | Description | Selected |
|--------|-------------|----------|
| Redirect to shell section | 301/302 so old bookmarks land | |
| Retire it | Remove standalone route; shell section is the only Settings URL | ✓ |
| Keep both | Leave `/admin/settings` serving too | |

**User's choice:** Retire it.
**Notes:** The 403-handler special-case on the `/admin/settings` path must be repointed to the new section route.

---

## Name display treatment — single field

| Option | Description | Selected |
|--------|-------------|----------|
| Name + ID beneath | `#channel`/`@role` + raw ID beneath, minimal | |
| Name + type/color cue + ID | Adds channel-type icon and/or role color swatch; bot must push type/color | ✓ |

**User's choice:** Name + type/color cue + ID.

## Name display treatment — role_list fields

| Option | Description | Selected |
|--------|-------------|----------|
| One chip per role | Each ID renders as its own readable @role chip; edit stays comma-separated IDs | ✓ |
| Inline names, ID line beneath | `@A, @B, @C` inline with raw ID list beneath | |

**User's choice:** One chip per role.

---

## Unknown / stale ID handling — per field

| Option | Description | Selected |
|--------|-------------|----------|
| Show ID + 'unresolved' flag | Raw ID + muted bilingual "name unavailable" marker; never blocks save | ✓ |
| Show ID only, silent | Just the raw ID, no marker | |

**User's choice:** Show ID + 'unresolved' flag.

## Unknown / stale ID handling — cache-not-ready vs deleted

| Option | Description | Selected |
|--------|-------------|----------|
| Distinguish them | Section-level "names loading — bot syncing" hint from cache freshness; avoids false "deleted" | ✓ |
| Treat the same | Any missing row shows the same per-field fallback regardless of cause | |

**User's choice:** Distinguish them.

---

## Live vs render-only resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Render-only (server join) | Names resolve server-side at render; new ID shows name after save+reload | |
| Live (client-side lookup) | Ship id→name cache to browser (Alpine); name updates instantly on type/paste | ✓ |

**User's choice:** Live (client-side lookup).

---

## Claude's Discretion

- Exact name-cache table schema and column names.
- Bot-side push cadence/triggers (startup snapshot, periodic loop, and/or guild
  channel/role create-update-delete events) — must use the shared-sqlite pattern only.
- Whether to reuse the existing heartbeat freshness row or add a dedicated push timestamp.
- Chip / swatch / icon styling within the variant-A visual language.
- Placement of the "Access" group among the feature groups.

## Deferred Ideas

- Guild-populated channel/role dropdown pickers (FUT-01) — deferred; this phase adds
  readable names on the existing raw-ID inputs, not pickers.
