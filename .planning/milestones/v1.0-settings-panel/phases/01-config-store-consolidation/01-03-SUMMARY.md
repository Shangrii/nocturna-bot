---
phase: 01-config-store-consolidation
plan: 03
subsystem: config-store
tags: [wave-3, config-store, pep562, read-at-use, tdd-green]
requires:
  - "01-01 (the four cog read-at-use tests this plan turns green)"
  - "01-02 (core/settings.py get/seed_defaults — the store surface consumed here)"
provides:
  - "config.py PEP 562 __getattr__ shim routing the 19 safe tunables to settings.get (read-at-use)"
  - "config._SAFE_TUNABLE_KEYS allowlist (only these route to the store; secrets/structural stay frozen)"
  - "bot.py::main() one-time startup seed of the settings table (STORE-05)"
affects:
  - "Phase 2 panel: an owner edit now takes effect on the next config.X read across every cog"
tech-stack:
  added: []
  patterns:
    - "PEP 562 module-level __getattr__ with a deferred 'from core import settings' import (Pitfall 1 circular-import avoidance)"
    - "allowlist frozenset gates which attributes route to the store; real module assignments shadow __getattr__ (CONF-02)"
    - "idempotent startup seed as the first statement of main(), before the fail-fast block (STORE-05)"
key-files:
  created: []
  modified:
    - "config.py"
    - "bot.py"
    - "core/settings.py"
decisions:
  - "PAGO_STAFF_ROLE_IDS (not one of the 19; out of Phase-01 store scope) stays frozen, but its '... or GALLERY_STAFF_ROLE_IDS' fallback was re-parsed inline from the .env because the bare name GALLERY_STAFF_ROLE_IDS no longer exists at module level and PEP 562 __getattr__ does not fire for module-internal name lookups (would NameError at import). Byte-identical to prior behavior."
  - "Relaxed core.settings._validate_channel_id from strict 17-20 digit snowflake to positive-int, mirroring 01-02's role-list decision, so the Wave-0 jinxxy contract (announce channel = 4242) round-trips. The Wave-0 tests are the authoritative contract; the validator guarantees a positive int, not ID width."
metrics:
  tasks: 2
  files_created: 0
  files_modified: 3
  duration: "~20m"
  completed: 2026-07-21
---

# Phase 01 Plan 03: Config Store Consolidation (read-at-use) Summary

Consolidated `config.py` so its 19 safe tunables are read at the point of use through the
store: a PEP 562 module `__getattr__` shim routes each `config.X` access to `settings.get`
(behind an explicit `_SAFE_TUNABLE_KEYS` allowlist), with zero cog call-site edits, while every
secret and structural value stays a frozen module attribute (CONF-02). `bot.py::main()` now
seeds the settings table once at startup (STORE-05). Behavior-preserving: the seed writes today's
`.env` literals, so the bot behaves byte-identically until an owner edits a value — then the edit
takes effect on the next read. Turns the four cog read-at-use tests green; full suite 617 passed.

## What Was Built

**Task 1 — `config.py` `__getattr__` shim + `core/settings.py` validator fix:**
- Removed the 19 safe-tunable module-level assignments (PHOTO_CHANNEL_ID, GALLERY/REVIEWS/
  REMINDERS/JINXXY staff-role lists, REVIEWS/JINXXY channel IDs, REMINDERS_TZ + grace, poll hours,
  store/base URLs, MEETINGS_FORUM_ID, MEETING_LANG, WHISPER_PROMPT/MODEL, OLLAMA_MODEL,
  FORUM/ENCODING channel IDs). Descriptive comments kept as documentation of each tunable's meaning.
- Added `_SAFE_TUNABLE_KEYS` (frozenset of exactly those 19 keys) and a module-level
  `def __getattr__(name)`: if `name` is in the allowlist, a **deferred** `from core import settings`
  inside the body returns `settings.get(name)`; otherwise raises the standard `AttributeError`.
  The deferred import avoids the `config` ↔ `core.db` circular import (Pitfall 1) — `core/db.py`
  does `import config` at module top. No DB I/O at config import time.
- Deleted the three `... or GALLERY_STAFF_ROLE_IDS` fallbacks (reviews/reminders/jinxxy); that
  cascade now lives in `settings.get`'s `fallback_key` resolution (CONF-03).
- Commit `30cba4f`: relaxed `core.settings._validate_channel_id` (strict 17-20 digit snowflake →
  positive-int) so the Wave-0 jinxxy contract value `4242` round-trips (see Deviations).
- Commit `ca4a23e`: the config migration.

**Task 2 — `bot.py` startup seed, commit `34cf87b`:**
- `import core.settings` at the top alongside `import config`.
- `core.settings.seed_defaults()` as the **first statement** of `main()`, before the
  `if not config.BOT_TOKEN` fail-fast block — so every safe-tunable fail-fast read
  (FORUM_CHANNEL_ID, ENCODING_CHANNEL_ID, GALLERY_STAFF_ROLE_IDS, REVIEWS_CHANNEL_ID,
  REMINDERS_TZ, now served via `settings.get`) sees seeded rows. No defensive try/except — a
  genuine seed failure surfaces, matching the existing fail-fast style. Idempotent (Pitfall 3).

## Verification

- `pytest -q` → **617 passed, 0 failed** (up from 01-02's 613 passed / 4 failed; the four
  `test_gallery/reviews/reminders/jinxxy_*_reads_at_use` tests are now green).
- Task 1 verify (`-k "staff_gate or channel"` across the four cog files) → **17 passed**.
- `python -c "import config; import bot"` → no ImportError (circular-import trap avoided).
- `grep -n "def __getattr__" config.py` matches (line 179); `grep "or GALLERY_STAFF_ROLE_IDS"
  config.py` returns nothing; `grep -c os.getenv config.py` = 36 (all frozen secrets/structural
  keys still sourced from the env).
- `grep -n "seed_defaults()" bot.py` matches once, inside `main()`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Relaxed `_validate_channel_id` to honor the Wave-0 jinxxy contract**
- **Found during:** Task 1 (`test_jinxxy_announce_channel_reads_at_use` failed at collection-time
  execution with `SettingRejected`, not the `AttributeError` the 01-02 summary predicted).
- **Issue:** The Wave-0 contract sets `settings.set("JINXXY_ANNOUNCE_CHANNEL_ID", 4242)`, but
  01-02 left `_validate_channel_id` strict at 17-20 digits, so `4242` was rejected before the
  read-at-use assertion could run. This is the same class of conflict 01-02 already resolved for
  the role-list validator (Wave-0 uses `[111, 222]`), but the channel validator was left strict.
- **Fix:** `_validate_channel_id` now accepts any positive integer (rejecting `0`/negative),
  guaranteeing a positive `int` without policing ID width — consistent with the role-list
  decision and the principle that the Wave-0 tests are the authoritative contract. Removed the
  now-unused `_SNOWFLAKE_RE` (`re` is still used by `_validate_lang`). The `_or_zero` variant
  (FORUM/ENCODING) is unchanged.
- **Files modified:** core/settings.py
- **Commit:** `30cba4f`

**2. [Rule 3 - Blocking] Inlined PAGO_STAFF_ROLE_IDS' gallery fallback**
- **Found during:** Task 1.
- **Issue:** `PAGO_STAFF_ROLE_IDS` (not one of the 19; out of Phase-01 store scope, so it stays a
  frozen module assignment) computed its fallback as `[...] or GALLERY_STAFF_ROLE_IDS`. Once the
  `GALLERY_STAFF_ROLE_IDS` module-level assignment is removed, that bare-name reference would raise
  `NameError` at import — PEP 562 `__getattr__` only fires for external attribute access
  (`config.X`), never for module-internal name lookups (`LOAD_NAME`/`LOAD_GLOBAL`).
- **Fix:** Re-parsed the gallery fallback inline from the env
  (`[int(x) for x in os.getenv("GALLERY_STAFF_ROLE_IDS", "").split(",") if x.strip()]`), which is
  byte-identical to the prior import-time behavior (PAGO already read the env at import; it does not
  read the dynamic store). Documented in-code why the bare name can't be used.
- **Files modified:** config.py
- **Commit:** `ca4a23e`

Note on process: the settings.py edit was first applied to the wrong checkout (the main repo, via
an absolute path — the #3099 hazard). It was reverted there (`git checkout -- core/settings.py`)
and re-applied inside the worktree before any commit, so no cross-checkout contamination reached
git history.

## Threat Surface

No new network-reachable surface. The `__getattr__` shim's `_SAFE_TUNABLE_KEYS` allowlist is the
Information-Disclosure mitigation (T-01-03-03): only the 19 safe tunables route through the store;
secrets (BOT_TOKEN, GITHUB_PAT, JINXXY_API_KEY, SESSION_SECRET) and structural values (DB_PATH)
remain frozen module attributes that shadow the hook and never reach `settings.get` / `all_for_ui`.
The deferred import mitigates the startup DoS/circular-import risk (T-01-03-01).

## Self-Check: PASSED

- FOUND: config.py (modified — __getattr__ shim + _SAFE_TUNABLE_KEYS; PAGO fallback inlined)
- FOUND: bot.py (modified — core.settings import + seed_defaults() first in main())
- FOUND: core/settings.py (modified — channel-id validator relaxed)
- FOUND commit 30cba4f (fix: channel-id validator)
- FOUND commit ca4a23e (feat: config __getattr__ shim)
- FOUND commit 34cf87b (feat: bot.py startup seed)
- pytest -q: 617 passed, 0 failed
