# Phase 1: Config Store + Consolidation - Context

**Gathered:** 2026-07-19
**Status:** Ready for planning
**Source:** Design spec (`docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md`) — approved; synthesized into CONTEXT during GSD bootstrap.

<domain>
## Phase Boundary

This phase delivers the **prerequisite** for the owner Settings Panel: a validated,
sqlite-backed config store plus the consolidation of `config.py`'s *safe tunables* to read
through it. It is the higher-risk half of the milestone (it touches how every migrated cog
reads its config) and must be **behavior-preserving** — byte-identical to current `.env`
behavior until the owner edits a value.

**In scope:**
- `core/settings.py` — the single source of truth for what is tunable (schema + get/set/all_for_ui).
- A `settings` table in the shared sqlite.
- Refactor `config.py` so *safe tunables* are read at-use via `settings.get`, while secrets and
  structural values stay frozen from `.env`.
- Idempotent seed/migration on startup.
- Decide + apply the shared-sqlite concurrency mode (bot reads + panel writes, two processes).

**Out of scope (this phase):** the web panel itself, `require_owner`, any HTTP route — those
are Phase 2. No new secrets or structural values become editable.

</domain>

<decisions>
## Implementation Decisions

### Config store module (`core/settings.py`)
- Pure module: stdlib + sqlite via `core/db.py`, unit-testable. Mirrors the
  `core/store_sync.py` / `core/editors_model.py` precedent (no discord.py / FastAPI imports).
- Public API is exactly three functions:
  - `get(key)` → stored value, else the `.env`/default seed. **Never raises** — a missing or
    corrupt row falls back to the seed so the bot always has a usable value.
  - `set(key, value)` → validates against the schema, then writes the `settings` table. Raises a
    typed `SettingRejected(reason)` on invalid input and writes nothing.
  - `all_for_ui()` → the grouped, typed descriptor list the Phase 2 panel renders from.
- The schema is the single declaration of each tunable: `key`, type, default, validation rule,
  and owning feature (group). This schema drives seeding, validation, and `all_for_ui()`.

### `settings` table
- Schema: `key TEXT PRIMARY KEY, value TEXT` where `value` is JSON-encoded.
- Created via the repo's `CREATE TABLE IF NOT EXISTS` idiom in `core/db.py` (new `init_settings()`
  function, called at startup — same pattern as `init_gallery_state` / `init_store_state` /
  `init_view_counts`). Do NOT fold it into `init_db()`.

### Validation (load-bearing in `settings.set`)
- Channel/role IDs: `^\d{17,20}$` (Discord snowflake shape).
- Intervals / grace hours: integer within a sane range (per-key bounds in the schema).
- Timezone: must resolve via `zoneinfo.ZoneInfo` (tzdata backs it on Windows/CI).
- Enums/toggles: constrained to the allowed set / boolean.
- `WHISPER_MODEL` / `OLLAMA_MODEL`: accepted as free strings — an unknown model is a runtime
  concern (field hint says "must already be available on the host"), NOT a validation error.
- A crafted POST must never store a value that would break a cog — validation is the gate.

### `config.py` refactor (behavior-preserving)
- The safe-tunable constants stop being frozen at import; each is read through `settings.get(...)`
  **at the point of use** (read-at-use). A staff gate re-reads its role list per reaction; a poll
  re-reads its channel each cycle → a saved change takes effect on next use.
- **Secrets and structural values stay exactly as they are** (frozen from `.env`): `BOT_TOKEN`,
  `GITHUB_PAT`, `JINXXY_API_KEY`, `SESSION_SECRET`, OAuth client id/secret, `GUILD_ID`,
  `ROLE_MODERATOR_ID`, `DISCORD_USER_ID`, `WEBSITE_*`, `DB_PATH`, `RECORDINGS_DIR`, `NOTES_FILE`,
  `NOTIFY_*`, `ENCODER_CONTROL_*`, `WHISPER_DEVICE/COMPUTE/THREADS`, `OLLAMA_HOST`,
  `EDITOR_APP_BASE_URL`, `DISCORD_OAUTH_REDIRECT_URI`.
- Cog call sites that read a migrated constant *at import time* move to read-at-use.
- The staff-role lists keep their fallback-to-`GALLERY_STAFF_ROLE_IDS`-when-empty semantic
  (REVIEWS / REMINDERS / JINXXY).

### Safe tunables in scope (the seed set)
| Feature | Keys |
|---------|------|
| Gallery | `PHOTO_CHANNEL_ID`, `GALLERY_STAFF_ROLE_IDS` |
| Reviews | `REVIEWS_CHANNEL_ID`, `REVIEWS_STAFF_ROLE_IDS` |
| Reminders | `REMINDERS_TZ`, `REMINDERS_STAFF_ROLE_IDS`, `REMINDERS_CATCHUP_GRACE_HOURS` |
| Jinxxy | `JINXXY_ANNOUNCE_CHANNEL_ID`, `JINXXY_POLL_HOURS`, `JINXXY_STAFF_ROLE_IDS`, `JINXXY_STORE_URL`, `WEBSITE_BASE_URL` |
| Meetings | `MEETINGS_FORUM_ID`, `MEETING_LANG`, `WHISPER_PROMPT`, `WHISPER_MODEL`, `OLLAMA_MODEL` |
| Forum / Encoding | `FORUM_CHANNEL_ID`, `ENCODING_CHANNEL_ID` |

The exact final list is confirmable during planning; this is the intended set.

### Seed / migration
- On startup, seed the `settings` table from the current `.env`/defaults for any key **not
  already present**. Idempotent — running twice is a no-op. No destructive migration. Behavior
  is byte-identical until the owner edits something.

### Concurrency (CONC-01 — DECIDE + APPLY in this phase)
- Two processes (bot + admin app) share one sqlite file; the panel adds writes from the second
  process. Current `core/db.py` opens a fresh connection per call with **no journal mode set**.
- **Proposed:** enable WAL journal mode on the shared sqlite so concurrent bot-read / panel-write
  do not raise "database is locked". Confirm the exact mechanism during planning (e.g. a
  one-time `PRAGMA journal_mode=WAL` — WAL is persistent per-database, so setting it once on the
  file is sufficient; verify interaction with the fresh-connection-per-call idiom and the
  `with conn:` transaction usage). This is a real decision the plan must resolve, not defer.

### Claude's Discretion
- Internal structure of the schema (dataclass vs dict-of-descriptors), the exact validation
  helper shapes, JSON encoding details, and how `config.py` exposes read-at-use (e.g. module
  `__getattr__` vs explicit getter functions vs helper) — pick the approach that best fits the
  existing codebase idioms and keeps call-site churn minimal and readable.
- How WAL is applied (init-time PRAGMA vs connection setup) — plan the least-invasive option.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design contract
- `docs/superpowers/specs/2026-07-19-bot-settings-panel-design.md` — the approved design spec;
  Phase A (this phase) is the "Config store + consolidation" section.

### Existing patterns to mirror
- `core/db.py` — the `init_*()` + `CREATE TABLE IF NOT EXISTS` idiom, fresh-connection-per-call,
  parameterized SQL, `with conn:` transactions. The `settings` table and `init_settings()` follow this.
- `core/store_sync.py`, `core/editors_model.py` — precedent for a pure, unit-testable `core/` module.
- `config.py` — the current ~50 `os.getenv` reads; the safe/structural/secret split is enumerated
  in the spec's "Background" section.

### Consumers to migrate (read-at-use call sites)
- `cogs/gallery.py`, `cogs/reviews.py`, `cogs/reminders.py`, `cogs/jinxxy.py`, `cogs/meeting.py`,
  `cogs/forum.py`, `cogs/encoding.py` — locate where each migrated constant is consumed.

</canonical_refs>

<specifics>
## Specific Ideas

- Follow the existing `_REMINDER_UPDATABLE` allowlist discipline: never interpolate a key/column
  name from a variable into SQL — the `settings` table is keyed by a validated key, values by `?`.
- The test precedent is strong (`tests/test_editors_model.py`, `tests/test_*` round-trip DB tests);
  `core/settings.py` should get the same treatment: get/set round-trip, per-type validation
  (accept valid, reject invalid ID/interval/TZ), fallback-to-default when unset, idempotent seed.
- A migrated-cog test should prove read-at-use: a mocked store change is reflected at the
  consumption site (staff gate honors a new role list; Jinxxy poll reads a new announce channel).

</specifics>

<deferred>
## Deferred Ideas

- The web panel, `require_owner`, and all HTTP routes → Phase 2.
- Guild-populated channel/role dropdowns → v2 (POLISH-01).
- Making structural values or secrets editable → out of scope (permanently, per spec).

</deferred>

---

*Phase: 01-config-store-consolidation*
*Context gathered: 2026-07-19 (synthesized from the approved design spec during GSD bootstrap)*
