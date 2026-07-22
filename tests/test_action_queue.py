"""State-machine contract for the shared sqlite action queue (INFRA-01/02)."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import config
from core import action_queue, db


def _use_tmp_db(monkeypatch, tmp_path, name="action_queue.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def _init_queue(monkeypatch, tmp_path, name="action_queue.db"):
    _use_tmp_db(monkeypatch, tmp_path, name=name)
    db.init_action_queue()


def _make_due(action_id):
    due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET next_attempt_at=? WHERE id=?",
            (due, action_id),
        )


def test_enqueue_then_claim_consumes_single_pending(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)

    action_id = action_queue.enqueue("noop", {"value": 1}, requested_by="manager-1")
    claimed = action_queue.claim_next()

    assert claimed["id"] == action_id
    assert json.loads(claimed["payload_json"]) == {"value": 1}
    assert action_queue.get_status(action_id)["status"] == "claimed"
    assert action_queue.claim_next() is None


def test_claim_next_returns_oldest_pending_first(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    first_id = action_queue.enqueue("first", {}, requested_by="manager-1")
    second_id = action_queue.enqueue("second", {}, requested_by="manager-1")

    assert action_queue.claim_next()["id"] == first_id
    assert action_queue.claim_next()["id"] == second_id


def test_claim_next_skips_rows_still_in_backoff(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    backed_off_id = action_queue.enqueue("backed-off", {}, requested_by="manager-1")
    ready_id = action_queue.enqueue("ready", {}, requested_by="manager-1")
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET next_attempt_at=? WHERE id=?",
            (future, backed_off_id),
        )

    assert action_queue.claim_next()["id"] == ready_id
    assert action_queue.get_status(backed_off_id)["status"] == "pending"


def test_complete_records_done_result(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    action_id = action_queue.enqueue("noop", {}, requested_by="manager-1")
    action_queue.claim_next()

    action_queue.complete(action_id, {"ok": True})

    row = action_queue.get_status(action_id)
    assert row["status"] == "done"
    assert json.loads(row["result_json"]) == {"ok": True}
    assert row["completed_at"]


def test_fail_requeues_with_backoff_then_marks_terminal_failed(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    action_id = action_queue.enqueue("noop", {}, requested_by="manager-1")

    for expected_attempts in range(1, action_queue._MAX_DISPATCH_ATTEMPTS):
        assert action_queue.claim_next()["id"] == action_id
        before = datetime.now(timezone.utc)
        action_queue.fail(action_id, f"failure-{expected_attempts}")
        row = action_queue.get_status(action_id)
        assert row["status"] == "pending"
        assert row["attempts"] == expected_attempts
        assert datetime.fromisoformat(row["next_attempt_at"]) > before
        _make_due(action_id)

    assert action_queue.claim_next()["id"] == action_id
    action_queue.fail(action_id, "terminal failure")

    row = action_queue.get_status(action_id)
    assert row["status"] == "failed"
    assert row["attempts"] == action_queue._MAX_DISPATCH_ATTEMPTS
    assert row["error"] == "terminal failure"
    assert row["completed_at"]


def test_purge_never_deletes_pending(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    pending_id = action_queue.enqueue("offline-pending", {}, requested_by="manager-1")

    keep_last = 50
    for index in range(keep_last + 5):
        other_id = action_queue.enqueue("terminal", {"index": index}, requested_by="manager-1")
        action_queue.complete(other_id, {"ok": True})

    assert action_queue.get_status(pending_id)["status"] == "pending"
    with db._get_conn() as conn:
        terminal_count = conn.execute(
            "SELECT COUNT(*) FROM action_queue WHERE status IN ('done', 'failed')"
        ).fetchone()[0]
    assert terminal_count == keep_last


def test_recover_stale_claims_requeues_orphan(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    action_id = action_queue.enqueue("noop", {}, requested_by="manager-1")
    action_queue.claim_next()
    stale = (
        datetime.now(timezone.utc)
        - timedelta(seconds=action_queue._STALE_CLAIM_SECONDS + 1)
    ).isoformat()
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE action_queue SET claimed_at=? WHERE id=?",
            (stale, action_id),
        )

    assert action_queue.recover_stale_claims() == 1
    assert action_queue.get_status(action_id)["status"] == "pending"


def test_recover_stale_claims_leaves_fresh_claim_in_flight(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    action_id = action_queue.enqueue("noop", {}, requested_by="manager-1")
    action_queue.claim_next()

    assert action_queue.recover_stale_claims() == 0
    assert action_queue.get_status(action_id)["status"] == "claimed"
    assert action_queue.claim_next() is None


def test_retry_mints_fresh_row_only_from_failed(monkeypatch, tmp_path):
    _init_queue(monkeypatch, tmp_path)
    pending_id = action_queue.enqueue("pending", {}, requested_by="manager-1")
    claimed_id = action_queue.enqueue("claimed", {}, requested_by="manager-1")
    done_id = action_queue.enqueue("done", {}, requested_by="manager-1")
    failed_id = action_queue.enqueue("failed", {"source": "original"}, requested_by="manager-1")
    with db._get_conn() as conn:
        conn.execute("UPDATE action_queue SET status='claimed' WHERE id=?", (claimed_id,))
        conn.execute("UPDATE action_queue SET status='done' WHERE id=?", (done_id,))
        conn.execute("UPDATE action_queue SET status='failed' WHERE id=?", (failed_id,))

    assert action_queue.retry(pending_id, "manager-2") is None
    assert action_queue.retry(claimed_id, "manager-2") is None
    assert action_queue.retry(done_id, "manager-2") is None

    retry_id = action_queue.retry(failed_id, "manager-2")
    assert retry_id not in {None, failed_id}
    original = action_queue.get_status(failed_id)
    retried = action_queue.get_status(retry_id)
    assert original["status"] == "failed"
    assert retried["status"] == "pending"
    assert retried["kind"] == original["kind"]
    assert retried["payload_json"] == original["payload_json"]
    assert retried["requested_by"] == "manager-2"
    assert retried["attempts"] == 0


def test_retry_on_locked_retries_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(action_queue.time, "sleep", sleeps.append)
    calls = 0

    @action_queue._retry_on_locked
    def flaky_write():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert flaky_write() == "ok"
    assert calls == 3
    assert sleeps == [0.05, 0.15]


def test_retry_on_locked_reraises_after_bounded_attempts(monkeypatch):
    sleeps = []
    monkeypatch.setattr(action_queue.time, "sleep", sleeps.append)
    errors = []

    @action_queue._retry_on_locked
    def always_locked():
        exc = sqlite3.OperationalError(f"database is locked #{len(errors) + 1}")
        errors.append(exc)
        raise exc

    with pytest.raises(sqlite3.OperationalError) as caught:
        always_locked()

    assert caught.value is errors[-1]
    assert len(errors) == 1 + len(action_queue._LOCK_RETRY_DELAYS)
    assert sleeps == list(action_queue._LOCK_RETRY_DELAYS)


def test_retry_on_locked_does_not_retry_other_operational_errors(monkeypatch):
    sleeps = []
    monkeypatch.setattr(action_queue.time, "sleep", sleeps.append)

    @action_queue._retry_on_locked
    def invalid_write():
        raise sqlite3.OperationalError("no such table: action_queue")

    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        invalid_write()
    assert sleeps == []

