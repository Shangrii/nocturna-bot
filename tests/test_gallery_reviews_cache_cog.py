"""Contracts for the bot-pushed gallery and reviews queue cache."""

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import config
from core import db


def _use_tmp_db(monkeypatch, tmp_path, name="gallery_reviews_cache.db"):
    """Point every database helper at a throwaway sqlite file."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / name), raising=False)


class _FakeChannel:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.history_calls = []

    def history(self, *, limit, oldest_first):
        self.history_calls.append(
            {"limit": limit, "oldest_first": oldest_first}
        )

        async def _iterate():
            for message in self.messages:
                yield message

        return _iterate()


def _message(
    message_id,
    *,
    display_name,
    bot=False,
    content="",
    attachments=(),
    reactions=(),
    embeds=(),
):
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(display_name=display_name, bot=bot),
        content=content,
        attachments=list(attachments),
        reactions=list(reactions),
        embeds=list(embeds),
        created_at=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
    )


def _image(url):
    return SimpleNamespace(content_type="image/webp", url=url)


def _published_marker():
    return SimpleNamespace(emoji="🟢", me=True)


def _review_embed(*, text, author_name=None):
    return SimpleNamespace(
        footer=SimpleNamespace(text="reseña"),
        description=text,
        author=SimpleNamespace(name=author_name),
    )


def _build_cache_cog(
    monkeypatch,
    tmp_path,
    *,
    gallery_messages=(),
    review_messages=(),
    gallery_entries=(),
    review_entries=(),
):
    _use_tmp_db(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "GUILD_ID", 111, raising=False)
    monkeypatch.setattr(config, "PHOTO_CHANNEL_ID", 222, raising=False)
    monkeypatch.setattr(config, "REVIEWS_CHANNEL_ID", 333, raising=False)
    monkeypatch.setattr(config, "WEBSITE_REPO", "owner/site", raising=False)
    monkeypatch.setattr(config, "WEBSITE_BRANCH", "main", raising=False)
    monkeypatch.setattr(
        config, "WEBSITE_REVIEWS_JSON", "src/data/reviews.json", raising=False
    )

    cache_module = importlib.import_module("cogs.gallery_reviews_cache")
    monkeypatch.setattr(
        cache_module.tasks.Loop,
        "start",
        lambda self, *args, **kwargs: None,
    )
    monkeypatch.setattr(
        cache_module.github_publish,
        "_fetch_gallery",
        lambda repo, branch: list(gallery_entries),
    )
    monkeypatch.setattr(
        cache_module.github_publish,
        "_fetch_json",
        lambda repo, branch, path: list(review_entries),
    )

    gallery_channel = _FakeChannel(gallery_messages)
    reviews_channel = _FakeChannel(review_messages)
    channels = {
        config.PHOTO_CHANNEL_ID: gallery_channel,
        config.REVIEWS_CHANNEL_ID: reviews_channel,
    }

    async def fetch_channel(channel_id):
        return channels[channel_id]

    bot = SimpleNamespace(
        get_channel=lambda channel_id: channels.get(channel_id),
        fetch_channel=fetch_channel,
    )
    cog = cache_module.GalleryReviewsCacheCog(bot)
    return cache_module, cog, gallery_channel, reviews_channel


@pytest.fixture
def anyio_backend():
    return "asyncio"


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


@pytest.mark.anyio
async def test_push_classifies_gallery_and_uses_live_poster(monkeypatch, tmp_path):
    pending = _message(
        401,
        display_name="Live Poster",
        content="Pending caption",
        attachments=[_image("https://cdn.example/pending.webp")],
    )
    published = _message(
        402,
        display_name="Published Poster",
        content="Published caption",
        attachments=[_image("https://cdn.example/published.webp")],
        reactions=[_published_marker()],
    )
    cache_module, cog, gallery_channel, _ = _build_cache_cog(
        monkeypatch,
        tmp_path,
        gallery_messages=[pending, published],
    )

    await cache_module.GalleryReviewsCacheCog._push.coro(cog)

    pending_row = db.get_gallery_queue_row(401)
    published_row = db.get_gallery_queue_row(402)
    assert pending_row["state"] == "pending"
    assert pending_row["poster"] == "Live Poster"
    assert pending_row["caption"] == "Pending caption"
    assert pending_row["thumb_url"] == "https://cdn.example/pending.webp"
    assert pending_row["message_link"] == (
        "https://discord.com/channels/111/222/401"
    )
    assert published_row["state"] == "published"
    assert gallery_channel.history_calls == [
        {"limit": 300, "oldest_first": False}
    ]


@pytest.mark.anyio
async def test_push_never_stores_anonymous_submitter_display_name(
    monkeypatch, tmp_path
):
    anonymous = _message(
        501,
        display_name="Secret Submitter",
        bot=True,
        embeds=[_review_embed(text="Private identity, public review")],
    )
    cache_module, cog, _, _ = _build_cache_cog(
        monkeypatch,
        tmp_path,
        review_messages=[anonymous],
    )

    await cache_module.GalleryReviewsCacheCog._push.coro(cog)

    row = db.get_reviews_queue_row(501)
    assert row["state"] == "pending"
    assert row["is_anonymous"] == 1
    assert row["author"] is None
    assert row["author"] != "Secret Submitter"
    assert row["body"] == "Private identity, public review"


@pytest.mark.anyio
async def test_push_excludes_non_review_bot_messages(monkeypatch, tmp_path):
    bot_reply = _message(
        601,
        display_name="Nocturna Bot",
        bot=True,
        content="⚠️ No pude publicar la reseña",
    )
    cache_module, cog, _, _ = _build_cache_cog(
        monkeypatch,
        tmp_path,
        review_messages=[bot_reply],
    )

    await cache_module.GalleryReviewsCacheCog._push.coro(cog)

    assert db.get_reviews_queue("pending") == []
    assert db.get_reviews_queue("published") == []


@pytest.mark.anyio
async def test_push_prunes_only_rows_absent_from_scan_and_published_entries(
    monkeypatch, tmp_path
):
    cache_module, cog, _, _ = _build_cache_cog(
        monkeypatch,
        tmp_path,
        gallery_entries=[{"file": "20260723-702-1.webp"}],
        review_entries=[{"id": "704"}],
    )
    db.upsert_gallery_queue_row(
        701,
        "pending",
        "Gone",
        "",
        "https://cdn.example/gone.webp",
        "2026-07-23T12:00:00+00:00",
        "https://discord.com/channels/111/222/701",
    )
    db.upsert_gallery_queue_row(
        702,
        "published",
        "Still published",
        "",
        "https://cdn.example/live.webp",
        "2026-07-23T12:00:00+00:00",
        "https://discord.com/channels/111/222/702",
    )
    db.upsert_reviews_queue_row(
        703,
        "pending",
        "Gone",
        0,
        "Gone review",
        "2026-07-23T12:00:00+00:00",
        "https://discord.com/channels/111/333/703",
    )
    db.upsert_reviews_queue_row(
        704,
        "published",
        None,
        1,
        "Still published",
        "2026-07-23T12:00:00+00:00",
        "https://discord.com/channels/111/333/704",
    )

    await cache_module.GalleryReviewsCacheCog._push.coro(cog)

    assert db.get_gallery_queue_row(701) is None
    assert db.get_reviews_queue_row(703) is None
    assert db.get_gallery_queue_row(702) is not None
    assert db.get_reviews_queue_row(704) is not None
