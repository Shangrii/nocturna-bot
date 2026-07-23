"""DB-level tests for reminder migrations, pausing, and optimistic concurrency."""

import sqlite3

import config
from core import db


NOW_ISO = "2026-07-08T15:00:00+00:00"


def _use_tmp_db(monkeypatch, tmp_path, filename="reminders.db"):
    db_path = tmp_path / filename
    monkeypatch.setattr(config, "DB_PATH", str(db_path), raising=False)
    return db_path


def _add_weekly(*, next_fire_utc=NOW_ISO):
    return db.add_reminder(
        name="Junta",
        frequency="weekly",
        weekday=0,
        hour=9,
        minute=0,
        channel_id=1,
        message="x",
        created_by=1,
        next_fire_utc=next_fire_utc,
    )


def test_init_reminders_migrates_paused_version_onto_existing_table(monkeypatch, tmp_path):
    db_path = _use_tmp_db(monkeypatch, tmp_path, "migration.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE reminders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                frequency     TEXT    NOT NULL,
                weekday       INTEGER,
                day_of_month  INTEGER,
                run_date      TEXT,
                hour          INTEGER NOT NULL,
                minute        INTEGER NOT NULL,
                channel_id    INTEGER NOT NULL,
                message       TEXT    NOT NULL,
                mentions      TEXT    DEFAULT '',
                reactions     TEXT    DEFAULT '',
                next_fire_utc TEXT    NOT NULL,
                created_by    INTEGER NOT NULL,
                created_at    TEXT    NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO reminders
                (name, frequency, weekday, hour, minute, channel_id, message,
                 next_fire_utc, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, ("Existente", "weekly", 0, 9, 0, 1, "No borrar", NOW_ISO, 1, NOW_ISO))

    db.init_reminders()

    with db._get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(reminders)")}
        row = conn.execute(
            "SELECT name, paused, version FROM reminders WHERE name = ?",
            ("Existente",),
        ).fetchone()
    assert {"paused", "version"} <= columns
    assert row["name"] == "Existente"
    assert row["paused"] == 0
    assert row["version"] == 1


def test_update_reminder_bumps_version_and_rejects_stale(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_reminders()
    rid = _add_weekly()
    assert db.get_reminder(rid)["version"] == 1

    assert db.update_reminder(rid, name="Nueva junta") is True
    updated = db.get_reminder(rid)
    assert updated["name"] == "Nueva junta"
    assert updated["version"] == 2

    assert db.update_reminder(rid, expected_version=1, name="Stale") is False
    final = db.get_reminder(rid)
    assert final["name"] == "Nueva junta"
    assert final["version"] == 2


def test_due_reminders_excludes_paused(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_reminders()
    rid = _add_weekly(next_fire_utc="2026-07-08T14:00:00+00:00")

    assert db.update_reminder(rid, paused=1) is True
    assert [row["id"] for row in db.due_reminders(NOW_ISO)] == []

    assert db.update_reminder(rid, paused=0) is True
    assert [row["id"] for row in db.due_reminders(NOW_ISO)] == [rid]


def test_set_next_fire_bumps_version(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_reminders()
    rid = _add_weekly()
    next_iso = "2026-07-15T15:00:00+00:00"

    assert db.set_next_fire(rid, next_iso, expected_version=1) is True
    row = db.get_reminder(rid)
    assert row["next_fire_utc"] == next_iso
    assert row["version"] == 2


def test_delete_reminder_rejects_stale_version(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_reminders()
    rid = _add_weekly()
    assert db.update_reminder(rid, name="Versión nueva") is True

    assert db.delete_reminder(rid, expected_version=1) is False
    assert db.get_reminder(rid) is not None

    assert db.delete_reminder(rid, expected_version=2) is True
    assert db.get_reminder(rid) is None


def test_scheduler_writeback_never_clobbers_concurrent_panel_edit(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "race.db")
    db.init_reminders()
    rid = _add_weekly()

    stale_row = db.due_reminders(NOW_ISO)[0]
    assert stale_row["version"] == 1

    panel_next_fire = "2026-07-10T09:00:00+00:00"
    assert db.update_reminder(
        rid,
        weekday=4,
        next_fire_utc=panel_next_fire,
    ) is True

    stale_next_fire = "2026-07-13T09:00:00+00:00"
    assert db.set_next_fire(
        rid,
        stale_next_fire,
        expected_version=stale_row["version"],
    ) is False

    final = db.get_reminder(rid)
    assert final["next_fire_utc"] == panel_next_fire
    assert final["weekday"] == 4
    assert final["version"] == 2
