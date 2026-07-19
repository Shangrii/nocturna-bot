# Bot Settings Panel — Design Spec

**Date:** 2026-07-19
**Repo:** `nocturna-bot`
**Status:** Approved design, pending spec review → implementation plan.

## Goal

Give the Nocturna bot owner a web panel to view and edit the bot's **safe operational
settings** (channels, staff roles, poll intervals, timezone, meeting/whisper tuning,
feature toggles) without SSHing into cinema and hand-editing `.env` — like a professional
Discord bot dashboard, scoped to the single Nocturna guild and to the owner only.

## Background — the current config surface

All config lives in one file, `config.py` (~50 `os.getenv` reads, sourced from `.env`).
It is NOT scattered across files; the pain is (a) volume and (b) no way to see/change it
without shell access. Splitting the surface by risk:

- **Secrets (never in the panel — stay in `.env`):** `BOT_TOKEN`, `GITHUB_PAT`,
  `JINXXY_API_KEY`, `SESSION_SECRET`, `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`.
- **Structural (set once, high blast radius — stay in `.env`, not editable in v1):**
  `GUILD_ID`, `ROLE_MODERATOR_ID`, `DISCORD_USER_ID`, `WEBSITE_REPO`, `WEBSITE_BRANCH`,
  all `WEBSITE_*_JSON` + `WEBSITE_*_IMAGE_DIR`, `DB_PATH`, `RECORDINGS_DIR`, `NOTES_FILE`,
  `NOTIFY_*`, `ENCODER_CONTROL_*`, `WHISPER_DEVICE`, `WHISPER_COMPUTE`, `WHISPER_THREADS`,
  `OLLAMA_HOST`, `EDITOR_APP_BASE_URL`, `DISCORD_OAUTH_REDIRECT_URI`.
- **Safe tunables (v1 panel scope):** see the enumerated list below.

## Decisions (locked)

1. **v1 = settings editor** (not an ops console / monitoring — those are out of scope).
2. **Scope = safe tunables only.** Structural + secrets stay in `.env`.
3. **Access = owner only.** The panel is gated to `session.discord_id == DISCORD_USER_ID`.
   The existing editor admin app (`require_editor`) is a separate surface, untouched.
4. **Shared sqlite is the channel.** The bot and the FastAPI admin app are two processes
   that already share `DB_PATH`. The panel WRITES settings to a table; the bot READS them.
   No IPC/socket/signal is built.
5. **Reload = read-at-use.** Migrated settings are read at the point of use (a staff gate
   re-reads its role list per reaction; a poll re-reads its channel each cycle), so a saved
   change takes effect on the next use. *Accepted nuance:* changing a `@tasks.loop` INTERVAL
   applies on the next cycle / bot restart, not instantly; all other values apply on next read.

## Safe tunables in v1 scope (enumerated)

| Feature | Settings |
|---------|----------|
| Gallery | `PHOTO_CHANNEL_ID`, `GALLERY_STAFF_ROLE_IDS` |
| Reviews | `REVIEWS_CHANNEL_ID`, `REVIEWS_STAFF_ROLE_IDS` |
| Reminders | `REMINDERS_TZ`, `REMINDERS_STAFF_ROLE_IDS`, `REMINDERS_CATCHUP_GRACE_HOURS` |
| Jinxxy | `JINXXY_ANNOUNCE_CHANNEL_ID`, `JINXXY_POLL_HOURS`, `JINXXY_STAFF_ROLE_IDS`, `JINXXY_STORE_URL`, `WEBSITE_BASE_URL` |
| Meetings | `MEETINGS_FORUM_ID`, `MEETING_LANG`, `WHISPER_PROMPT`, `WHISPER_MODEL`, `OLLAMA_MODEL` |
| Forum / Encoding | `FORUM_CHANNEL_ID`, `ENCODING_CHANNEL_ID` |

Notes: the staff-role lists keep their **fallback-to-`GALLERY_STAFF_ROLE_IDS`-when-empty**
semantic (REVIEWS/REMINDERS/JINXXY). `WHISPER_MODEL` / `OLLAMA_MODEL` are editable but the
chosen model must already be available on the host — the field hint says so; an unknown model
is a runtime concern, not a validation error. The exact final list is confirmable during
planning, but this is the intended v1 set.

## Architecture — two deliverables

### Phase A — Config store + consolidation (the prerequisite; most of the work/risk)

- **`core/settings.py`** (new) — the single source of truth for *what* is tunable. For each
  setting: `key`, type, default, validation, and owning feature. Public API:
  - `get(key)` → returns the stored value, falling back to the `.env`/default seed if absent.
  - `set(key, value)` → validates against the schema, then writes to the `settings` table.
  - `all_for_ui()` → the grouped, typed descriptor list the panel renders from.
  - A pure module (stdlib + sqlite via `core/db.py`), unit-testable, matching the
    `core/store_sync.py` / `core/editors_model.py` precedent.
- **`settings` table** in the existing sqlite (`key TEXT PRIMARY KEY, value TEXT`, value
  JSON-encoded), created via the repo's `CREATE TABLE IF NOT EXISTS` idiom in `core/db.py`.
- **`config.py` refactor** — the safe-tunable constants stop being frozen at import; each is
  read through `settings.get(...)`. **Secrets and structural values stay exactly as they are**
  (frozen from `.env`). Cog call sites that read a migrated constant at import time move to
  read-at-use (`settings.get('X')` where the value is consumed).
- **Idempotent seed / migration** — on startup, seed the `settings` table from the current
  `.env`/defaults for any key not already present. Behavior is byte-identical until the owner
  edits something. No destructive migration.

### Phase B — The panel (on the existing admin app)

- **`require_owner`** dependency (new, in `app/deps.py`) — session `discord_id` must equal
  `config.DISCORD_USER_ID`, else 403. Reuses the existing OAuth login + session middleware.
- **`GET /admin/settings`** — renders a form grouped by feature from `settings.all_for_ui()`,
  each field typed: channel/role IDs as validated number inputs, intervals as numbers, TZ as a
  select (or validated text), toggles as checkboxes, prompts as text. Secrets never appear.
- **`POST /admin/settings`** — validates every field server-side via `settings.set` (the schema
  is the gate), writes the table, re-renders with a success/error banner. An invalid value is
  rejected before any write, so the bot never reads a bad value.
- Channel/role **dropdowns populated from the guild via the bot token** are a later polish; v1
  uses validated ID inputs.

## Data flow

1. Owner logs in (Discord OAuth) → `require_owner` confirms `discord_id == DISCORD_USER_ID`.
2. Panel renders current values from `settings.all_for_ui()`.
3. Owner edits + saves → `settings.set` validates → writes the `settings` table.
4. The bot process, on its next relevant use (reaction gate, poll cycle, reminder tick), calls
   `settings.get(...)` and reads the new value from the shared sqlite. Loop-interval changes
   apply on the next cycle.

## Error handling

- `settings.set` raises a typed `SettingRejected(reason)` on invalid input; the panel maps it to
  an inline field error, writes nothing.
- `settings.get` never raises: a missing/corrupt row falls back to the `.env`/default seed so the
  bot always has a usable value.
- A non-owner hitting any `/admin/settings` route → 403 (no data leaked).

## Security

- One new trust gate (`require_owner`); the settings surface is owner-only.
- Secrets are never read into the panel, never rendered, never editable.
- Validation is load-bearing in `settings.set` (int ranges, ID shape `^\d{17,20}$`, TZ resolves
  via `zoneinfo.ZoneInfo`, enums/toggles constrained) — a crafted POST cannot store a value that
  would break a cog.
- Editing staff-role lists is a trust-boundary change, but only the owner can do it (accepted).

## Testing

- `core/settings.py`: `get`/`set` round-trip; per-type validation (accept valid, reject invalid
  ID/interval/TZ); fallback to default when unset; idempotent seed.
- Migrated cogs/config: a mocked store change is reflected at the read-at-use site (e.g. the staff
  gate honors a new role list; the Jinxxy poll reads a new announce channel).
- Panel: `require_owner` returns 403 for a non-owner and 200 for the owner; a valid POST persists;
  an invalid POST returns an error and writes nothing (mock the store).

## Out of scope (v1, YAGNI)

- Editing structural values or secrets.
- Guild-populated channel/role dropdowns (v1 = validated ID inputs).
- Ops console / monitoring / manual action triggers (sync now, view logs, manage reminders).
- Multi-guild, multi-admin, or a dedicated bot-admin role.
- Live loop-interval hot-swap (`change_interval`) — interval edits apply next cycle/restart.
