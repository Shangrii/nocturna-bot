"""DB-level tests for the Phase 8 Jinxxy sync-status mirror."""

import sqlite3

import config
from core import db


def _use_tmp_db(monkeypatch, tmp_path, name):
    db_path = tmp_path / name
    monkeypatch.setattr(config, "DB_PATH", str(db_path), raising=False)
    return db_path


def test_init_jinxxy_sync_status_migration_onto_existing_five_column_table(
    monkeypatch, tmp_path
):
    db_path = _use_tmp_db(monkeypatch, tmp_path, "migration.db")
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE jinxxy_sync_status (
                id            INTEGER PRIMARY KEY CHECK (id = 1),
                last_run_utc  TEXT,
                ok            INTEGER,
                product_count INTEGER,
                error         TEXT
            )
        """)
        conn.execute(
            """
            INSERT INTO jinxxy_sync_status
                (id, last_run_utc, ok, product_count, error)
            VALUES (1, ?, ?, ?, ?)
            """,
            ("2026-07-01T00:00:00+00:00", 1, 7, None),
        )

    db.init_jinxxy_sync_status()

    with db._get_conn() as conn:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jinxxy_sync_status)")
        }
        row = conn.execute(
            "SELECT product_count FROM jinxxy_sync_status WHERE id = ?",
            (1,),
        ).fetchone()
    assert {
        "running",
        "started_at",
        "source",
        "actor_name",
        "added_count",
        "updated_count",
        "removed_count",
    } <= columns
    assert row["product_count"] == 7


def test_init_jinxxy_sync_status_is_idempotent(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "idempotent.db")

    db.init_jinxxy_sync_status()
    with db._get_conn() as conn:
        first_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jinxxy_sync_status)")
        }

    db.init_jinxxy_sync_status()
    with db._get_conn() as conn:
        second_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(jinxxy_sync_status)")
        }

    assert second_columns == first_columns


def test_set_status_round_trips_counts(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "counts.db")
    db.init_jinxxy_sync_status()

    db.set_jinxxy_sync_status(
        ok=True,
        product_count=9,
        error=None,
        added_count=3,
        updated_count=2,
        removed_count=1,
    )

    row = db.get_jinxxy_sync_status()
    assert row["added_count"] == 3
    assert row["updated_count"] == 2
    assert row["removed_count"] == 1


def test_last_run_write_does_not_clobber_running_mirror(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "preserve-running.db")
    db.init_jinxxy_sync_status()

    db.mark_jinxxy_sync_running("panel", "Nombre")
    db.set_jinxxy_sync_status(ok=True, product_count=9, error=None)

    row = db.get_jinxxy_sync_status()
    assert row["running"] == 1
    assert row["source"] == "panel"
    assert row["actor_name"] == "Nombre"


def test_mark_and_clear_running_mirror(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "running.db")
    db.init_jinxxy_sync_status()

    db.mark_jinxxy_sync_running("scheduled")
    running_row = db.get_jinxxy_sync_status()
    assert running_row["running"] == 1
    assert running_row["started_at"] is not None

    db.clear_jinxxy_sync_running()
    cleared_row = db.get_jinxxy_sync_status()
    assert cleared_row["running"] == 0
    assert cleared_row["started_at"] is None
    assert cleared_row["source"] == "scheduled"


def test_never_synced_row_has_null_last_run_utc(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path, "never-synced.db")
    db.init_jinxxy_sync_status()

    db.clear_jinxxy_sync_running()

    row = db.get_jinxxy_sync_status()
    assert row is not None
    assert row["last_run_utc"] is None
