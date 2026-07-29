"""Durable sqlite storage tests for Phase 9 meetings."""

import json

import config
from core import db


def _use_tmp_db(monkeypatch, tmp_path, name):
    db_path = tmp_path / name
    monkeypatch.setattr(config, "DB_PATH", str(db_path), raising=False)
    db.init_meetings()
    return db_path


def _insert_meeting(**overrides):
    values = {
        "tema": "Phase 9 planning",
        "started_at": "2026-07-29T15:00:00+00:00",
        "ended_at": "2026-07-29T16:00:00+00:00",
        "attendees": ["Ari", "Nox"],
        "notes": ["Confirm schema", "Keep transcript immutable"],
        "transcript": "Ari: Let's persist this.\nNox: Agreed.",
        "summary": "Agreed on the durable meetings schema.",
        "thread_id": None,
        "starter_message_id": None,
    }
    values.update(overrides)
    return db.insert_meeting(**values)


def test_init_and_insert_round_trip_every_meeting_field(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "round-trip.db")
    db.init_meetings()  # Idempotent on an already initialized database.

    meeting_id = _insert_meeting()
    row = db.get_meeting(meeting_id)

    assert meeting_id == 1
    assert row["tema"] == "Phase 9 planning"
    assert row["started_at"] == "2026-07-29T15:00:00+00:00"
    assert row["ended_at"] == "2026-07-29T16:00:00+00:00"
    assert json.loads(row["attendees_json"]) == ["Ari", "Nox"]
    assert json.loads(row["notes_json"]) == [
        "Confirm schema",
        "Keep transcript immutable",
    ]
    assert row["transcript"] == "Ari: Let's persist this.\nNox: Agreed."
    assert row["summary"] == "Agreed on the durable meetings schema."
    assert row["thread_id"] is None
    assert row["starter_message_id"] is None
    assert row["created_at"]


def test_inserted_meeting_survives_a_fresh_connection(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "persistence.db")
    meeting_id = _insert_meeting(tema="Persistent meeting")

    with db._get_conn() as fresh_conn:
        row = fresh_conn.execute(
            "SELECT tema, transcript FROM meetings WHERE id = ?",
            (meeting_id,),
        ).fetchone()

    assert row["tema"] == "Persistent meeting"
    assert row["transcript"] == "Ari: Let's persist this.\nNox: Agreed."


def test_list_meetings_orders_by_started_at_then_id_newest_first(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path, "ordering.db")
    oldest_id = _insert_meeting(
        tema="Oldest",
        started_at="2026-07-27T10:00:00+00:00",
    )
    tied_older_id = _insert_meeting(
        tema="Tied, lower id",
        started_at="2026-07-29T10:00:00+00:00",
    )
    tied_newer_id = _insert_meeting(
        tema="Tied, higher id",
        started_at="2026-07-29T10:00:00+00:00",
    )

    rows = db.list_meetings()

    assert [row["id"] for row in rows] == [
        tied_newer_id,
        tied_older_id,
        oldest_id,
    ]


def test_summary_update_preserves_other_fields_and_thread_lookup(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path, "update-and-lookup.db")
    meeting_id = _insert_meeting(
        tema="Do not overwrite",
        transcript="Original transcript",
        summary="Original summary",
        thread_id=987654321,
        starter_message_id=987654322,
    )

    db.update_meeting_summary(meeting_id, "Corrected summary")

    row = db.get_meeting(meeting_id)
    assert row["summary"] == "Corrected summary"
    assert row["tema"] == "Do not overwrite"
    assert row["transcript"] == "Original transcript"
    assert row["thread_id"] == 987654321
    assert row["starter_message_id"] == 987654322
    assert db.get_meeting_by_thread_id(987654321)["id"] == meeting_id
    assert db.get_meeting_by_thread_id(111111111) is None
