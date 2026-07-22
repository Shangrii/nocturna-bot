"""Database contract for the bot-pushed Discord channel/role name cache."""

import config
import core.db as db


def _use_tmp_db(monkeypatch, tmp_path, name="discord_names.db"):
    """Point every ``_get_conn()`` at a throwaway sqlite file (never bot.db)."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def test_init_discord_names_creates_text_id_table_idempotently(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)

    db.init_discord_names()
    db.init_discord_names()

    with db._get_conn() as conn:
        columns = {
            row["name"]: row["type"]
            for row in conn.execute("PRAGMA table_info(discord_names)").fetchall()
        }
    assert columns == {
        "id": "TEXT",
        "kind": "TEXT",
        "name": "TEXT",
        "subtype": "TEXT",
        "color": "TEXT",
        "synced_at": "TEXT",
    }


def test_replace_discord_names_round_trips_string_snowflake(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_discord_names()

    db.replace_discord_names([
        (1416329356426481717, "channel", "gallery", "text", None),
        ("1453560115423875205", "role", "Manager", None, "#8b93a3"),
    ])

    rows = db.get_discord_names()
    by_id = {row["id"]: dict(row) for row in rows}
    assert by_id == {
        "1416329356426481717": {
            "id": "1416329356426481717",
            "kind": "channel",
            "name": "gallery",
            "subtype": "text",
            "color": None,
            "synced_at": by_id["1416329356426481717"]["synced_at"],
        },
        "1453560115423875205": {
            "id": "1453560115423875205",
            "kind": "role",
            "name": "Manager",
            "subtype": None,
            "color": "#8b93a3",
            "synced_at": by_id["1453560115423875205"]["synced_at"],
        },
    }
    assert by_id["1416329356426481717"]["synced_at"]
    assert (
        by_id["1416329356426481717"]["synced_at"]
        == by_id["1453560115423875205"]["synced_at"]
    )


def test_replace_discord_names_drops_deleted_rows(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_discord_names()
    db.replace_discord_names([
        ("111", "channel", "keep-for-now", "text", None),
        ("222", "role", "deleted-later", None, "#123456"),
    ])

    db.replace_discord_names([
        ("111", "channel", "only-survivor", "forum", None),
    ])

    rows = db.get_discord_names()
    assert len(rows) == 1
    assert {key: rows[0][key] for key in ("id", "kind", "name", "subtype", "color")} == {
        "id": "111",
        "kind": "channel",
        "name": "only-survivor",
        "subtype": "forum",
        "color": None,
    }


def test_get_discord_names_empty_returns_empty_list(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_discord_names()

    assert db.get_discord_names() == []
