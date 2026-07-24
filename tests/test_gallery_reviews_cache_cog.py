"""Contracts for the bot-pushed gallery and reviews queue cache."""

import config
from core import db


def _use_tmp_db(monkeypatch, tmp_path, name="gallery_reviews_cache.db"):
    """Point every database helper at a throwaway sqlite file."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


def test_queue_table_init_is_idempotent(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)

    db.init_gallery_queue()
    db.init_gallery_queue()
    db.init_reviews_queue()
    db.init_reviews_queue()

    with db._get_conn() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = ?",
                ("table",),
            ).fetchall()
        }
    assert {"gallery_queue", "reviews_queue"} <= tables


def test_gallery_queue_upsert_roundtrip_preserves_resolved_fields(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_gallery_queue()

    db.upsert_gallery_queue_row(
        101,
        "pending",
        "Poster original",
        "Caption one",
        "https://cdn.example/one.webp",
        "2026-07-23T10:00:00+00:00",
        "https://discord.com/channels/guild/photos/101",
    )
    db.upsert_gallery_queue_row(
        101,
        "published",
        "Poster changed",
        "Caption two",
        "https://cdn.example/two.webp",
        "2099-01-01T00:00:00+00:00",
        "https://discord.com/channels/guild/photos/101?fresh=1",
    )

    row = db.get_gallery_queue_row(101)
    assert row["state"] == "published"
    assert row["poster"] == "Poster original"
    assert row["posted_at"] == "2026-07-23T10:00:00+00:00"
    assert row["caption"] == "Caption two"
    assert row["thumb_url"] == "https://cdn.example/two.webp"
    assert row["message_link"].endswith("?fresh=1")
    assert row["synced_at"]


def test_reviews_queue_upsert_roundtrip_preserves_identity_fields(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_reviews_queue()

    db.upsert_reviews_queue_row(
        201,
        "pending",
        "Named reviewer",
        0,
        "First body",
        "2026-07-23T11:00:00+00:00",
        "https://discord.com/channels/guild/reviews/201",
    )
    db.upsert_reviews_queue_row(
        201,
        "published",
        "Changed identity",
        1,
        "Updated body",
        "2099-01-01T00:00:00+00:00",
        "https://discord.com/channels/guild/reviews/201?fresh=1",
    )

    row = db.get_reviews_queue_row(201)
    assert row["state"] == "published"
    assert row["author"] == "Named reviewer"
    assert row["is_anonymous"] == 0
    assert row["review_date"] == "2026-07-23T11:00:00+00:00"
    assert row["body"] == "Updated body"
    assert row["message_link"].endswith("?fresh=1")
    assert row["synced_at"]


def test_queue_row_filters_are_disjoint_and_deletes_are_scoped(
    monkeypatch, tmp_path
):
    _use_tmp_db(monkeypatch, tmp_path)
    db.init_gallery_queue()
    db.init_reviews_queue()

    for message_id, state in ((301, "pending"), (302, "published")):
        db.upsert_gallery_queue_row(
            message_id,
            state,
            f"Poster {message_id}",
            f"Caption {message_id}",
            f"https://cdn.example/{message_id}.webp",
            f"2026-07-23T12:0{message_id - 301}:00+00:00",
            f"https://discord.com/channels/guild/photos/{message_id}",
        )
        db.upsert_reviews_queue_row(
            message_id,
            state,
            f"Reviewer {message_id}",
            0,
            f"Review {message_id}",
            f"2026-07-23T13:0{message_id - 301}:00+00:00",
            f"https://discord.com/channels/guild/reviews/{message_id}",
        )

    gallery_pending = db.get_gallery_queue("pending")
    gallery_published = db.get_gallery_queue("published")
    reviews_pending = db.get_reviews_queue("pending")
    reviews_published = db.get_reviews_queue("published")

    assert {row["message_id"] for row in gallery_pending} == {301}
    assert {row["message_id"] for row in gallery_published} == {302}
    assert {row["message_id"] for row in reviews_pending} == {301}
    assert {row["message_id"] for row in reviews_published} == {302}

    db.delete_gallery_queue_row(301)
    db.delete_reviews_queue_row(301)

    assert db.get_gallery_queue_row(301) is None
    assert db.get_reviews_queue_row(301) is None
    assert db.get_gallery_queue_row(302) is not None
    assert db.get_reviews_queue_row(302) is not None
