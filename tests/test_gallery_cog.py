"""Unit tests for the pure helpers powering the gallery cog (05-03, BOT-01).

Covers the testable core: the image-attachment allow-list (D-13), the staff role
gate (D-01/D-02), the stateless numerics-only filename convention (D-14), the caption
trim/omit (BOT-06), and the ``on_message`` ✅ approve-control detection (D-03).

Discord objects are faked with ``types.SimpleNamespace``; the async listener is driven
with ``asyncio.run`` + ``AsyncMock`` — no pytest-asyncio dependency, matching the rest
of the suite.
"""

import asyncio
import re
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import config
from cogs import gallery
from cogs.gallery import GalleryCog

FILENAME_RE = re.compile(r"^\d{8}-\d+-\d+\.webp$")

STAFF_ROLE_ID = 111
OTHER_ROLE_ID = 222
PHOTO_CHANNEL = 999


# ── fakes ───────────────────────────────────────────────────────────────────────
def _attachment(content_type):
    return types.SimpleNamespace(content_type=content_type)


def _member(role_ids, is_bot=False):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids],
        bot=is_bot,
    )


def _message(author, attachments=(), channel_id=PHOTO_CHANNEL, content=""):
    return types.SimpleNamespace(
        author=author,
        attachments=list(attachments),
        channel=types.SimpleNamespace(id=channel_id),
        content=content,
        add_reaction=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def _gallery_config(monkeypatch):
    monkeypatch.setattr(config, "GALLERY_STAFF_ROLE_IDS", [STAFF_ROLE_ID], raising=False)
    monkeypatch.setattr(config, "PHOTO_CHANNEL_ID", PHOTO_CHANNEL, raising=False)


@pytest.fixture
def cog(monkeypatch):
    # Don't touch the sqlite DB during unit tests.
    monkeypatch.setattr(gallery.db, "init_gallery_state", lambda: None)
    return GalleryCog(bot=types.SimpleNamespace())


# ── _image_attachments (D-13 allow-list) ─────────────────────────────────────────
def test_image_attachments_keeps_only_static_image_types():
    msg = _message(_member([STAFF_ROLE_ID]), attachments=[
        _attachment("image/png"),
        _attachment("image/jpeg"),
        _attachment("image/webp"),
    ])
    assert len(gallery._image_attachments(msg)) == 3


def test_image_attachments_excludes_gif_video_and_missing_type():
    msg = _message(_member([STAFF_ROLE_ID]), attachments=[
        _attachment("image/gif"),
        _attachment("video/mp4"),
        _attachment("application/pdf"),
        _attachment(None),
    ])
    assert gallery._image_attachments(msg) == []


# ── _is_staff (D-01 role gate) ───────────────────────────────────────────────────
def test_is_staff_true_when_role_intersects():
    assert gallery._is_staff(_member([OTHER_ROLE_ID, STAFF_ROLE_ID])) is True


def test_is_staff_false_without_matching_role():
    assert gallery._is_staff(_member([OTHER_ROLE_ID])) is False
    assert gallery._is_staff(_member([])) is False


# ── _build_filename (D-14 stateless, numerics-only) ──────────────────────────────
def test_build_filename_matches_numeric_convention():
    created = datetime(2026, 7, 3, 14, 5, 9, tzinfo=timezone.utc)
    name = gallery._build_filename(1416329356426481717, created, 1)
    assert name == "20260703-1416329356426481717-1.webp"
    assert FILENAME_RE.match(name)


def test_build_filename_is_numeric_only_regardless_of_index():
    # The helper takes no message text — a filename can never carry caption chars.
    created = datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    for index in (1, 2, 10):
        name = gallery._build_filename(987654321, created, index)
        assert FILENAME_RE.match(name), name
        assert re.search(r"[^0-9\-.a-z]", name) is None  # no slash/unicode/space possible


def test_build_filename_normalizes_to_utc_date():
    # A non-UTC aware datetime is converted to UTC before formatting the date segment.
    created = datetime(2026, 1, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=5)))
    name = gallery._build_filename(42, created, 1)
    assert name.startswith("20251231-")  # 01:00 +05:00 == 20:00 UTC previous day


# ── _caption (BOT-06 trim + omit-when-empty) ─────────────────────────────────────
def test_caption_trims_text():
    assert gallery._caption("  Luna — full outfit  ") == "Luna — full outfit"


def test_caption_empty_for_whitespace_only():
    assert not gallery._caption("   \n\t ")
    assert not gallery._caption("")
    assert not gallery._caption(None)


# ── on_message detection (BOT-01/D-03) ───────────────────────────────────────────
def test_on_message_adds_check_for_staff_image_post(cog):
    msg = _message(_member([STAFF_ROLE_ID]), attachments=[_attachment("image/png")])
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_awaited_once_with("✅")


def test_on_message_ignores_community_image_post(cog):
    msg = _message(_member([OTHER_ROLE_ID]), attachments=[_attachment("image/png")])
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


def test_on_message_ignores_staff_text_only_post(cog):
    msg = _message(_member([STAFF_ROLE_ID]), attachments=[], content="hola equipo")
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


def test_on_message_ignores_other_channel(cog):
    msg = _message(_member([STAFF_ROLE_ID]), attachments=[_attachment("image/png")],
                   channel_id=PHOTO_CHANNEL + 1)
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


def test_on_message_ignores_bot_author(cog):
    msg = _message(_member([STAFF_ROLE_ID], is_bot=True), attachments=[_attachment("image/png")])
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


# ── 05-04 Task 1: 🌙 unpublish/dismiss + auto-unpublish-on-delete (BOT-05) ────────
def _reaction(emoji, me=False):
    return types.SimpleNamespace(emoji=emoji, me=me)


def _live_message(msg_id=555, reactions=None):
    return types.SimpleNamespace(
        id=msg_id,
        reactions=list(reactions) if reactions is not None else [],
        remove_reaction=AsyncMock(),
        add_reaction=AsyncMock(),
        reply=AsyncMock(),
    )


@pytest.fixture
def cog_with_user(monkeypatch):
    """A cog whose bot exposes ``.user`` (needed to remove the bot's own markers)."""
    monkeypatch.setattr(gallery.db, "init_gallery_state", lambda: None)
    bot = types.SimpleNamespace(user=types.SimpleNamespace(id=42))
    return GalleryCog(bot=bot)


# ── _is_published (derived from 🟢 marker / entries, D-05/D-14) ───────────────────
def test_is_published_true_with_green_marker():
    assert gallery._is_published(_live_message(reactions=[_reaction("🟢", me=True)])) is True


def test_is_published_false_without_marker():
    assert gallery._is_published(_live_message(reactions=[_reaction("✅", me=True)])) is False


def test_is_published_true_from_matching_entries():
    msg = _live_message(msg_id=1416329356426481717, reactions=[])
    entries = [{"file": "20260703-1416329356426481717-1.webp"}]
    assert gallery._is_published(msg, entries) is True


def test_is_published_false_for_prefix_collision_entries():
    # D-14: exact middle-segment match — a snowflake sharing a prefix must NOT collide.
    msg = _live_message(msg_id=987654321, reactions=[])
    entries = [{"file": "20260703-9876543210-1.webp"}]
    assert gallery._is_published(msg, entries) is False


# ── 🌙 unpublish / dismiss (D-06/D-07/D-09) ───────────────────────────────────────
def test_unpublish_published_removes_and_replies(cog_with_user, monkeypatch):
    remove = AsyncMock(return_value={"committed": True, "count": 2})
    monkeypatch.setattr(gallery.github_publish, "remove_message", remove)
    msg = _live_message(msg_id=555, reactions=[_reaction("🟢", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))
    remove.assert_awaited_once_with(555)
    msg.remove_reaction.assert_any_await("🟢", cog_with_user.bot.user)   # back to pending
    msg.reply.assert_awaited_once()
    assert msg.reply.await_args.kwargs.get("delete_after")               # mirrored auto-delete


def test_unpublish_pending_dismisses_without_commit(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "remove_message", remove)
    msg = _live_message(msg_id=556, reactions=[_reaction("✅", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))
    remove.assert_not_awaited()                                          # D-07: no commit
    msg.remove_reaction.assert_any_await("✅", cog_with_user.bot.user)   # clears the prompt
    msg.reply.assert_not_awaited()


# ── auto-unpublish on message delete (D-10) ───────────────────────────────────────
def test_message_delete_in_photo_channel_unpublishes(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "remove_message", remove)
    payload = types.SimpleNamespace(channel_id=PHOTO_CHANNEL, message_id=777)
    asyncio.run(cog_with_user.on_raw_message_delete(payload))
    remove.assert_awaited_once_with(777)


def test_message_delete_other_channel_noop(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "remove_message", remove)
    payload = types.SimpleNamespace(channel_id=PHOTO_CHANNEL + 1, message_id=778)
    asyncio.run(cog_with_user.on_raw_message_delete(payload))
    remove.assert_not_awaited()


# ── 🌙 role gate + dispatch (D-08) ────────────────────────────────────────────────
def test_moon_reaction_non_staff_ignored(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "remove_message", remove)
    cog_with_user._unpublish = AsyncMock()
    payload = types.SimpleNamespace(
        emoji="🌙", member=_member([OTHER_ROLE_ID]),
        channel_id=PHOTO_CHANNEL, message_id=779,
    )
    asyncio.run(cog_with_user.on_raw_reaction_add(payload))
    cog_with_user._unpublish.assert_not_awaited()
    remove.assert_not_awaited()


def test_moon_reaction_staff_dispatches_unpublish(cog_with_user, monkeypatch):
    fake_msg = _live_message(msg_id=780, reactions=[_reaction("🟢", me=True)])
    channel = types.SimpleNamespace(fetch_message=AsyncMock(return_value=fake_msg))
    cog_with_user.bot.get_channel = lambda cid: channel
    cog_with_user._unpublish = AsyncMock()
    payload = types.SimpleNamespace(
        emoji="🌙", member=_member([STAFF_ROLE_ID]),
        channel_id=PHOTO_CHANNEL, message_id=780,
    )
    asyncio.run(cog_with_user.on_raw_reaction_add(payload))
    cog_with_user._unpublish.assert_awaited_once_with(fake_msg)
