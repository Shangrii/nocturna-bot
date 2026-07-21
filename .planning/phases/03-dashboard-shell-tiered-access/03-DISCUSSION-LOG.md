# Phase 3: Dashboard Shell + Tiered Access - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 3-Dashboard Shell + Tiered Access
**Areas discussed:** Login & tier resolution, Role→tier mapping model, Overview data plumbing, Nav visibility & module stubs

---

## Login & tier resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Any mapped tier (Recommended) | OAuth callback resolves tier from role→tier mapping (plus owner ID); anyone resolving to a tier gets a session | ✓ |
| Any guild member | Any guild member gets a session; tier resolved per request | |
| Keep editor gate + owner bypass | Editors and owner only; Managers would need the editor role | |

**User's choice:** Any mapped tier

| Option | Description | Selected |
|--------|-------------|----------|
| Live re-check (Recommended) | Every protected request re-reads live guild roles via bot token; instant revocation | ✓ |
| Short TTL cache | Cache resolved tier ~60s in session | |
| Check at login only | Resolve once at OAuth callback | |

**User's choice:** Live re-check

| Option | Description | Selected |
|--------|-------------|----------|
| Union of tiers (Recommended) | Additive grants: Manager modules AND own editor page | ✓ |
| Highest tier only | Manager outranks editor; no editor page for dual-role users | |
| Manager includes editor | Strictly nested; every Manager gets a presentation page | |

**User's choice:** Union of tiers

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded ID bypass (Recommended) | DISCORD_USER_ID always resolves to owner tier; mapping cannot express/remove ownership; fails closed when unset | ✓ |
| Owner role + ID fallback | Mappable owner role with hardcoded fallback | |

**User's choice:** Hardcoded ID bypass

---

## Role→tier mapping model

| Option | Description | Selected |
|--------|-------------|----------|
| Settings-store keys (Recommended) | Two role-list keys in the validated settings store (manager_roles, editor_roles), seeded for byte-identical behavior | ✓ |
| Dedicated table | New role_tiers table per the db.py idiom | |

**User's choice:** Settings-store keys

| Option | Description | Selected |
|--------|-------------|----------|
| Multiple per tier (Recommended) | Each tier holds a role list | ✓ |
| One role per tier | Single snowflake field per tier | |

**User's choice:** Multiple per tier

| Option | Description | Selected |
|--------|-------------|----------|
| Raw ID fields (Recommended) | Role-ID inputs per tier like the v1 settings form; names in Phase 4; dropdowns deferred (FUT-01) | ✓ |
| Wait for Phase 4 names | Same fields, polish expectations deferred | |
| You decide | Claude picks layout during planning | |

**User's choice:** Raw ID fields

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, unify (Recommended) | has_editor_role reads editor_roles from the settings store; one source of truth | ✓ |
| No, keep separate | Editor app keeps ROLE_MODERATOR_ID; tier system uses its own key | |

**User's choice:** Yes, unify

---

## Overview data plumbing

| Option | Description | Selected |
|--------|-------------|----------|
| Heartbeat row (Recommended) | Bot loop writes heartbeat timestamp + latency; Online iff fresh | |
| Richer status block | Heartbeat plus uptime, guild member count, loaded cogs | ✓ |
| You decide | Claude picks minimal viable status fields | |

**User's choice:** Richer status block
**Notes:** User wants the fuller status view despite extra bot-side plumbing.

| Option | Description | Selected |
|--------|-------------|----------|
| Bot writes sync meta (Recommended) | Jinxxy poll records each run's outcome (timestamp, ok/error, product count); Phase 8 reuses it | ✓ |
| Placeholder until Phase 8 | 'Coming soon' tile; would soft-miss SHELL-02 | |

**User's choice:** Bot writes sync meta

| Option | Description | Selected |
|--------|-------------|----------|
| New activity_log table (Recommended) | Append-only table + helper called on notable cog events; Overview shows last ~10 | ✓ |
| Derive from existing tables | Merge existing tables into a pseudo-feed | |
| Minimal now | Status + last sync only in Phase 3 | |

**User's choice:** New activity_log table

| Option | Description | Selected |
|--------|-------------|----------|
| Load + Alpine poll (Recommended) | Server-render on load; Alpine fetch refreshes tiles ~30s | ✓ |
| Page load only | As-of load; manual reload | |

**User's choice:** Load + Alpine poll

---

## Nav visibility & module stubs

| Option | Description | Selected |
|--------|-------------|----------|
| Coming-soon stubs (Recommended) | Real routes with variant-A chrome and 'coming soon' bodies | ✓ |
| Hide until built | Only Overview + Settings in Phase 3 | |
| Stubs with real data peeks | Stubs plus read-only counts where data exists | |

**User's choice:** Coming-soon stubs

| Option | Description | Selected |
|--------|-------------|----------|
| Hidden entirely (Recommended) | Nav renders only granted sections | |
| Visible but locked | Every section shown, lock icon on ungranted ones | ✓ |

**User's choice:** Visible but locked (against recommendation — staff should see the full feature map)

| Option | Description | Selected |
|--------|-------------|----------|
| Straight to /editor (Recommended) | Editors land on the existing editor page; no shell until Phase 10 | |
| Shell with locked nav | Editors see the shell: locked sidebar + 'Editor' entry linking to /editor | ✓ |

**User's choice:** Shell with locked nav (against recommendation — consistent with visible-but-locked; previews Phase 10)

| Option | Description | Selected |
|--------|-------------|----------|
| Styled 403 page (Recommended) | 403 with a friendly in-shell bilingual page; locked nav links here | ✓ |
| Locks not clickable | Non-link locked items; raw 403 on direct URL | |
| You decide | Claude picks; 403 status + bilingual copy required | |

**User's choice:** Styled 403 page

---

## Claude's Discretion

- Heartbeat cadence, staleness threshold, activity-log retention, Overview tile layout
- Settings form layout for the mapping fields (consistent with v1 panel)
- Landing page per tier after login

## Deferred Ideas

- Short vanity URLs for editor pages (`nocturna-avatars.site/shangri`) — raised
  mid-discussion; new capability, candidate for Phase 10 or roadmap backlog.
