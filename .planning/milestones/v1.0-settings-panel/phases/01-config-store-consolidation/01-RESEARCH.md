# Phase 1: Config Store + Consolidation - Research

**Researched:** 2026-07-19
**Domain:** SQLite-backed config store + Python config-module refactor (internal, codebase-grounded)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Config store module (`core/settings.py`)
- Pure module: stdlib + sqlite via `core/db.py`, unit-testable. Mirrors the
  `core/store_sync.py` / `core/editors_model.py` precedent (no discord.py / FastAPI imports).
- Public API is exactly three functions:
  - `get(key)` -> stored value, else the `.env`/default seed. **Never raises** - a missing or
    corrupt row falls back to the seed so the bot always has a usable value.
  - `set(key, value)` -> validates against the schema, then writes the `settings` table. Raises a
    typed `SettingRejected(reason)` on invalid input and writes nothing.
  - `all_for_ui()` -> the grouped, typed descriptor list the Phase 2 panel renders from.
- The schema is the single declaration of each tunable: `key`, type, default, validation rule,
  and owning feature (group). This schema drives seeding, validation, and `all_for_ui()`.

### `settings` table
- Schema: `key TEXT PRIMARY KEY, value TEXT` where `value` is JSON-encoded.
- Created via the repo's `CREATE TABLE IF NOT EXISTS` idiom in `core/db.py` (new `init_settings()`
  function, called at startup - same pattern as `init_gallery_state` / `init_store_state` /
  `init_view_counts`). Do NOT fold it into `init_db()`.

### Validation (load-bearing in `settings.set`)
- Channel/role IDs: `^\d{17,20}$` (Discord snowflake shape).
- Intervals / grace hours: integer within a sane range (per-key bounds in the schema).
- Timezone: must resolve via `zoneinfo.ZoneInfo` (tzdata backs it on Windows/CI).
- Enums/toggles: constrained to the allowed set / boolean.
- `WHISPER_MODEL` / `OLLAMA_MODEL`: accepted as free strings - an unknown model is a runtime
  concern (field hint says "must already be available on the host"), NOT a validation error.
- A crafted POST must never store a value that would break a cog - validation is the gate.

### `config.py` refactor (behavior-preserving)
- The safe-tunable constants stop being frozen at import; each is read through `settings.get(...)`
  **at the point of use** (read-at-use). A staff gate re-reads its role list per reaction; a poll
  re-reads its channel each cycle -> a saved change takes effect on next use.
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
  already present**. Idempotent - running twice is a no-op. No destructive migration. Behavior
  is byte-identical until the owner edits something.

### Concurrency (CONC-01 - DECIDE + APPLY in this phase)
- Two processes (bot + admin app) share one sqlite file; the panel adds writes from the second
  process. Current `core/db.py` opens a fresh connection per call with **no journal mode set**.
- **Proposed:** enable WAL journal mode on the shared sqlite so concurrent bot-read / panel-write
  do not raise "database is locked". Confirm the exact mechanism during planning (e.g. a
  one-time `PRAGMA journal_mode=WAL` - WAL is persistent per-database, so setting it once on the
  file is sufficient; verify interaction with the fresh-connection-per-call idiom and the
  `with conn:` transaction usage). This is a real decision the plan must resolve, not defer.

### Claude's Discretion
- Internal structure of the schema (dataclass vs dict-of-descriptors), the exact validation
  helper shapes, JSON encoding details, and how `config.py` exposes read-at-use (e.g. module
  `__getattr__` vs explicit getter functions vs helper) - pick the approach that best fits the
  existing codebase idioms and keeps call-site churn minimal and readable.
- How WAL is applied (init-time PRAGMA vs connection setup) - plan the least-invasive option.

### Deferred Ideas (OUT OF SCOPE)

- The web panel, `require_owner`, and all HTTP routes -> Phase 2.
- Guild-populated channel/role dropdowns -> v2 (POLISH-01).
- Making structural values or secrets editable -> out of scope (permanently, per spec).
</user_constraints>

## Summary

This phase is an internal refactor of a well-patterned codebase, not a new-technology
integration. Everything needed is either already in the repo (`core/db.py`'s `init_*()` idiom,
`core/store_sync.py`'s pure-module precedent, `core/editors_model.py`'s validation-exception
precedent) or in the Python 3.12 standard library (`sqlite3`, `json`, `re`, `zoneinfo`). **No new
third-party packages are required for this phase** — `tzdata` (zoneinfo backing) is already a
pinned dependency.

Three findings materially shape the plan:

1. **Every current safe-tunable read site is `config.X` attribute access, never `from config
   import X`.** A full grep of `cogs/` and `core/` confirms zero `from config import` statements
   anywhere in the codebase. This means a **module-level `__getattr__` (PEP 562) shim on
   `config.py`** is a drop-in mechanism — every existing call site (`config.PHOTO_CHANNEL_ID`,
   `config.REMINDERS_TZ`, etc.) becomes read-at-use automatically, with **zero call-site edits**
   required for the majority of sites. This is a stronger result than the phase description's
   "minimal call-site churn" — it's near-zero churn for straight reads.
2. **The existing test suite already monkeypatches `config` attributes directly**
   (`monkeypatch.setattr(config, "REMINDERS_STAFF_ROLE_IDS", [...], raising=False)` appears in
   6+ test files). Python attribute lookup checks the module's `__dict__` before falling back to
   `__getattr__`, so `monkeypatch.setattr` continues to work completely unmodified after the
   refactor — patched tests never touch `__getattr__` or the DB at all. This is a strong
   compatibility signal for the `__getattr__` approach and needs zero test rewrites for the
   constants that stay mocked this way.
3. **WAL journal mode is empirically confirmed persistent per-database-file** (verified live in
   this session, see Sources) — a fresh `sqlite3.connect()` on an already-WAL database reports
   `wal` mode without re-issuing the pragma. Combined with `core/db.py`'s fresh-connection-per-call
   idiom, the least-invasive, most robust placement is inside `_get_conn()` itself (self-healing
   regardless of which process — bot or, in Phase 2, the admin panel — opens the database file
   first), accepting a negligible per-connection pragma check as the cost.

**Primary recommendation:** Build `core/settings.py` as a pure stdlib module (mirroring
`core/store_sync.py`) using `core/db.py`'s existing `_get_conn()` for a new `init_settings()` +
`settings` table; convert `config.py`'s safe-tunable constants to a module `__getattr__` that
lazily imports `core.settings` (deferred import, avoiding a circular-import failure); add
`PRAGMA journal_mode=WAL` as the first statement in `core/db.py::_get_conn()`; call a new
`settings.seed_defaults()` (or equivalent) once, early, in `bot.py`'s `main()`, before the
existing fail-fast `config.X` checks.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Settings schema (key/type/default/validation/group) | Database / Storage (`core/settings.py`) | — | Single source of truth per STORE-01; must be importable by both the bot process and (Phase 2) the FastAPI admin process without either owning the other |
| Settings persistence (`settings` table) | Database / Storage (shared sqlite) | — | Two processes (bot, future panel) already share `DB_PATH`; no IPC layer exists or is being built (locked decision) |
| Settings validation (`SettingRejected`) | Database / Storage (`core/settings.py`) | — | Validation must run identically whether called from the bot's seed path or (Phase 2) the panel's POST handler — putting it in the shared pure module avoids duplicating rules in the web tier |
| Config read-at-use (`config.py` shim) | Backend process (bot / cog layer) | — | `config.py` is imported by every cog; it is the natural facade, not a new tier |
| Concurrency mode (WAL) | Database / Storage (`core/db.py`) | — | `_get_conn()` is the single choke point every process uses; this is a storage-tier concern, not an application concern |
| Idempotent seed on startup | Backend process (`bot.py::main()`) | Database / Storage (`core/settings.py` implementation) | Needs a single, ordered, single-threaded startup call site before any cog reads config; `core/settings.py` implements the logic, `bot.py` triggers it once |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlite3` | stdlib (bundled with Python 3.12.8, sqlite 3.45.3) | `settings` table storage | Already the sole persistence layer (`core/db.py`); no reason to introduce a second one |
| `json` | stdlib | Encode/decode the `settings.value TEXT` column | `settings` table schema is locked as `value TEXT` JSON-encoded (STORE-02); stdlib `json` is sufficient — values are scalars/lists of ints/strings, no complex types |
| `zoneinfo` | stdlib (3.9+) | Validate `REMINDERS_TZ`-shaped values via `ZoneInfo(...)` | Already the exact validation used in `bot.py::main()`'s existing fail-fast check (`ZoneInfo(config.REMINDERS_TZ)`) and in `cogs/reminders.py` |
| `re` | stdlib | Snowflake-shape validation (`^\d{17,20}$`), key/enum checks | Matches `core/editors_model.py`'s existing regex-validation idiom |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tzdata` | `>=2025.2` (already pinned in `requirements.txt`) | Backs `zoneinfo.ZoneInfo` on Windows/CI where the OS has no IANA tz database | Already required by `cogs/reminders.py`; no phase-1 action needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `json` for `value` column | `pydantic` (already a transitive dep via `fastapi`) | Rejected — CONTEXT explicitly locks `core/settings.py` as a "pure module: stdlib + sqlite" mirroring `core/store_sync.py`, which deliberately has zero non-stdlib imports. Pydantic-based validation is the `core/editors_model.py` pattern instead, used for a different (HTTP-payload) surface |
| Module `__getattr__` shim | Explicit getter functions (`config.get_photo_channel_id()`) | Rejected as primary — would require rewriting every one of the ~45 call sites found across `cogs/gallery.py`, `reviews.py`, `reminders.py`, `jinxxy.py`, `meeting.py` (via `core/transcription.py`/`core/summarizer.py`), `forum.py`, `encoding.py`. The `__getattr__` shim requires editing zero call sites since every existing read is already `config.X` attribute access (verified — no `from config import X` anywhere in the repo) |
| PRAGMA in `_get_conn()` | One-time PRAGMA call from `bot.py::main()` only | Considered as alternative — see **Pattern 3** below for the full tradeoff discussion |

**Installation:**
No new packages. This phase adds one new file (`core/settings.py`) using only what's already
installed.

**Version verification:** `sqlite3.sqlite_version` on the dev machine confirms `3.45.3`
`[VERIFIED: local python -c "import sqlite3; print(sqlite3.sqlite_version)"]` — WAL journaling
has been supported since SQLite 3.7.0 (2010), so no version risk. `tzdata>=2025.2` is already
pinned in `requirements.txt` line 24 `[VERIFIED: repo grep]`.

## Package Legitimacy Audit

**No new external packages are introduced by this phase.** `core/settings.py` is implemented
with `sqlite3`, `json`, `re`, and `zoneinfo` — all Python 3.12 standard library. The
`slopcheck`/registry-verification protocol does not apply; there is nothing to audit.

**Packages removed due to slopcheck [SLOP] verdict:** none (N/A — no packages recommended).
**Packages flagged as suspicious [SUS]:** none (N/A — no packages recommended).

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          Process 1: bot.py (discord.py)                   │
│                                                                            │
│  main()                                                                   │
│    │                                                                      │
│    ├─► core.db.init_db()          ─► CREATE TABLE IF NOT EXISTS forum_posts│
│    │     (WAL pragma also fires   ─► PRAGMA journal_mode=WAL (1st call)   │
│    │      here — first _get_conn())                                       │
│    │                                                                      │
│    ├─► core.settings.seed_defaults()                                     │
│    │     ├─► core.db.init_settings()  ─► CREATE TABLE IF NOT EXISTS settings│
│    │     └─► INSERT OR IGNORE per schema key ◄── .env / default values   │
│    │                                                                      │
│    ├─► existing fail-fast checks (config.GALLERY_STAFF_ROLE_IDS, etc.)   │
│    │     └─► config.__getattr__(key) ─► core.settings.get(key)           │
│    │           └─► SELECT value FROM settings WHERE key=? (fresh conn)   │
│    │                 ├─ row present + valid JSON → decoded value          │
│    │                 └─ row absent / corrupt / table missing → .env seed │
│    │                                                                      │
│    └─► bot.run() ─► setup_hook() loads cogs                              │
│           cogs/gallery.py, reviews.py, reminders.py, jinxxy.py,          │
│           meeting.py (→ core/transcription.py, core/summarizer.py),      │
│           forum.py, encoding.py                                          │
│             │  each read site is unchanged: `config.SOME_KEY`             │
│             └─► same __getattr__ → settings.get() path, AT EACH USE       │
│                   (staff-gate check, poll tick, forum-channel compare…)  │
└──────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│           Process 2 (Phase 2, out of scope): FastAPI admin panel          │
│           POST /admin/settings ─► core.settings.set(key, value)          │
│                                     ├─ validates against schema           │
│                                     ├─ raises SettingRejected on invalid  │
│                                     └─ writes settings table (same file) │
└──────────────────────────────────────────────────────────────────────────┘
                              ▲
                              │  same DB_PATH, WAL journal mode
                              │  (readers never block writers,
                              │   writers never block readers)
                              ▼
                     bot.db  (+ bot.db-wal, bot.db-shm sidecar files)
```

The primary use case to trace: a cog calls `config.PHOTO_CHANNEL_ID` → `config.__getattr__`
fires (the name is no longer a module-level constant) → delegates to `core.settings.get(...)` →
opens a fresh connection via `core.db._get_conn()` → `SELECT` against the `settings` table → JSON
decode → return. If the table doesn't exist yet, is empty for that key, or the stored JSON is
corrupt, `get()` catches the failure and returns the `.env`/default seed instead (STORE-04).

### Recommended Project Structure
```
core/
├── db.py            # existing — add init_settings() (new table) + WAL pragma in _get_conn()
├── settings.py       # NEW — schema, get/set/all_for_ui, SettingRejected, seed_defaults()
├── store_sync.py     # existing — pure-module precedent (no DB), unchanged
└── editors_model.py  # existing — validation-exception precedent (SlugRejected), unchanged
config.py              # existing — becomes get/set of frozen constants + __getattr__ shim
bot.py                 # existing — main() gains one call: settings.seed_defaults() (or similar)
tests/
└── test_settings.py   # NEW — mirrors tests/test_editors_model.py's structure
```

### Pattern 1: The `settings` table + `init_settings()` (mirrors existing `init_*()` idiom)

**What:** A new function in `core/db.py`, following the exact shape of `init_gallery_state()` /
`init_reminders()` / `init_store_state()` — `CREATE TABLE IF NOT EXISTS`, no seeding logic
inside it (seeding is `core/settings.py`'s job, matching the "do NOT fold into `init_db()`"
constraint from CONTEXT.md).

**When to use:** Called once at true process startup (not from a cog `__init__`, since settings
are read by every cog and even by `bot.py::main()`'s own fail-fast checks before any cog loads).

**Example (mirrors `core/db.py:38-52`'s `init_gallery_state()`):**
```python
# core/db.py — new function, same file, same idiom
def init_settings():
    """Create the settings table if it doesn't exist (STORE-02).

    key TEXT PRIMARY KEY, value TEXT (JSON-encoded). Deliberately NOT folded into
    init_db() (CONTEXT.md) — same reasoning as gallery_state/reminders/store_snapshot:
    each feature's table gets its own idempotent init function.
    """
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
```

### Pattern 2: `config.py` module `__getattr__` shim (PEP 562) — read-at-use with zero call-site churn

**What:** Because every existing consumer does `config.SOME_KEY` (attribute access on the
imported module, never `from config import SOME_KEY`), removing a constant's module-level
assignment and adding a module `__getattr__` fallback makes every existing call site
automatically become read-at-use, with the import deferred inside the function body to avoid a
circular-import failure (`config.py` → `core.settings` → `core.db` → `import config`).

**When to use:** For every key in the "safe tunables in scope" table in CONTEXT.md. Secrets and
structural values (CONF-02) keep their plain `os.getenv(...)` module-level assignment —
unchanged.

**Example:**
```python
# config.py — safe tunables are REMOVED as module-level assignments and instead
# declared (for reference/defaults) only inside core/settings.py's schema. A
# __getattr__ fallback intercepts any read that isn't a real module attribute.

_SAFE_TUNABLE_KEYS = frozenset({
    "PHOTO_CHANNEL_ID", "GALLERY_STAFF_ROLE_IDS",
    "REVIEWS_CHANNEL_ID", "REVIEWS_STAFF_ROLE_IDS",
    "REMINDERS_TZ", "REMINDERS_STAFF_ROLE_IDS", "REMINDERS_CATCHUP_GRACE_HOURS",
    "JINXXY_ANNOUNCE_CHANNEL_ID", "JINXXY_POLL_HOURS", "JINXXY_STAFF_ROLE_IDS",
    "JINXXY_STORE_URL", "WEBSITE_BASE_URL",
    "MEETINGS_FORUM_ID", "MEETING_LANG", "WHISPER_PROMPT", "WHISPER_MODEL", "OLLAMA_MODEL",
    "FORUM_CHANNEL_ID", "ENCODING_CHANNEL_ID",
})

def __getattr__(name: str):
    """PEP 562 module __getattr__ — only fires when `name` is NOT a real module
    attribute (i.e. never for the frozen secrets/structural constants above, and
    never for config.py's OWN top-level code, which reads its own globals directly).
    Deferred import avoids a circular import: core.settings -> core.db -> `import config`
    only resolves safely because config.py has already finished executing by the time
    any EXTERNAL caller triggers __getattr__.
    """
    if name in _SAFE_TUNABLE_KEYS:
        from core import settings  # deferred — see circular-import pitfall below
        return settings.get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

This requires **zero edits** to `cogs/gallery.py`, `cogs/reviews.py`, `cogs/reminders.py`,
`cogs/jinxxy.py`, `cogs/forum.py`, `cogs/encoding.py`, `core/transcription.py`, or
`core/summarizer.py` — every one of their `config.X` reads (confirmed via grep, listed in
Sources) already re-evaluates on every access, since Python attribute access is never cached by
the reader.

**One exception requiring attention, not a call-site edit:** `cogs/jinxxy.py:246` —
`@tasks.loop(hours=config.JINXXY_POLL_HOURS)` is a **decorator argument**, evaluated once at
class-definition time (import time of `cogs/jinxxy.py`), not per-poll. This is EXPECTED and
matches the design's own accepted nuance ("changing a `@tasks.loop` INTERVAL applies on the next
cycle / bot restart, not instantly" — spec `## Decisions`, point 5; also PANEL-04, "loop-interval
changes apply on the next cycle/restart"). No code change needed here beyond the `__getattr__`
shim itself — the decorator naturally picks up the DB-backed value once at cog load, which is the
locked, intended behavior for interval-shaped settings.

### Pattern 3: WAL journal mode — where to apply it (CONC-01, decided)

**What:** `PRAGMA journal_mode=WAL` is confirmed empirically (this session) to be **persistent
in the database file header** — a fresh connection, opened with no pragma set at all, reports
`wal` mode once any prior connection has set it once
`[VERIFIED: local python -c reproduction, see Sources]`. This directly resolves the CONTEXT.md
open question: "is a one-time PRAGMA journal_mode=WAL persistent for the database file (so it
need only be set once)" — **yes, confirmed.**

**Two placement options were evaluated:**

| Option | Where | Pros | Cons |
|--------|-------|------|------|
| **A — inside `_get_conn()`** (recommended) | `core/db.py::_get_conn()`, as the first statement after `conn.row_factory = sqlite3.Row` | Self-healing regardless of process start order — works correctly whether `bot.py` or (Phase 2) the FastAPI admin app opens the database file first; touches exactly one function, one line; zero new startup call sites anywhere | Every single DB call (all ~30 functions in `core/db.py`) pays one extra cheap pragma round-trip forever — negligible for this bot's call volume (Discord reactions, hourly polls), but not literally "free" |
| **B — one-time call from `bot.py::main()`** | New `db.enable_wal()` (or folded into `init_db()`), called once before `bot.run()` | Zero recurring per-call overhead after the first call | Only protects the bot process; the Phase 2 admin app would need its OWN explicit call in `app/main.py`'s `lifespan()`, duplicating the concern across two files; also depends on which process starts first on a brand-new DB file (a rare but real edge case if the panel process starts before the bot on a fresh deploy) |

**Recommendation: Option A.** The `with conn:` transaction usage (`sqlite3.Connection` used as a
context manager) is unaffected — that context manager only governs commit/rollback of the
transaction body, not the journal mode, and `PRAGMA journal_mode=WAL` is not itself
transactional (SQLite applies it immediately, outside the `BEGIN`/`COMMIT` the `with` block
manages). Recommended change to `core/db.py`:

```python
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # CONC-01 — persistent per-file after first call
    return conn
```

**Windows/shared-file caveat (flagged, not blocking):** WAL requires the filesystem to support
the shared-memory primitives backing the `-wal`/`-shm` sidecar files. This works reliably on
local NTFS (dev machine) and local ext4/xfs (the `cinema` deploy host — confirmed Linux via
`deploy/nocturna-editor-admin.service`'s systemd unit, `/home/YOUR_USER/...` paths)
`[VERIFIED: repo file deploy/nocturna-editor-admin.service]`. It is **not** reliable over network
filesystems (SMB/NFS) — not applicable here since `DB_PATH` defaults to a relative path
(`bot.db`) on local disk in both environments, but worth a one-line comment in the code so a
future deploy to a network-mounted path doesn't silently regress.

**Writer/writer contention (secondary, not requiring new code):** WAL solves reader-vs-writer
blocking (the actual CONC-01 scenario — bot reads while panel writes) but two SIMULTANEOUS
writers (e.g. bot writing `reminders` while panel writes `settings`, same file) still serialize
briefly. `sqlite3.connect()`'s default `timeout` parameter is 5.0 seconds
`[VERIFIED: local python -c reproduction]`, which already causes a blocked writer to retry for up
to 5s before raising `sqlite3.OperationalError: database is locked` — this default is already in
effect today (unset in `_get_conn()`) and needs no phase-1 change, but is worth noting in the
plan as "already covered" so it isn't independently re-litigated.

### Pattern 4: `SettingRejected` exception (mirrors `core/editors_model.py::SlugRejected`)

**What:** The codebase already has a precedent for a typed, reason-carrying validation
exception — `core/editors_model.py:164-174`'s `SlugRejected(ValueError)`.

```python
# core/settings.py
class SettingRejected(ValueError):
    """Raised by settings.set() when a value fails schema validation (STORE-03).

    Mirrors core/editors_model.py's SlugRejected — a typed, reason-carrying exception
    so a future HTTP layer (Phase 2) can map .reason to a field-level error without
    string-matching the message.
    """
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
```

### Anti-Patterns to Avoid
- **Interpolating a settings key into SQL.** The repo's `_REMINDER_UPDATABLE` allowlist
  discipline (`core/db.py:220-225`) exists specifically to prevent this. `settings.set` must
  validate `key` against the schema's known key set BEFORE using it in any SQL, and the `key`
  itself should still go through a parameterized `?` (never an f-string), even though it's
  allowlist-checked — defense in depth, matching existing repo conventions.
- **Doing DB I/O at `config.py` import time.** The read-at-use requirement (CONF-01) and the
  "pure module" precedent both forbid this. The `__getattr__` shim only fires on attribute
  access, never during `config.py`'s own top-level execution.
- **A non-deferred `from core import settings` at the top of `config.py`.** This creates a
  circular import (see Common Pitfalls below) and will raise `ImportError` or return a partially
  initialized module at process startup.
- **Setting WAL mode conditionally based on `os.name` or platform checks.** Unnecessary — WAL
  works identically via the same one-line pragma on both the Windows dev machine and the Linux
  `cinema` host; no platform branching needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Discord snowflake ID shape validation | A custom length/digit-range checker | `re.fullmatch(r"\d{17,20}", value)` | Already the exact regex CONTEXT.md locks; Discord snowflakes are always 17-20 decimal digits — no library needed, this is a one-line stdlib regex |
| Timezone validity check | A hardcoded list of IANA zone names | `zoneinfo.ZoneInfo(value)` wrapped in try/except `ZoneInfoNotFoundError` | `bot.py::main()` ALREADY does exactly this for `REMINDERS_TZ` today (lines 126-133) — reuse the identical check inside `settings.set`'s TZ validator rather than inventing a second mechanism |
| JSON value round-tripping for the `value TEXT` column | A custom serialization format | stdlib `json.dumps`/`json.loads` | STORE-02 locks `value TEXT` as JSON-encoded; values are scalars/int-lists only (no nested objects), well within `json`'s native scope |
| A settings cache/reload signal between processes | A file-watch, socket, or pub/sub layer | Nothing — read-at-use against the shared sqlite IS the mechanism (locked decision, spec `## Decisions` point 4/5) | Explicitly out of scope; building any IPC here would contradict the approved design |

**Key insight:** This phase has almost no "don't hand-roll" surface because the two genuinely
hard subproblems (concurrent sqlite access, typed validation) are both solved by SQLite itself
(WAL) and by patterns already proven elsewhere in this exact codebase (`SlugRejected`,
`ZoneInfo` validation, snowflake regex). The temptation to avoid is building something NEW rather
than reusing what's one file away.

## Common Pitfalls

### Pitfall 1: Circular import between `config.py` and `core/settings.py`
**What goes wrong:** `core/db.py` does `import config` at module level (line 4, for
`config.DB_PATH`). If `config.py`'s `__getattr__` does `from core import settings` at MODULE
level (top of file) rather than inside the function body, Python hits a circular import the
first time anything imports `config` before `core.settings`/`core.db` have finished loading —
`config` → `core.settings` → `core.db` → `import config` (not yet in `sys.modules` as complete)
→ `ImportError` or a partially-initialized module object missing `DB_PATH`.
**Why it happens:** `config.py` is the most-imported module in the repo (every cog, `core/db.py`,
`bot.py`, `app/main.py` all import it); adding a reverse dependency from `config.py` back into
`core/` inverts the existing one-way dependency direction (`core/` → `config`, never the other
way).
**How to avoid:** Do the `from core import settings` import **inside the `__getattr__` function
body**, not at module top level. By the time any external caller triggers `config.__getattr__`
(attribute access from outside the module), `config.py`'s own top-level code has already fully
executed and is registered in `sys.modules`, so `core/db.py`'s `import config` resolves to the
complete module with no cycle.
**Warning signs:** `ImportError: cannot import name 'settings' from partially initialized module
'core'` (or similar) raised during `import config` at the very top of any test file or `bot.py`.

### Pitfall 2: `settings.get()` must survive a missing table, not just a missing row
**What goes wrong:** STORE-04 requires `get()` to never raise, "a missing or corrupt row falls
back to the seed." But `bot.py::main()` calls `config.GALLERY_STAFF_ROLE_IDS` (etc.) for its
fail-fast checks BEFORE any cog's `__init__` runs, and (per the recommended startup flow) even
before `settings.seed_defaults()`/`init_settings()` has necessarily completed if the seed call is
misplaced or fails. If `init_settings()` hasn't run yet, `SELECT value FROM settings WHERE
key=?` raises `sqlite3.OperationalError: no such table: settings`, not merely "row not found" —
a narrower `except sqlite3.Error` catch that only anticipates a missing ROW (not a missing TABLE)
will let this propagate and violate STORE-04.
**Why it happens:** The other `init_*()` functions are each called from their owning cog's
`__init__`, which only runs during `setup_hook` — but `settings` is read by code that runs
BEFORE `setup_hook` (the existing fail-fast block in `main()`).
**How to avoid:** `settings.get()`'s implementation should catch `sqlite3.Error` broadly (not
just "row is None"), covering "table doesn't exist," "value is malformed JSON," and "value fails
schema validation" all as equally-valid reasons to fall back to the `.env`/default seed. Do not
special-case "table missing" as a startup-ordering bug to prevent — make `get()` unconditionally
robust to it, exactly as `app/main.py`'s `lifespan()` already treats `db.init_presence()` /
`db.init_view_counts()` as best-effort (`try/except Exception: log.exception(...)`, non-fatal).
**Warning signs:** `sqlite3.OperationalError: no such table: settings` in bot logs at startup,
or the bot exiting via the existing `sys.exit(1)` fail-fast paths in `main()` on a completely
fresh deploy where the table has never been created.

### Pitfall 3: Seeding must run once, centrally — not from any single cog's `__init__`
**What goes wrong:** Following the `init_gallery_state()` / `init_reminders()` /
`init_store_state()` precedent literally (each called from its OWNING cog's `__init__`) is wrong
for `settings`, because settings are consumed by SEVEN different cogs plus `bot.py::main()`
itself, and cogs load in a fixed but not-obviously-safe order in `setup_hook`
(`encoding, forum, gallery, reviews, reminders, jinxxy, editors, presence, help, meeting`). If
seeding were tied to (say) `GalleryCog.__init__`, then `bot.py::main()`'s fail-fast checks
(which run BEFORE any `load_extension` call) would read unseeded settings on first boot — which
is harmless (falls back to `.env`, matching current behavior) UNLESS a later cog's seed
overwrites a value the fail-fast check already read a different (stale) copy of. In practice
`get()`'s per-call fallback (Pitfall 2) makes this survivable either way, but seeding still needs
ONE clear owner to satisfy STORE-05's "idempotent... on startup" wording unambiguously for the
Phase 2 panel's `all_for_ui()`, which should show real seeded rows, not perpetually-empty ones.
**Why it happens:** The repo's existing `init_*()` precedent is per-feature/per-cog, but
`settings` is cross-cutting.
**How to avoid:** Call the seed step explicitly and once from `bot.py::main()`, before the
existing `config.X` fail-fast checks, e.g. `core.settings.seed_defaults()` (naming at
implementation discretion) which internally calls `core.db.init_settings()` then does an
idempotent `INSERT OR IGNORE`-style seed per schema key. This keeps `core/settings.py`'s PUBLIC
API to exactly `get`/`set`/`all_for_ui` (STORE-01) while still exposing an internal
startup-only entry point `bot.py` calls directly (module-private by convention, e.g. a leading
underscore, or documented as "startup-only, not part of the panel-facing API").
**Warning signs:** Phase 2's `all_for_ui()` renders correct current values (via the `.env`
fallback) but an empty/never-populated `settings` table on a system that's been running for
weeks — a working-but-technically-non-compliant-with-STORE-05 state that's easy to miss because
`get()`'s fallback masks it.

### Pitfall 4: `WHISPER_MODEL`/`OLLAMA_MODEL` are free strings, not validated against a model list
**What goes wrong:** A natural instinct when building a generic "enum/toggle" validator is to
also constrain free-text-looking fields like model names against SOME allowlist. CONTEXT.md
explicitly locks these as accepted free strings — "an unknown model is a runtime concern... NOT a
validation error." Adding model-name validation would be scope creep AND would break for any
locally-available Ollama/Whisper model not on a hardcoded list.
**Why it happens:** Every other tunable in scope IS validated (IDs, intervals, TZ, enums), so it's
easy to assume all fields need a validation rule.
**How to avoid:** In the schema, `WHISPER_MODEL` / `OLLAMA_MODEL` should have a `validate: None`
(or equivalent "accept any non-empty string, maybe length-capped") rule, distinct from the
snowflake/interval/TZ/enum validators used elsewhere.
**Warning signs:** A test that tries to save a valid-but-uncommon model name and gets an
unexpected `SettingRejected`.

### Pitfall 5: The staff-role fallback-to-`GALLERY_STAFF_ROLE_IDS` semantic must survive migration (CONF-03)
**What goes wrong:** Today, `REVIEWS_STAFF_ROLE_IDS` / `REMINDERS_STAFF_ROLE_IDS` /
`JINXXY_STAFF_ROLE_IDS` compute their fallback ONCE, at `config.py` import time (e.g.
`config.py:80-82`: `[...] or GALLERY_STAFF_ROLE_IDS` — a plain Python `or` against the ALREADY
frozen `GALLERY_STAFF_ROLE_IDS` list, evaluated once when `config.py` first runs). After
migration, both sides of that `or` become independently DB-backed, read-at-use values — if the
fallback logic isn't re-implemented as a runtime check (not an import-time one), then e.g.
`GALLERY_STAFF_ROLE_IDS` changing at runtime would no longer correctly cascade into
`REVIEWS_STAFF_ROLE_IDS`'s empty-fallback behavior (a stale, import-time-frozen fallback would
still be baked in), OR conversely a naive re-implementation might apply the fallback INSIDE
`settings.get("REVIEWS_STAFF_ROLE_IDS")` in a way that gets confused with the "row missing → use
seed" fallback already required by STORE-04 (these are two DIFFERENT fallback mechanisms that
must compose correctly: empty-list-in-DB → gallery roles; row-entirely-absent → `.env` seed,
which itself might be empty, cascading to gallery roles).
**Why it happens:** The current code conflates "unset in `.env`" with "empty list," and the
`__getattr__` shim by itself doesn't automatically preserve a CROSS-KEY fallback relationship —
that logic currently lives in `config.py`'s top-level assignment expression, which is being
removed for these keys.
**How to avoid:** Implement the `GALLERY_STAFF_ROLE_IDS`-fallback as an explicit, runtime check —
either inside `config.__getattr__` (special-case these three keys: if `settings.get(key)` returns
an empty list, return `settings.get("GALLERY_STAFF_ROLE_IDS")` instead) or inside
`core/settings.py`'s schema itself (a per-key `fallback_key` attribute the schema declares,
resolved by `get()`). Either placement is fine (Claude's Discretion per CONTEXT.md), but the
fallback MUST be evaluated fresh on every read, not baked in at seed time, since a staff-gate
re-reads its role list per reaction (the whole point of read-at-use).
**Warning signs:** A test that sets `GALLERY_STAFF_ROLE_IDS` via the (future, Phase 2) panel,
leaves `REVIEWS_STAFF_ROLE_IDS` empty, and finds the reviews staff gate still using the OLD
gallery roles (or no roles at all).

## Code Examples

### `settings.get()` — never-raises, falls back to `.env`/default seed (STORE-04)
```python
# core/settings.py
import json
import logging

import config as _config  # only for reading the .env-sourced default seed values
from core import db

log = logging.getLogger(__name__)


def get(key: str):
    """Return the stored value for ``key``, or the .env/default seed. Never raises (STORE-04)."""
    default = _SCHEMA[key].default  # from the schema; may itself be an .env-sourced value
    try:
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])
    except (Exception,) as e:  # table missing, corrupt JSON, or any sqlite error
        log.warning("settings.get(%r) fell back to default: %s", key, e)
        return default
```
*Note: catching bare `Exception` here is deliberate and matches STORE-04's "never raises"
requirement plus `app/main.py`'s existing precedent of broad `except Exception` around
best-effort table init (`lifespan()`, line 272). A narrower `except sqlite3.Error` would also
satisfy the DB-failure cases but would NOT catch a `json.JSONDecodeError` on a corrupt row — the
broad catch is the correct choice for STORE-04's "corrupt row" wording specifically.*

### `settings.set()` — validates, raises `SettingRejected`, writes nothing on failure (STORE-03)
```python
# core/settings.py
def set(key: str, value) -> None:
    """Validate `value` against the schema for `key`, then persist it. Raises SettingRejected
    on invalid input; writes nothing on failure (STORE-03)."""
    if key not in _SCHEMA:
        raise SettingRejected(f"unknown setting key: {key!r}")
    descriptor = _SCHEMA[key]
    validated = descriptor.validate(value)  # raises SettingRejected internally on failure
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(validated)),
        )
```
*Source pattern: `core/db.py::set_presence()` (lines 512-521) already uses the identical
`INSERT ... ON CONFLICT(...) DO UPDATE SET ...` upsert idiom for a single-key-per-row table —
reuse it verbatim rather than `INSERT OR REPLACE` (which would work too, but the `ON CONFLICT`
form is the more recently-used idiom in this file, e.g. `increment_view()` too).*

### Snowflake / interval / TZ validators (STORE-03)
```python
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_SNOWFLAKE_RE = re.compile(r"^\d{17,20}$")

def _validate_channel_id(value) -> int:
    s = str(value).strip()
    if not _SNOWFLAKE_RE.fullmatch(s):
        raise SettingRejected("must be a Discord snowflake ID (17-20 digits)")
    return int(s)

def _validate_role_id_list(value) -> list[int]:
    # comma-separated string OR a list — mirrors config.py's existing
    # "[int(x) for x in os.getenv(...).split(',') if x.strip()]" idiom
    items = value if isinstance(value, list) else str(value).split(",")
    out = []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        if not _SNOWFLAKE_RE.fullmatch(item):
            raise SettingRejected(f"invalid role ID in list: {item!r}")
        out.append(int(item))
    return out

def _validate_timezone(value) -> str:
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise SettingRejected(f"not a valid IANA timezone: {value!r}")
    return str(value)
```
*Source: the TZ check mirrors `bot.py::main()`'s EXISTING check almost verbatim (lines 126-133,
`ZoneInfo(config.REMINDERS_TZ)` wrapped in `except (ZoneInfoNotFoundError, KeyError,
ValueError)`) — reusing the exact same exception tuple avoids introducing a second, possibly
inconsistent TZ-validity definition in the codebase.*

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `config.py` freezes all ~50 tunables at `os.getenv(...)` import time | Safe tunables (18 keys) read-at-use via `settings.get()`; secrets/structural values (~30 keys) stay frozen | This phase | A saved panel edit (Phase 2) takes effect on the NEXT read, no bot restart, for everything except `@tasks.loop` intervals (next cycle/restart, by design) |
| `core/db.py::_get_conn()` opens sqlite with default rollback-journal mode | WAL journal mode, set idempotently in `_get_conn()` | This phase (CONC-01) | Concurrent bot-read / panel-write no longer raises "database is locked" under normal contention; writer/writer contention already mitigated by Python's existing 5s default connect timeout |

**Deprecated/outdated:** Nothing in this phase deprecates existing DB helper functions —
`init_db()`, `init_gallery_state()`, etc. are all unchanged and continue to be called from their
existing cog `__init__` sites.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `settings` table's seed/startup call belongs in `bot.py::main()` (not `setup_hook`, not a cog `__init__`) | Architecture Patterns / Pitfall 3 | Low — this is a design recommendation, not a verified fact; if the planner places it elsewhere (e.g. `setup_hook`'s top, before `load_extension` calls) the STORE-04 fallback still makes the bot functionally correct either way, just less precisely matching STORE-05's "on startup" wording |
| A2 | Placing `PRAGMA journal_mode=WAL` inside `_get_conn()` (Option A) is preferable to a one-time call in `main()` (Option B) | Architecture Patterns / Pattern 3 | Low-medium — both options are technically correct (WAL is persistent either way per the verified test); Option A's "negligible per-call overhead" claim is reasoned from the app's low call volume (Discord reactions/polls), not benchmarked in this session |
| A3 | `core/settings.py` should call `core/db.py::_get_conn()` (currently name-mangled private with a single underscore) directly, rather than `core/db.py` exposing a new public `get_conn()` | Code Examples | Low — `tests/test_counter_app.py:70` already calls `db._get_conn()` directly from outside `core/db.py`, establishing this as an accepted (if informal) convention in this codebase; a stricter reviewer might prefer a public rename |

**None of these are HIGH-risk** — all three are architecture/style recommendations grounded in
strong codebase precedent, not claims about external library behavior needing user confirmation
in the CONTEXT.md sense. No `[ASSUMED]`-tagged claims about third-party APIs, compliance, or
external service behavior exist in this research.

## Open Questions (RESOLVED)

> **RESOLVED (2026-07-21, at planning):** Q1 → adopt the recommendation — `core/settings.py` adds a
> `seed_defaults()` startup hook (called from `bot.py::main()`), documented as startup-only and NOT
> part of the get/set/all_for_ui panel-facing contract (see 01-02 Task 3 + 01-03 Task 2). Q2 →
> Claude's Discretion per CONTEXT.md; the plan adopts a plain dict of small dataclasses (01-02 Task 2).
> Neither is a design risk; both are settled in the plans.

1. **Should `settings.seed_defaults()` (the startup seed call) be part of `core/settings.py`'s
   importable surface, or should `core/db.py::init_settings()` alone be sufficient and the
   seed-from-`.env` loop live inline in `bot.py`?**
   - What we know: STORE-01 locks the PUBLIC API to exactly `get`/`set`/`all_for_ui`; the seed
     step is functionally necessary but wasn't given an explicit name in CONTEXT.md.
   - What's unclear: whether "public API is exactly three functions" is a hard constraint on
     the whole module's importable surface, or specifically a constraint on what the Phase 2
     panel is allowed to call.
   - Recommendation: treat it as the latter — add one more function (e.g. `seed_defaults()`) that
     `bot.py` calls directly, documented as "startup-only, not part of the panel-facing contract."
     This is a naming/scoping decision for the planner, not a design risk.

2. **Should the `settings` schema itself be a `dict` of dataclass-like descriptors defined at
   module level in `core/settings.py`, or loaded from a separate `SETTINGS_SCHEMA` structure?**
   - What we know: CONTEXT.md explicitly leaves "internal structure of the schema (dataclass vs
     dict-of-descriptors)" to Claude's Discretion.
   - What's unclear: nothing blocking — this is confirmed-open by the user's own CONTEXT.md.
   - Recommendation: a plain dict of small dataclasses (one per key: `key, type, default,
     validate_fn, group`) is idiomatic Python 3.12 and keeps `all_for_ui()` a simple
     groupby-and-serialize over the same structure `get`/`set` already consult — no need for a
     heavier framework given the module is explicitly stdlib-only.

## Environment Availability

No external service/tool dependencies are introduced by this phase — it is pure Python
stdlib + the already-running shared sqlite file. `sqlite3.sqlite_version` (3.45.3) and `tzdata`
(already pinned) are confirmed present in the dev environment; the `cinema` deploy host is
confirmed Linux via existing systemd unit files (`deploy/nocturna-editor-admin.service`), which
is a fully WAL-compatible local filesystem target.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| sqlite3 (stdlib) | `settings` table, WAL | Yes | 3.45.3 | — |
| zoneinfo + tzdata | TZ validation | Yes | tzdata 2025.2+ (pinned) | — |
| Local disk for `DB_PATH` | WAL sidecar files (`-wal`/`-shm`) | Yes (both dev + `cinema`) | — | Flag if `DB_PATH` is ever pointed at a network share (not currently the case) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STORE-01 | `core/settings.py` exposes `get(key)`, `set(key, value)`, `all_for_ui()` | Architecture Pattern 1/4; Code Examples show `get`/`set` shapes; schema structure left to discretion per Open Question 2 |
| STORE-02 | `settings` table (`key TEXT PRIMARY KEY, value TEXT` JSON-encoded), via `CREATE TABLE IF NOT EXISTS` in `core/db.py` | Pattern 1 gives the exact `init_settings()` function mirroring `init_gallery_state()` |
| STORE-03 | `settings.set` validates every value, raises typed `SettingRejected(reason)`, writes nothing on invalid input | Pattern 4 (`SettingRejected` mirrors `SlugRejected`); Code Examples give snowflake/interval/TZ/enum validators |
| STORE-04 | `settings.get` never raises — missing/corrupt row falls back to `.env`/default seed | Pitfall 2 (must catch missing-TABLE, not just missing-row); Code Examples show the broad-except pattern |
| STORE-05 | Idempotent startup seed from `.env`/defaults for unset keys; byte-identical until edited | Pitfall 3 (central seed call site in `bot.py::main()`); Diagram shows the seed step in the startup sequence |
| CONF-01 | Safe-tunable constants read via `settings.get(...)` at point of use | Pattern 2 — the `__getattr__` shim, verified zero-call-site-edit via full-repo grep of `config.X` usage |
| CONF-02 | Secrets/structural values stay frozen from `.env`, never migrated | Pattern 2 — `_SAFE_TUNABLE_KEYS` allowlist explicitly excludes them; full secret/structural list re-confirmed against `config.py`'s current contents |
| CONF-03 | Staff-role fallback-to-`GALLERY_STAFF_ROLE_IDS` semantic survives migration | Pitfall 5 — details the exact runtime-vs-import-time distinction and two composable fallback layers |
| CONC-01 | Shared-sqlite access mode decided + applied so bot-read/panel-write don't collide | Pattern 3 — WAL in `_get_conn()`, empirically verified persistent; Windows/network-share caveat noted; writer/writer timeout already covered by Python's default |
</phase_requirements>

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=8.0.0` (already pinned in `requirements.txt`) |
| Config file | none detected (no `pytest.ini`/`pyproject.toml` `[tool.pytest]` section) — tests run via bare `pytest` from repo root, relying on `tests/conftest.py`'s `sys.path` bootstrap |
| Quick run command | `pytest tests/test_settings.py -x` (new file) |
| Full suite command | `pytest` (repo root) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STORE-01 | `get`/`set`/`all_for_ui` round-trip through the `settings` table | unit | `pytest tests/test_settings.py -k round_trip -x` | ❌ Wave 0 |
| STORE-03 | Per-type validation: accept valid, reject invalid ID/interval/TZ | unit | `pytest tests/test_settings.py -k validation -x` | ❌ Wave 0 |
| STORE-04 | `get` never raises — missing row, missing table, corrupt JSON all fall back | unit | `pytest tests/test_settings.py -k fallback -x` | ❌ Wave 0 |
| STORE-05 | Idempotent seed — running the seed step twice is a no-op, matches `.env` values | unit | `pytest tests/test_settings.py -k seed_idempotent -x` | ❌ Wave 0 |
| CONF-01 | A migrated cog re-reads a changed value at its next use (not cached from import) | unit | `pytest tests/test_reminders_cog.py tests/test_gallery_cog.py tests/test_jinxxy_cog.py -k staff_gate_or_channel -x` (extend existing files) | ⚠️ Wave 0 — existing files exist, new test cases needed |
| CONF-02 | Secrets/structural values are unaffected (existing `monkeypatch.setattr(config, ...)` tests for `GITHUB_PAT`, `SESSION_SECRET`, etc. still pass unmodified) | unit | `pytest` (full suite — regression, no new tests needed) | ✅ existing |
| CONF-03 | Staff-role fallback-to-gallery semantic holds when the specific role list is empty in the DB | unit | `pytest tests/test_settings.py -k staff_role_fallback -x` | ❌ Wave 0 |
| CONC-01 | WAL mode is active after `_get_conn()`'s first call; two connections can read+write without "database is locked" under a short contention window | integration | `pytest tests/test_settings.py -k wal -x` (new — spin up two connections against a `tmp_path` db) | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_settings.py -x` (and the touched cog's existing test
  file, e.g. `pytest tests/test_reminders_cog.py -x` after editing `cogs/reminders.py`'s
  behavior indirectly via `config.py`)
- **Per wave merge:** `pytest` (full suite — this repo has no slow/integration markers to
  exclude; the existing suite runs in-process against `tmp_path` sqlite files, matching the
  `test_counter_app.py`/`test_gallery_cog.py` precedent)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_settings.py` — new file covering STORE-01/03/04/05 and CONF-03's fallback
      composition, mirroring `tests/test_editors_model.py`'s structure (plain `assert`/
      `pytest.raises`, no fixtures beyond `tmp_path` + `monkeypatch.setattr(config, "DB_PATH",
      ...)` — matching `tests/test_counter_app.py:23`'s existing `DB_PATH` monkeypatch idiom for
      isolating a test DB)
- [ ] Extend `tests/test_reminders_cog.py`, `tests/test_gallery_cog.py`, `tests/test_jinxxy_cog.py`,
      `tests/test_reviews_cog.py` with ONE new test each proving read-at-use: mock
      `core.settings.get` (or set the underlying DB row) between two calls to the cog's staff-gate
      function and assert the second call reflects the change — this is the "migrated-cog test"
      the design spec's Testing section calls for.
- [ ] No framework install needed — `pytest` already present.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Out of scope this phase (Phase 2 owns `require_owner`) |
| V3 Session Management | No | Out of scope this phase |
| V4 Access Control | No | Out of scope this phase — no new access boundary is introduced; `settings.set` has no caller yet (Phase 2 wires the only write path) |
| V5 Input Validation | Yes | `settings.set`'s schema-driven validators (snowflake regex, integer range, `zoneinfo.ZoneInfo` resolution, closed enum sets) — see Code Examples |
| V6 Cryptography | No | No crypto surface in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| SQL injection via a settings key/column name | Tampering | `settings.set` validates `key` against the schema's known-key set BEFORE any SQL; the value always goes through a parameterized `?` placeholder (never an f-string), matching `core/db.py`'s existing `_REMINDER_UPDATABLE` allowlist discipline |
| A crafted/out-of-range value silently breaking a cog at runtime (e.g. a non-numeric channel ID reaching `bot.get_channel(...)`) | Tampering / Denial of Service | Validation is the gate in `settings.set` — an invalid value is rejected BEFORE any write, so `settings.get` can never return a value that would break a cog (STORE-03's explicit intent, reiterated in the design spec's Security section) |
| Stale/corrupt JSON in the `value` column (e.g. from manual DB editing or a future schema change) causing a crash at read time | Denial of Service | `settings.get`'s broad-except fallback (Pitfall 2 / STORE-04) — a corrupt row degrades to the `.env` default rather than crashing the read path |

This phase does not expose any new network-reachable surface — the only new attack surface (an
HTTP `POST` reaching `settings.set`) is explicitly Phase 2's scope (PANEL-01/02/03).

## Sources

### Primary (HIGH confidence)
- `core/db.py` (full file, this repo) — the `init_*()` + `CREATE TABLE IF NOT EXISTS` idiom,
  `_get_conn()`'s fresh-connection-per-call pattern, `with conn:` transaction usage,
  `_REMINDER_UPDATABLE` allowlist discipline, `set_presence()`'s `ON CONFLICT` upsert idiom.
- `config.py` (full file, this repo) — every current `os.getenv(...)` read, the
  secret/structural/safe-tunable split, and the existing `GALLERY_STAFF_ROLE_IDS`-fallback `or`
  expressions (lines 80-82, 93-95, 117-119).
- `core/store_sync.py`, `core/editors_model.py` (full files, this repo) — the pure-module
  precedent and the `SlugRejected(ValueError)` typed-exception precedent.
- `bot.py` (full file, this repo) — the `main()` fail-fast validation block that reads
  `config.GALLERY_STAFF_ROLE_IDS`/`REVIEWS_CHANNEL_ID`/`REMINDERS_TZ` before `setup_hook`, and
  the `setup_hook()` cog-load order.
- `app/main.py` lines 255-284 (this repo) — the `lifespan()` best-effort `db.init_presence()`/
  `db.init_view_counts()` precedent for non-fatal startup table init.
- Full-repo `Grep` for every safe-tunable constant across `cogs/*.py` and `core/*.py` — confirms
  every read site is `config.X` attribute access; zero `from config import X` statements exist
  anywhere in the repo.
- Full-repo `Grep` for `monkeypatch.setattr(config,` across `tests/*.py` — confirms the
  module-attribute-patching idiom used in 12 test files, validating `__getattr__` compatibility.
- Local execution: `python -c "import sqlite3; print(sqlite3.sqlite_version)"` → `3.45.3`.
- Local execution: a 3-step sqlite3 reproduction confirming `PRAGMA journal_mode=WAL` set once
  persists across a fresh `sqlite3.connect()` with no pragma re-issued
  `[VERIFIED: local python execution, this session]`.
- `deploy/nocturna-editor-admin.service` (this repo) — confirms the `cinema` deploy host is
  Linux/systemd with local-filesystem paths (`/home/YOUR_USER/nocturna-bot`).
- `requirements.txt` (this repo) — confirms `tzdata>=2025.2` already pinned, no new packages
  needed.
- `tests/test_editors_model.py`, `tests/test_reminders_cog.py`, `tests/test_gallery_cog.py`,
  `tests/test_counter_app.py` (this repo) — the existing test-precedent for round-trip DB tests,
  `monkeypatch.setattr(config, ...)`, and `DB_PATH` isolation via `tmp_path`.

### Secondary (MEDIUM confidence)
- SQLite WAL persistence semantics (general knowledge of "WAL mode is sticky per database file
  once set") — corroborated by this session's own empirical local reproduction (promoted to
  Primary/VERIFIED above), not relied on as training-data-only.
- Python `sqlite3.connect()`'s default `timeout=5.0` parameter (training-data knowledge of the
  stdlib API) — not independently re-verified via a live timeout-triggering test in this session
  (would require simulating an actual lock contention scenario); flagged here rather than in the
  Assumptions Log because it is documented, stable stdlib API behavior rather than an
  ecosystem/library claim, but the planner should not treat the exact 5.0s figure as re-verified
  this session if precision matters.

### Tertiary (LOW confidence)
- None used — all claims in this research are grounded in direct repository inspection or local
  tool execution.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every recommendation is stdlib or an already-pinned
  dependency, cross-checked against `requirements.txt`.
- Architecture: HIGH — every pattern is grounded in a direct read of the actual file it mirrors
  (`core/db.py`, `core/store_sync.py`, `core/editors_model.py`, `bot.py`, `app/main.py`), not
  external-library research.
- Pitfalls: HIGH — each pitfall traces to a specific, cited line range in this repository (the
  circular-import risk, the pre-`setup_hook` fail-fast timing, the cross-key fallback semantic)
  rather than generic domain knowledge.
- Concurrency (CONC-01): HIGH — the core persistence claim was verified by direct local
  execution in this session, not asserted from training data alone.

**Research date:** 2026-07-19
**Valid until:** This is an internal-refactor phase with no external-library version risk;
research remains valid for the life of this phase's implementation (no expiry driven by
ecosystem drift — re-verify only if `core/db.py`'s connection-handling idiom changes before this
phase is planned/executed).
