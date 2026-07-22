"""Pure sqlite state machine for durable panel-to-bot actions.

Phases 6-9 MUST confirm their real dispatch handlers finish well within
``_STALE_CLAIM_SECONDS`` before treating that threshold as frozen.
"""

# Source: this repo's core/db.py idiom (gallery_state / bot_heartbeat / discord_names),
# generalized per CONTEXT.md D-08/D-10 and PITFALLS.md Pitfall 3 retry guidance.
import json, sqlite3, time, functools
from datetime import datetime, timezone, timedelta
from core import db

_LOCK_RETRY_DELAYS = (0.05, 0.15, 0.4)   # 3 extra attempts beyond the first try
_MAX_DISPATCH_ATTEMPTS = 3               # D-06 "small bounded attempt count"
_BACKOFF_SECONDS = (2, 5, 15)            # attempt 1/2/3 requeue delay
_STALE_CLAIM_SECONDS = 60                # >> the ~1.5s tick; distinguishes crash from in-flight

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _retry_on_locked(fn):
    """Retries a write on 'database is locked' after busy_timeout itself is exhausted.
    Floor of D-11: applied ONLY to the new high-frequency action_queue write paths."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        last_exc = None
        for delay in (0.0,) + _LOCK_RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                return fn(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                last_exc = exc
        raise last_exc
    return wrapper

@_retry_on_locked
def enqueue(kind: str, payload: dict, requested_by: str) -> int:
    with db._get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (kind, json.dumps(payload), requested_by, _now_iso()),
        )
        return cur.lastrowid

@_retry_on_locked
def recover_stale_claims() -> int:
    """D-08: a 'claimed' row older than _STALE_CLAIM_SECONDS survived a bot crash
    mid-dispatch — requeue it so claim_next() retries it (at-least-once delivery)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_STALE_CLAIM_SECONDS)).isoformat()
    with db._get_conn() as conn:
        cur = conn.execute(
            "UPDATE action_queue SET status='pending' WHERE status='claimed' AND claimed_at < ?",
            (cutoff,),
        )
        return cur.rowcount

@_retry_on_locked
def claim_next() -> sqlite3.Row | None:
    """D-10: serialized, oldest-first. Skips rows still in backoff (next_attempt_at future)."""
    now = _now_iso()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM action_queue WHERE status='pending' "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY id LIMIT 1", (now,),
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "UPDATE action_queue SET status='claimed', claimed_at=? WHERE id=? AND status='pending'",
            (now, row["id"]),
        )
        if cur.rowcount == 0:
            return None   # defensive; single bot process makes this unreachable today
    return row

def _purge_terminal(conn, keep_last: int = 50):
    """D-03 keep-last-N, purge-on-write — but scoped to done|failed ONLY (Pitfall 1)."""
    conn.execute("""
        DELETE FROM action_queue
        WHERE status IN ('done', 'failed')
        AND id NOT IN (
            SELECT id FROM action_queue WHERE status IN ('done', 'failed')
            ORDER BY id DESC LIMIT ?
        )
    """, (keep_last,))

@_retry_on_locked
def complete(action_id: int, result: dict):
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET status='done', result_json=?, completed_at=? WHERE id=?",
            (json.dumps(result), _now_iso(), action_id),
        )
        _purge_terminal(conn)

@_retry_on_locked
def fail(action_id: int, error: str):
    """D-06 auto-retry with backoff, then D-02's terminal 'failed' + manual Retry."""
    with db._get_conn() as conn:
        row = conn.execute("SELECT attempts FROM action_queue WHERE id=?", (action_id,)).fetchone()
        attempts = (row["attempts"] if row else 0) + 1
        if attempts < _MAX_DISPATCH_ATTEMPTS:
            delay = _BACKOFF_SECONDS[min(attempts - 1, len(_BACKOFF_SECONDS) - 1)]
            next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
            conn.execute(
                "UPDATE action_queue SET status='pending', attempts=?, next_attempt_at=?, error=? "
                "WHERE id=?", (attempts, next_attempt, error, action_id),
            )
        else:
            conn.execute(
                "UPDATE action_queue SET status='failed', attempts=?, error=?, completed_at=? "
                "WHERE id=?", (attempts, error, _now_iso(), action_id),
            )
            _purge_terminal(conn)

@_retry_on_locked
def retry(action_id: int, requested_by: str) -> int | None:
    """D-02 manual Retry — re-enqueues a FRESH row from a terminal 'failed' row's kind+payload.
    Never mutates the old row in place (it stays as bounded history until purge)."""
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT kind, payload_json FROM action_queue WHERE id=? AND status='failed'",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        cur = conn.execute(
            "INSERT INTO action_queue (kind, payload_json, status, requested_by, requested_at) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (row["kind"], row["payload_json"], requested_by, _now_iso()),
        )
        return cur.lastrowid

def get_status(action_id: int) -> sqlite3.Row | None:
    with db._get_conn() as conn:
        return conn.execute("SELECT * FROM action_queue WHERE id=?", (action_id,)).fetchone()
