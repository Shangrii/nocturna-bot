"""Queue-layer tests for Phase 8's Jinxxy sync enqueue dedupe."""

import config
from core import action_queue, db


def _use_tmp_db(monkeypatch, tmp_path, name):
    db_path = tmp_path / name
    monkeypatch.setattr(config, "DB_PATH", str(db_path), raising=False)
    db.init_action_queue()
    return db_path


def _kind_count(kind):
    with db._get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM action_queue WHERE kind = ?",
            (kind,),
        ).fetchone()["n"]


def test_enqueue_deduped_returns_existing_pending_id(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "pending.db")

    first_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-1"
    )
    second_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-2"
    )

    assert second_id == first_id
    assert _kind_count("jinxxy_sync") == 1


def test_enqueue_deduped_returns_existing_claimed_id(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "claimed.db")
    first_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-1"
    )

    claimed = action_queue.claim_next()
    second_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-2"
    )

    assert claimed["id"] == first_id
    assert second_id == first_id
    assert _kind_count("jinxxy_sync") == 1


def test_enqueue_deduped_inserts_after_completion(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "completed.db")
    first_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-1"
    )
    action_queue.complete(first_id, {})

    second_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-2"
    )

    assert second_id != first_id
    assert _kind_count("jinxxy_sync") == 2


def test_enqueue_deduped_does_not_dedupe_across_kinds(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "different-kinds.db")

    sync_id = action_queue.enqueue_deduped(
        "jinxxy_sync", {}, requested_by="manager-1"
    )
    noop_id = action_queue.enqueue_deduped(
        "noop", {}, requested_by="manager-1"
    )

    assert noop_id != sync_id
    assert _kind_count("jinxxy_sync") == 1
    assert _kind_count("noop") == 1


def test_enqueue_deduped_scopes_meeting_republish_by_dedupe_key(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path, "meeting-keys.db")

    id_same_a = action_queue.enqueue_deduped(
        "meeting_republish",
        {"meeting_id": 1},
        requested_by="manager-1",
        dedupe_key="meeting_republish:1",
    )
    id_same_b = action_queue.enqueue_deduped(
        "meeting_republish",
        {"meeting_id": 1},
        requested_by="manager-2",
        dedupe_key="meeting_republish:1",
    )
    id_diff_1 = id_same_a
    id_diff_2 = action_queue.enqueue_deduped(
        "meeting_republish",
        {"meeting_id": 2},
        requested_by="manager-2",
        dedupe_key="meeting_republish:2",
    )

    assert id_same_a == id_same_b
    assert id_diff_1 != id_diff_2
    assert _kind_count("meeting_republish") == 2
