---
phase: 01-config-store-consolidation
reviewed: 2026-07-21T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - bot.py
  - config.py
  - core/db.py
  - core/settings.py
  - tests/test_gallery_cog.py
  - tests/test_jinxxy_cog.py
  - tests/test_reminders_cog.py
  - tests/test_reviews_cog.py
  - tests/test_settings.py
findings:
  critical: 0
  warning: 5
  info: 5
  total: 10
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-07-21T00:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the sqlite-backed config store (`core/settings.py` on WAL-enabled `core/db.py`),
the `config.py` consolidation (frozen literals removed, 19 safe tunables routed through
`config.__getattr__` → `settings.get`), the `bot.py` seed wiring, and the five Wave-0/regression
test suites.

Focus areas requested and their verdict:

- **Owner gate / fail-closed on unset `DISCORD_USER_ID`:** No owner-gate logic exists in the
  reviewed files (it lands in Phase 2). Confirmed `DISCORD_USER_ID` stays a *frozen* module
  attribute (`config.py:18`, default `0`) — it is NOT in `_SAFE_TUNABLE_KEYS`/`_SCHEMA`, so it can
  never route through `__getattr__`/the store, and an unset value stays `0`. That specific concern
  is not violated here.
- **PEP 562 shim / module-internal name resolution:** Sound. The deferred `from core import
  settings` inside `__getattr__` avoids the import cycle, `__getattr__` only fires for missing
  attributes (secrets shadow it), and the one internal bare-name hazard (`GALLERY_STAFF_ROLE_IDS`
  inside `PAGO_STAFF_ROLE_IDS`) is correctly re-parsed inline (`config.py:140-144`).
- **Injection in get/set:** Keys are allowlist-checked against `_SCHEMA` and passed only as `?`
  placeholders; values go through `json.dumps`. No SQL interpolation. Good.

No BLOCKER-level defects. Five WARNINGs concern fail-open-on-error behavior of the security-gate
reads, a typed-error contract gap in the numeric/ID validators, a "safe band" enforcement gap, a
cross-process table-existence hazard in `set()`, and a mutable-default aliasing hazard.

## Warnings

### WR-01: `get()` catch-all fallback silently reverts security gates to `.env` defaults (fail-open direction)

**File:** `core/settings.py:283-291`
**Issue:** `get()` wraps the DB read in `except Exception` and returns the schema/`.env` default on
*any* failure (locked-beyond-timeout, disk-full, corruption). The staff-role gates (`_is_staff` in
the gallery/reviews/reminders/jinxxy cogs) now read `config.*_STAFF_ROLE_IDS` through this path on
every reaction. If an owner has *tightened* a staff list via the panel (removed a role) but the
`.env` still lists it, a transient sqlite error during a gate check makes `get()` return the broader
`.env` default — re-authorizing the removed role for that read. For an authorization boundary the
error path resolves toward *more* access, not less. The window is narrow and requires a DB error, so
this is a WARNING rather than a deterministic bypass, but the direction is wrong for a gate.
**Fix:** Narrow the except to expected sqlite/JSON errors, and consider caching the last
*successfully-read* value per key so a transient error reuses the owner's last-known setting instead
of the `.env` seed:
```python
except (sqlite3.Error, json.JSONDecodeError, KeyError, TypeError) as e:
    log.warning("settings.get(%r) fell back to default: %s", key, e)
    value = _LAST_GOOD.get(key, default)
```
At minimum, document that a store read failure resolves to the `.env` seed and ensure the seed is
never broader than the panel value for role-list gates.

### WR-02: ID/role validators can raise a bare `ValueError` (not `SettingRejected`) on Unicode "digit" input

**File:** `core/settings.py:53-56, 66-68, 86-88`
**Issue:** `_validate_channel_id`, `_validate_channel_id_or_zero`, and `_validate_role_id_list` gate
on `str.isdigit()` then call `int()`. Some Unicode characters pass `isdigit()` but are not valid
integer literals (verified: `"²".isdigit()` is `True`, `int("²")` raises `ValueError`). In
`_validate_channel_id` the expression `if not s.isdigit() or int(s) <= 0:` short-circuits into
`int(s)`, which raises a plain `ValueError`. Because `SettingRejected` is a *subclass* of
`ValueError`, the Phase-2 HTTP layer that catches `except SettingRejected` (per the class docstring,
`core/settings.py:30-35`) will NOT catch this, and the raised object has no `.reason` attribute —
the panel 500s instead of returning a clean rejection.
**Fix:** Use `str.isdecimal()` (rejects `²`) or guard the conversion so every rejection is typed:
```python
s = str(value).strip()
if not s.isdecimal() or int(s) <= 0:
    raise SettingRejected("must be a positive channel/forum ID")
return int(s)
```
Apply the same to the `_or_zero` and role-list validators.

### WR-03: int-range validators are wider than the documented "safe band" (6–12h)

**File:** `core/settings.py:199 (REMINDERS_CATCHUP_GRACE_HOURS), 210 (JINXXY_POLL_HOURS)`
**Issue:** Both use `_make_int_range(1, 168)`, but `config.py:85` and `config.py:94-95` document these
tunables' safe band as **6–12h** (D-13 / D-03). The whole point of the panel is that it exposes only
*safe* values. As implemented, an owner can set `JINXXY_POLL_HOURS = 1`, polling the Jinxxy Creator
API hourly (rate-limit / ban risk), or set the catch-up grace to `168` (7 days), well outside the
intended window. The Wave-0 test only asserts `0` and `100000` are rejected and `8` accepted — it
never pins the band, so this drift is untested.
**Fix:** Enforce the documented band (or reconcile the docs if the band was intentionally widened):
```python
"JINXXY_POLL_HOURS": _Setting(..., _make_int_range(6, 12)),
"REMINDERS_CATCHUP_GRACE_HOURS": _Setting(..., _make_int_range(6, 12)),
```
and add a test asserting `5` and `13` are rejected.

### WR-04: `set()` assumes the `settings` table exists — cross-process ordering hazard

**File:** `core/settings.py:311-316`
**Issue:** `get()` is deliberately tolerant of a missing table (Pitfall 2, tested), but `set()` is
not: it runs `INSERT ... ON CONFLICT` with no `init_settings()` guard. The design (see `core/db.py:10-14`
and `config.py` comments) is explicitly two processes — the bot and the settings panel — sharing one
sqlite file, and `seed_defaults()`/`init_settings()` is called **only** from `bot.py::main()`
(`bot.py:96`). If the panel process starts (or an owner saves a setting) before the bot has ever run
`seed_defaults()` — fresh deploy, or bot crashed on boot — `set()` raises
`sqlite3.OperationalError: no such table: settings`, which is neither `SettingRejected` nor handled.
**Fix:** Make `set()` self-healing the same way `seed_defaults()` is, since `init_settings()` is
idempotent:
```python
if key not in _SCHEMA:
    raise SettingRejected(f"unknown setting key: {key!r}")
validated = _SCHEMA[key].validate(value)
db.init_settings()  # idempotent; get() already tolerates a missing table
with db._get_conn() as conn:
    ...
```

### WR-05: `get()` returns the schema default list by reference (mutable-default aliasing)

**File:** `core/settings.py:281-296`
**Issue:** On the no-row path, `default = descriptor.default` and `get()` returns that exact object.
For role-list tunables the default is a live `list` created once at import
(`_env_role_ids(...)`, `core/settings.py:167-171`). Every caller that reads, e.g.,
`config.GALLERY_STAFF_ROLE_IDS` when the DB row is unset gets the *same* list instance backing
`_SCHEMA`. Any in-place mutation by a caller (`.append`, `.sort`, `.remove`) permanently corrupts the
default for the whole process. The stored-row path is safe (`json.loads` returns a fresh list), so
the bug only bites before an owner saves that key. `_Setting` being `frozen=True` does not protect
the inner list.
**Fix:** Return a defensive copy of container defaults:
```python
value = (list(default) if isinstance(default, list) else default) if row is None \
    else json.loads(row["value"])
```

## Info

### IN-01: Public API names `get`/`set` shadow builtins module-wide

**File:** `core/settings.py:271, 299`
**Issue:** `def get` and `def set` shadow the builtins for the rest of the module. Harmless today
(no in-module use of builtin `set()`/`get`), but a future edit that reaches for `set(...)` inside
`core/settings.py` would silently call the module function. Consider a module `__all__` and/or a
short comment flagging the intentional shadow.

### IN-02: `get()` never re-type-checks the deserialized value

**File:** `core/settings.py:288, 294`
**Issue:** A stored value that is valid JSON but the wrong type (only reachable via direct DB
corruption, since `set()` always validates) is returned as-is. E.g. a role-list key holding `"5"`
→ `json.loads` → `int 5`, which then fails the `isinstance(value, list)` fallback check and is
returned as an `int` to a caller doing `set(role_ids)`. Consider re-running the descriptor's
validator on read (or at least an isinstance guard) so corruption degrades to the default rather than
propagating a wrong-typed value.

### IN-03: role-list validator accepts `0` as a role id; channel validator rejects `0`

**File:** `core/settings.py:86-88` vs `54`
**Issue:** `_validate_role_id_list` appends any `isdigit()` item including `"0"`, while
`_validate_channel_id` rejects `<= 0`. Harmless (role `0` never matches a real member, so the gate
stays fail-closed) but inconsistent. Reject non-positive role ids for symmetry.

### IN-04: `_SAFE_TUNABLE_KEYS` and `_SCHEMA` are two hand-maintained lists with no lockstep test

**File:** `config.py:156-176` and `core/settings.py:160-267`
**Issue:** `settings.get(key)` does `_SCHEMA[key]` *before* its try block, so a key present in
`config._SAFE_TUNABLE_KEYS` but missing from `_SCHEMA` would surface as an uncaught `KeyError`
(not the clean `AttributeError` the shim otherwise raises). The two 19-key lists currently match, but
nothing pins them together. Also note the error-surface asymmetry: `settings.get("BOGUS")` raises
`KeyError` while `settings.set("BOGUS", ...)` raises typed `SettingRejected`. Add a test asserting
`frozenset(config._SAFE_TUNABLE_KEYS) == set(settings._SCHEMA)`.

### IN-05: `_validate_url` validates scheme only, not host

**File:** `core/settings.py:125-130`
**Issue:** The check is `startswith("http://")/("https://")` only, so `"https://"` (no host) or
`"http:// /path"` pass. Owner-only input, low risk, but a minimal host check (e.g. `urlparse(...).netloc`)
would prevent a silently broken store/site link.

---

_Reviewed: 2026-07-21T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
