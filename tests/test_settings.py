"""Wave 0 (test-first) contract for the config store (Fase 01, plan 01-02).

These tests define the surface ``core/settings.py`` + ``core/db.init_settings`` must implement
in 01-02 (the store) and 01-03 (the consolidation). They are EXPECTED RED at the end of 01-01
because ``core/settings.py`` and ``core.db.init_settings`` do not exist yet — importing this
module errors at collection, which is the intended Wave 0 signal. Do NOT stub the store to turn
them green here; that is 01-02's job.

Structure mirrors ``tests/test_editors_model.py`` (plain ``assert`` / ``pytest.raises``, no heavy
fixtures). Every test isolates the database with ``monkeypatch.setattr(config, "DB_PATH", ...)``
pointed at a ``tmp_path`` file — matching ``tests/test_counter_app.py:23`` — so no test can ever
touch the real ``bot.db``. Values are written THROUGH the store (``settings.set`` or a direct row
insert), never via ``monkeypatch.setattr(config, "<safe-tunable>", ...)``, because patching a
module attribute would bypass the very store these tests exercise (and shadow the future
``config.__getattr__`` shim from 01-03).
"""

import sqlite3

import pytest

import config
import core.db as db
import core.settings as settings


def _use_tmp_db(monkeypatch, tmp_path, name="settings.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


# ── STORE-01: get/set/all_for_ui round-trip through the settings table ────────────
def test_round_trip_get_set(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    settings.set("PHOTO_CHANNEL_ID", 1416329356426481717)
    assert settings.get("PHOTO_CHANNEL_ID") == 1416329356426481717


# ── STORE-02: init_settings() creates the table (CREATE TABLE IF NOT EXISTS idiom) ─
def test_init_table_creates_settings(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with db._get_conn() as conn:
        conn.execute("SELECT key, value FROM settings").fetchall()   # table exists
    db.init_settings()                                               # idempotent — no raise


# ── STORE-03: per-type validation — reject invalid, write nothing, raise SettingRejected ──
def test_validation_rejects_bad_snowflake(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with pytest.raises(settings.SettingRejected):
        settings.set("PHOTO_CHANNEL_ID", "abc")
    # nothing was written → get falls back to the default, never the rejected value
    assert settings.get("PHOTO_CHANNEL_ID") != "abc"
    assert settings.get("PHOTO_CHANNEL_ID") == config.PHOTO_CHANNEL_ID


def test_validation_rejects_bad_interval(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with pytest.raises(settings.SettingRejected):
        settings.set("JINXXY_POLL_HOURS", 0)          # below the allowed band
    with pytest.raises(settings.SettingRejected):
        settings.set("JINXXY_POLL_HOURS", 100000)     # far out of range


def test_validation_rejects_bad_timezone(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with pytest.raises(settings.SettingRejected):
        settings.set("REMINDERS_TZ", "Not/AZone")
    settings.set("REMINDERS_TZ", "America/Mexico_City")   # a real IANA zone is accepted
    assert settings.get("REMINDERS_TZ") == "America/Mexico_City"


def test_validation_accepts_free_string_model(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    # Pitfall 4: model names are free strings, not an enum — an uncommon name is valid.
    settings.set("WHISPER_MODEL", "some-uncommon-model")
    assert settings.get("WHISPER_MODEL") == "some-uncommon-model"


# ── STORE-04: get never raises — missing row / missing table / corrupt JSON → default ──
def test_fallback_missing_row(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()                                   # table exists, key unset
    assert settings.get("PHOTO_CHANNEL_ID") == config.PHOTO_CHANNEL_ID


def test_fallback_missing_table(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    # Pitfall 2: WITHOUT init_settings() the table is absent — get must not raise "no such table".
    assert settings.get("PHOTO_CHANNEL_ID") == config.PHOTO_CHANNEL_ID


def test_fallback_corrupt_json(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with db._get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?)",
            ("PHOTO_CHANNEL_ID", "{not valid json"),
        )
        conn.commit()
    # a corrupt stored value falls back to the default instead of raising
    assert settings.get("PHOTO_CHANNEL_ID") == config.PHOTO_CHANNEL_ID


# ── STORE-05: idempotent seed — running twice is a no-op that matches .env defaults ──
def test_seed_idempotent(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    settings.seed_defaults()

    def _rows():
        with db._get_conn() as conn:
            return {r[0]: r[1] for r in conn.execute("SELECT key, value FROM settings")}

    first = _rows()
    settings.seed_defaults()                             # second call — must change nothing
    second = _rows()
    assert first == second
    assert len(first) == len(second)
    # each seeded value equals the corresponding config default
    assert settings.get("PHOTO_CHANNEL_ID") == config.PHOTO_CHANNEL_ID
    assert settings.get("JINXXY_POLL_HOURS") == config.JINXXY_POLL_HOURS


# ── CONF-03: staff-role fallback to GALLERY_STAFF_ROLE_IDS when the specific list is empty ──
def test_staff_role_fallback_to_gallery(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    settings.set("GALLERY_STAFF_ROLE_IDS", [111, 222])
    # the specific lists are unset in the DB → each composes down to the gallery list
    assert settings.get("REVIEWS_STAFF_ROLE_IDS") == [111, 222]
    assert settings.get("REMINDERS_STAFF_ROLE_IDS") == [111, 222]
    assert settings.get("JINXXY_STAFF_ROLE_IDS") == [111, 222]


# ── STORE-01: all_for_ui is grouped and never leaks a secret / structural key ─────
def test_all_for_ui_grouped(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    grouped = settings.all_for_ui()
    assert isinstance(grouped, list) and grouped              # grouped descriptor list
    blob = repr(grouped)
    for secret in ("BOT_TOKEN", "GITHUB_PAT", "JINXXY_API_KEY", "SESSION_SECRET", "DB_PATH"):
        assert secret not in blob                             # secrets/structural keys absent


# ── CONC-01: WAL journal mode is active after _get_conn() ─────────────────────────
def test_wal_mode_active(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    with db._get_conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"


# ── CONC-01: a held read + a concurrent write do not collide with "database is locked" ──
def test_wal_concurrent_read_write(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_settings()
    settings.set("PHOTO_CHANNEL_ID", 1416329356426481717)
    reader = db._get_conn()
    try:
        cur = reader.execute("SELECT key FROM settings")
        cur.fetchone()                                       # hold an open read cursor
        try:
            settings.set("JINXXY_POLL_HOURS", 8)             # write on a second connection
        except sqlite3.OperationalError as exc:              # pragma: no cover - failure path
            pytest.fail(f"WAL should permit a concurrent write: {exc}")
    finally:
        reader.close()
