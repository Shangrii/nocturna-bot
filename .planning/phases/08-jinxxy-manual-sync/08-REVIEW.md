---
phase: 08-jinxxy-manual-sync
reviewed: 2026-07-28T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - cogs/action_queue_worker.py
  - tests/test_action_queue_cog.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 08: Code Review Report

**Reviewed:** 2026-07-28T00:00:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed the `jinxxy_sync` dispatch handler (`ActionQueueCog._handle_jinxxy_sync`,
`cogs/action_queue_worker.py:181-209`) added by plan 08-05 and its tests
(`tests/test_action_queue_cog.py:367-498`), against the four focus areas: correctness,
D-10 error-category mapping / no upstream-string leakage, result shaping, and the
guarded-wrapper delegation contract.

The core contract is implemented correctly and I found **no BLOCKER**:

- **Delegation** — the handler resolves the cog via `get_cog("Jinxxy")` and delegates
  entirely to `_run_sync_guarded(source="panel", actor_name=...)`. It never calls
  `_run_sync`, `_announce`, or touches the sync lock (verified against
  `cogs/jinxxy.py:368-397`).
- **D-10 mapping** — every exception in the delegated path (including the missing-cog
  `RuntimeError`) is caught and re-raised as `RuntimeError(sync_error_category(exc))`,
  which classifies strictly by exception *type* (`cogs/jinxxy.py:88-100`). `action_queue.fail`
  stores `str(exc)` (`core/action_queue.py:139,144`) — the mapped category only; the
  `raise ... from exc` cause chain is not serialized, so upstream URLs/status codes never
  reach the failure record. Tests at lines 457-485 confirm this.
- **Result shaping** — the success path emits only integer counts, never the raw product
  payload; the `checkout_url`-absent assertion (line 441) confirms it.

The findings below are latent-robustness and test-coverage gaps, not behavioral defects in
the happy/known-failure paths that the suite exercises.

## Warnings

### WR-01: Result-shaping block sits outside the D-10 error-mapping try/except

**File:** `cogs/action_queue_worker.py:200-209`
**Issue:** The `try/except` that maps every failure through `sync_error_category` closes at
line 198. The result-shaping block (`result.get("already")`, `len(result.get("added") or [])`,
etc.) runs *after* it, unguarded. This block trusts the `_run_sync_guarded` return contract
absolutely: if that method ever returned `None`, a non-dict, or a dict whose `added`/`updated`/
`removed`/`products` value is a non-list truthy value that `len()` rejects (e.g. an `int`), the
resulting `AttributeError`/`TypeError` escapes the mapping and is recorded verbatim by
`action_queue.fail(row["id"], str(exc))`. That is exactly the raw-Python-error leakage into the
failure record that D-10 exists to prevent, and it bypasses the type-based category bucketing.
It is currently unreachable (today `reconcile_store` returns lists and `_run_sync_guarded`
always returns a dict), but the safety net does not cover the shaping step, so a future change
to `_run_sync`'s return shape would silently reopen the D-10 hole.
**Fix:** Move the shaping inside the guarded block so any shaping failure is also mapped:
```python
try:
    jinxxy_cog = self.bot.get_cog("Jinxxy")
    if jinxxy_cog is None:
        raise RuntimeError("JinxxyCog no está cargado · JinxxyCog is not loaded")
    result = await jinxxy_cog._run_sync_guarded(source="panel", actor_name=actor_name)
    if result.get("already"):
        return {"already": True}
    return {
        "already": False,
        "changed": bool(result.get("changed")),
        "added": len(result.get("added") or []),
        "updated": len(result.get("updated") or []),
        "removed": len(result.get("removed") or []),
        "products": len(result.get("products") or []),
    }
except Exception as exc:
    log.exception("action_queue: jinxxy_sync falló")
    raise RuntimeError(sync_error_category(exc)) from exc
```

### WR-02: The load-bearing cog lookup key `"Jinxxy"` is never verified against a real JinxxyCog

**File:** `cogs/action_queue_worker.py:190` (test gap: `tests/test_action_queue_cog.py:369-377`)
**Issue:** Dispatch depends on `self.bot.get_cog("Jinxxy")` resolving to the real cog. Unlike the
gallery/review handlers, whose keys are class names (`GalleryCog`/`ReviewsCog`), this key is the
`GroupCog` `name=` override (`cogs/jinxxy.py:155`) — a value that lives *only* in a class-decl
kwarg and a source comment. No test instantiates `JinxxyCog` and asserts its
`qualified_name == "Jinxxy"`; every jinxxy test uses a `SimpleNamespace` stub keyed on the literal
string (`_build_jinxxy_bot`, lines 369-377). If the `name=` kwarg were renamed or dropped,
production dispatch would silently degrade to the generic-error path (`get_cog` → `None` →
mapped `_ERR_GENERIC`, action fails), while the entire suite stays green. The ambiguity is live:
a sibling planning doc still records the wrong key (`08-PATTERNS.md:158` says
`get_cog("JinxxyCog")`), which is precisely the mistake the fix corrected.
**Fix:** Add one integration-style test that constructs a real `JinxxyCog` (or asserts
`JinxxyCog.__cog_name__ == "Jinxxy"`) so the exact lookup string is pinned by code, not just by a
comment. Example: `assert JinxxyCog(bot).qualified_name == "Jinxxy"`.

## Info

### IN-01: Duplicate traceback logging on every jinxxy_sync failure

**File:** `cogs/action_queue_worker.py:197` and `cogs/action_queue_worker.py:61`
**Issue:** The handler calls `log.exception("action_queue: jinxxy_sync falló")` in its own
`except`, then re-raises; `_run_once` (line 61) then logs `log.exception("action_queue: acción %s
falló", row["id"])` for the same failure. Every `jinxxy_sync` failure therefore emits two full
stack traces per attempt (six per exhausted retry budget). The sibling handlers
(`gallery_publish`, etc.) do not self-log — they rely solely on `_run_once`. This is noise and an
inconsistency, not a leak (both traces stay in operator logs, as D-10 intends).
**Fix:** Drop the handler-local `log.exception` and rely on `_run_once`'s single log site, or
downgrade the handler line to `log.debug` if the pre-mapping original exception detail is wanted
at that point.

### IN-02: No test covers a genuine ran-but-unchanged success (`changed=False`, empty lists)

**File:** `tests/test_action_queue_cog.py:392-419`
**Issue:** `test_jinxxy_sync_dispatch_completes_with_shaped_counts` only exercises the
`changed=True` path with every list populated. The `{"already": False, "changed": False, ...}`
branch — a sync that actually ran but produced no changes — and the `len(... or [])` guard when the
value is `[]` (as opposed to a populated list) are never asserted. This is the common
steady-state outcome in production and is untested.
**Fix:** Add a case with `_build_jinxxy_bot({"changed": False, "added": [], "updated": [],
"removed": [], "products": []})` asserting the result is
`{"already": False, "changed": False, "added": 0, "updated": 0, "removed": 0, "products": 0}`.

---

_Reviewed: 2026-07-28T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
