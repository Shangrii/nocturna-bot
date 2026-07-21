"""Unit tests for the pure helpers + listeners powering the reviews cog (07-03).

Covers the testable core: the staff role gate (T-07-03), the author/text resolution seam
(``_review_author_and_text``), the id-keyed published-state (``_is_published``, including the
prefix non-collision case), the ``on_message`` ✅ approve-control detection (REV-02), the
entry dict shape built by ``_publish``, the 🌙 unpublish/dismiss + delete-unpublish flows,
and the startup ``_reconcile`` / orphan-pass dispatch.

Discord objects are faked with ``types.SimpleNamespace``; async listeners are driven with
``asyncio.run`` + ``AsyncMock`` — no pytest-asyncio dependency, matching the rest of the suite.
"""

import asyncio
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import discord
import pytest

import config
from cogs import reviews
from cogs.reviews import ReviewsCog
from core import db
from core import settings

STAFF_ROLE_ID = 111
OTHER_ROLE_ID = 222
REVIEWS_CHANNEL = 999


# ── fakes ───────────────────────────────────────────────────────────────────────
def _member(role_ids, is_bot=False):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids],
        bot=is_bot,
    )


def _author(display_name="Cliente", is_bot=False, uid=7):
    return types.SimpleNamespace(display_name=display_name, bot=is_bot, id=uid)


def _message(author, channel_id=REVIEWS_CHANNEL, content=""):
    return types.SimpleNamespace(
        author=author,
        channel=types.SimpleNamespace(id=channel_id),
        content=content,
        add_reaction=AsyncMock(),
    )


def _reaction(emoji, me=False):
    return types.SimpleNamespace(emoji=emoji, me=me)


def _live_message(msg_id=555, reactions=None, author_name="Cliente",
                  content="reseña genial", created=None):
    return types.SimpleNamespace(
        id=msg_id,
        reactions=list(reactions) if reactions is not None else [],
        author=_author(display_name=author_name),
        content=content,
        created_at=created or datetime(2026, 7, 9, 14, 5, 9, tzinfo=timezone.utc),
        remove_reaction=AsyncMock(),
        add_reaction=AsyncMock(),
        reply=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def _reviews_config(monkeypatch):
    monkeypatch.setattr(config, "REVIEWS_STAFF_ROLE_IDS", [STAFF_ROLE_ID], raising=False)
    monkeypatch.setattr(config, "REVIEWS_CHANNEL_ID", REVIEWS_CHANNEL, raising=False)


@pytest.fixture
def cog():
    return ReviewsCog(bot=types.SimpleNamespace())


@pytest.fixture
def cog_with_user():
    """A cog whose bot exposes ``.user`` (needed to remove the bot's own markers)."""
    bot = types.SimpleNamespace(user=types.SimpleNamespace(id=42))
    return ReviewsCog(bot=bot)


# ── _is_staff (T-07-03 role gate) ─────────────────────────────────────────────────
def test_is_staff_true_when_role_intersects():
    assert reviews._is_staff(_member([OTHER_ROLE_ID, STAFF_ROLE_ID])) is True


def test_is_staff_false_without_matching_role():
    assert reviews._is_staff(_member([OTHER_ROLE_ID])) is False
    assert reviews._is_staff(_member([])) is False


def test_is_staff_false_for_bot_without_role():
    assert reviews._is_staff(_member([], is_bot=True)) is False


# ── _review_author_and_text (the extension seam) ─────────────────────────────────
def test_review_author_and_text_plain_message():
    msg = _message(_author(display_name="Luna"), content="  trabajo increíble  ")
    author, text = reviews._review_author_and_text(msg)
    assert author == "Luna"
    assert text == "trabajo increíble"          # trimmed


def test_review_author_and_text_empty_content_returns_none():
    for content in ("", "   \n\t "):
        author, text = reviews._review_author_and_text(_message(_author(), content=content))
        assert author is None
        assert text == ""


# ── _is_published (id-keyed derived state) ────────────────────────────────────────
def test_is_published_true_with_green_marker():
    assert reviews._is_published(_live_message(reactions=[_reaction("🟢", me=True)])) is True


def test_is_published_false_without_marker():
    assert reviews._is_published(_live_message(reactions=[_reaction("✅", me=True)])) is False


def test_is_published_true_from_matching_entry_id():
    msg = _live_message(msg_id=1453534905706221600, reactions=[])
    entries = [{"id": "1453534905706221600", "author": "Luna", "text": "x", "date": "d"}]
    assert reviews._is_published(msg, entries) is True


def test_is_published_false_for_prefix_collision_entries():
    # Exact string id match — a snowflake sharing a prefix must NOT collide.
    msg = _live_message(msg_id=987654321, reactions=[])
    entries = [{"id": "9876543210", "author": "Luna", "text": "x", "date": "d"}]
    assert reviews._is_published(msg, entries) is False


# ── on_message detection (REV-02) ─────────────────────────────────────────────────
def test_on_message_adds_check_for_client_text_review(cog):
    msg = _message(_author(is_bot=False), content="me encantó el resultado")
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_awaited_once_with("✅")


def test_on_message_ignores_empty_text(cog):
    msg = _message(_author(is_bot=False), content="   ")
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


def test_on_message_ignores_other_channel(cog):
    msg = _message(_author(is_bot=False), content="reseña", channel_id=REVIEWS_CHANNEL + 1)
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


def test_on_message_ignores_bot_author(cog):
    msg = _message(_author(is_bot=True), content="reseña")
    asyncio.run(cog.on_message(msg))
    msg.add_reaction.assert_not_awaited()


# ── _publish entry shape + markers (REV-03) ───────────────────────────────────────
def test_publish_builds_entry_dict_and_adds_markers(cog_with_user, monkeypatch):
    publish = AsyncMock(return_value={"committed": True, "count": 1})
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _live_message(msg_id=900, author_name="Luna", content="  gran trabajo  ",
                        created=datetime(2026, 7, 9, 14, 5, 9, tzinfo=timezone.utc))
    asyncio.run(cog_with_user._publish(msg))
    publish.assert_awaited_once()
    entry = publish.await_args.args[0]
    assert entry == {
        "id": "900",
        "author": "Luna",
        "text": "gran trabajo",                 # trimmed
        "date": "2026-07-09T14:05:09.000Z",     # millisecond-Z shape
    }
    msg.add_reaction.assert_any_await("🟢")
    msg.add_reaction.assert_any_await("🌙")
    assert msg.reply.await_args.kwargs.get("delete_after")   # auto-deleting confirmation


def test_publish_idempotent_when_already_green(cog_with_user, monkeypatch):
    publish = AsyncMock()
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _live_message(msg_id=901, reactions=[_reaction("🟢", me=True)])
    asyncio.run(cog_with_user._publish(msg))
    publish.assert_not_awaited()                 # already published -> skipped


def test_publish_failure_surfaces_warning_and_no_green(cog_with_user, monkeypatch):
    publish = AsyncMock(side_effect=reviews.github_publish.GitHubPublishError("boom"))
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _live_message(msg_id=902, reactions=[])
    asyncio.run(cog_with_user._publish(msg))     # must not raise
    msg.add_reaction.assert_any_await("⚠️")      # retry to-do surfaced
    # never a 🟢 on the failure path
    assert not any(call.args == ("🟢",) for call in msg.add_reaction.await_args_list)
    assert msg.reply.await_args.kwargs.get("delete_after") is None   # persistent reply


# ── WR-04: non-typed failures still drive the ⚠️ retry UX (last-resort backstop) ──
def test_publish_unexpected_error_still_surfaces_warning(cog_with_user, monkeypatch):
    publish = AsyncMock(side_effect=TypeError("malformed entry"))
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _live_message(msg_id=903, reactions=[])
    asyncio.run(cog_with_user._publish(msg))     # must not raise
    msg.add_reaction.assert_any_await("⚠️")      # retry to-do surfaced
    assert not any(call.args == ("🟢",) for call in msg.add_reaction.await_args_list)


def test_unpublish_unexpected_error_still_surfaces_warning(cog_with_user, monkeypatch):
    remove = AsyncMock(side_effect=TypeError("malformed entry"))
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    msg = _live_message(msg_id=904, reactions=[_reaction("🟢", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))   # must not raise
    msg.add_reaction.assert_any_await("⚠️")
    msg.remove_reaction.assert_not_awaited()     # 🟢 kept — review may still be live


# ── WR-01: non-review bot messages are never publishable, even by a staff ✅ ──────
def test_publish_skips_non_review_bot_message(cog_with_user, monkeypatch):
    # The cog's own persistent ⚠️ failure reply is a bot message with text content — a
    # mis-tapped staff ✅ on it must NOT publish the error text to the website.
    publish = AsyncMock()
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _live_message(msg_id=930, content="⚠️ No pude publicar la reseña: GitHub falló…")
    msg.author = _author(display_name="NocturnaBot", is_bot=True)
    asyncio.run(cog_with_user._publish(msg))
    publish.assert_not_awaited()                 # never committed
    msg.add_reaction.assert_not_awaited()        # no 🟢/🌙 markers either


def test_unpublish_skips_non_review_bot_message(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    msg = _live_message(msg_id=931, content="mensaje de otro bot",
                        reactions=[_reaction("✅", me=True)])
    msg.author = _author(display_name="ForeignBot", is_bot=True)
    asyncio.run(cog_with_user._unpublish(msg))
    remove.assert_not_awaited()
    msg.remove_reaction.assert_not_awaited()     # left completely untouched


# ── 🌙 unpublish / dismiss ────────────────────────────────────────────────────────
def test_unpublish_published_removes_and_replies(cog_with_user, monkeypatch):
    remove = AsyncMock(return_value={"committed": True, "count": 1})
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    msg = _live_message(msg_id=555, reactions=[_reaction("🟢", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))
    remove.assert_awaited_once_with(555)
    msg.remove_reaction.assert_any_await("🟢", cog_with_user.bot.user)   # back to pending
    msg.reply.assert_awaited_once()
    assert msg.reply.await_args.kwargs.get("delete_after")               # mirrored auto-delete


def test_unpublish_pending_dismisses_and_heals_lost_marker(cog_with_user, monkeypatch):
    # WR-02: the dismiss path still calls the transport defensively — remove_review is a
    # no-op (no commit) for a truly-pending message, but heals a published review whose
    # 🟢 marker was lost, instead of leaving it live forever while looking dismissed.
    remove = AsyncMock(return_value={"committed": False, "commit_sha": None, "count": 0})
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    msg = _live_message(msg_id=556, reactions=[_reaction("✅", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))
    remove.assert_awaited_once_with(556)                                 # defensive removal
    msg.remove_reaction.assert_any_await("✅", cog_with_user.bot.user)   # clears the prompt
    msg.reply.assert_not_awaited()


def test_unpublish_pending_defensive_removal_failure_is_tolerated(cog_with_user, monkeypatch):
    # A failed defensive removal must never abort the dismiss (logged, not surfaced).
    remove = AsyncMock(side_effect=reviews.github_publish.GitHubPublishError("boom"))
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    msg = _live_message(msg_id=558, reactions=[_reaction("✅", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))   # must not raise
    msg.remove_reaction.assert_any_await("✅", cog_with_user.bot.user)   # dismiss still done
    msg.reply.assert_not_awaited()


def test_unpublish_failure_keeps_green_and_surfaces(cog_with_user, monkeypatch):
    remove = AsyncMock(side_effect=reviews.github_publish.GitHubPublishError("boom"))
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    msg = _live_message(msg_id=557, reactions=[_reaction("🟢", me=True)])
    asyncio.run(cog_with_user._unpublish(msg))   # must not raise
    msg.add_reaction.assert_any_await("⚠️")      # surfaced
    msg.remove_reaction.assert_not_awaited()     # 🟢 kept — review still live


# ── auto-unpublish on message delete ──────────────────────────────────────────────
def test_message_delete_in_reviews_channel_unpublishes(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    payload = types.SimpleNamespace(channel_id=REVIEWS_CHANNEL, message_id=777)
    asyncio.run(cog_with_user.on_raw_message_delete(payload))
    remove.assert_awaited_once_with(777)


def test_message_delete_other_channel_noop(cog_with_user, monkeypatch):
    remove = AsyncMock()
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    payload = types.SimpleNamespace(channel_id=REVIEWS_CHANNEL + 1, message_id=778)
    asyncio.run(cog_with_user.on_raw_message_delete(payload))
    remove.assert_not_awaited()


# ── ✅/🌙 raw reaction gate + dispatch (T-07-03) ──────────────────────────────────
def test_reaction_non_staff_ignored(cog_with_user, monkeypatch):
    cog_with_user._publish = AsyncMock()
    cog_with_user._unpublish = AsyncMock()
    payload = types.SimpleNamespace(
        emoji="✅", member=_member([OTHER_ROLE_ID]),
        channel_id=REVIEWS_CHANNEL, message_id=779,
    )
    asyncio.run(cog_with_user.on_raw_reaction_add(payload))
    cog_with_user._publish.assert_not_awaited()
    cog_with_user._unpublish.assert_not_awaited()


def test_reaction_bot_member_ignored(cog_with_user):
    cog_with_user._publish = AsyncMock()
    payload = types.SimpleNamespace(
        emoji="✅", member=_member([STAFF_ROLE_ID], is_bot=True),
        channel_id=REVIEWS_CHANNEL, message_id=781,
    )
    asyncio.run(cog_with_user.on_raw_reaction_add(payload))
    cog_with_user._publish.assert_not_awaited()


def test_check_reaction_staff_dispatches_publish(cog_with_user):
    fake_msg = _live_message(msg_id=780, reactions=[])
    channel = types.SimpleNamespace(fetch_message=AsyncMock(return_value=fake_msg))
    cog_with_user.bot.get_channel = lambda cid: channel
    cog_with_user._publish = AsyncMock()
    payload = types.SimpleNamespace(
        emoji="✅", member=_member([STAFF_ROLE_ID]),
        channel_id=REVIEWS_CHANNEL, message_id=780,
    )
    asyncio.run(cog_with_user.on_raw_reaction_add(payload))
    cog_with_user._publish.assert_awaited_once_with(fake_msg)


def test_moon_reaction_staff_dispatches_unpublish(cog_with_user):
    fake_msg = _live_message(msg_id=782, reactions=[_reaction("🟢", me=True)])
    channel = types.SimpleNamespace(fetch_message=AsyncMock(return_value=fake_msg))
    cog_with_user.bot.get_channel = lambda cid: channel
    cog_with_user._unpublish = AsyncMock()
    payload = types.SimpleNamespace(
        emoji="🌙", member=_member([STAFF_ROLE_ID]),
        channel_id=REVIEWS_CHANNEL, message_id=782,
    )
    asyncio.run(cog_with_user.on_raw_reaction_add(payload))
    cog_with_user._unpublish.assert_awaited_once_with(fake_msg)


# ── _reconcile dispatch table ─────────────────────────────────────────────────────
def _user(uid, is_bot=False):
    return types.SimpleNamespace(id=uid, bot=is_bot)


def _full_reaction(emoji, me=False, users=()):
    """A history-message reaction whose ``users()`` is an async iterator of reactors."""
    async def _aiter():
        for u in users:
            yield u
    return types.SimpleNamespace(emoji=emoji, me=me, users=_aiter)


def _not_found():
    return discord.NotFound(
        types.SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")


def _history_message(msg_id=600, content="buena reseña", is_bot=False,
                     reactions=None, members=None):
    guild = types.SimpleNamespace(
        get_member=lambda uid: (members or {}).get(uid),
        fetch_member=AsyncMock(side_effect=_not_found()),
    )
    return types.SimpleNamespace(
        id=msg_id,
        author=_author(is_bot=is_bot),
        content=content,
        reactions=list(reactions) if reactions else [],
        guild=guild,
        add_reaction=AsyncMock(),
    )


def test_reconcile_client_review_without_prompt_adds_check(cog_with_user):
    msg = _history_message(reactions=[])                 # posted while down, no ✅ prompt
    asyncio.run(cog_with_user._reconcile(msg))
    msg.add_reaction.assert_awaited_once_with("✅")


def test_reconcile_bot_message_is_noop(cog_with_user):
    msg = _history_message(is_bot=True, reactions=[])
    asyncio.run(cog_with_user._reconcile(msg))
    msg.add_reaction.assert_not_awaited()


def test_reconcile_empty_text_is_noop(cog_with_user):
    msg = _history_message(content="   ", reactions=[])
    asyncio.run(cog_with_user._reconcile(msg))
    msg.add_reaction.assert_not_awaited()


def test_reconcile_staff_check_unpublished_triggers_publish(cog_with_user):
    cog_with_user._publish = AsyncMock()
    msg = _history_message(
        reactions=[_full_reaction("✅", me=True, users=[_user(42, is_bot=True), _user(7)])],
        members={7: _member([STAFF_ROLE_ID])},
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._publish.assert_awaited_once_with(msg)


def test_reconcile_staff_moon_triggers_unpublish(cog_with_user):
    cog_with_user._unpublish = AsyncMock()
    msg = _history_message(
        reactions=[_full_reaction("🌙", users=[_user(8)])],
        members={8: _member([STAFF_ROLE_ID])},
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._unpublish.assert_awaited_once_with(msg)


def test_reconcile_published_message_is_left_alone(cog_with_user):
    cog_with_user._publish = AsyncMock()                 # 🟢 already present -> no republish
    msg = _history_message(
        reactions=[_full_reaction("🟢", me=True),
                   _full_reaction("✅", me=True, users=[_user(5)])],
        members={5: _member([STAFF_ROLE_ID])},
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._publish.assert_not_awaited()
    msg.add_reaction.assert_not_awaited()


def test_reconcile_non_staff_check_does_not_publish(cog_with_user):
    # The staff gate holds during backfill too: a NON-staff ✅ must not trigger a publish.
    cog_with_user._publish = AsyncMock()
    msg = _history_message(
        reactions=[_full_reaction("✅", me=True, users=[_user(3)])],
        members={3: _member([OTHER_ROLE_ID])},           # reactor is not staff
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._publish.assert_not_awaited()


def test_reaction_by_staff_falls_back_to_fetch_member(cog_with_user):
    # A staff ✅ from a reactor missing from the cache must still be honored (cold cache).
    cog_with_user._publish = AsyncMock()
    msg = _history_message(
        reactions=[_full_reaction("✅", me=True, users=[_user(7)])], members={})
    msg.guild.fetch_member = AsyncMock(return_value=_member([STAFF_ROLE_ID]))
    asyncio.run(cog_with_user._reconcile(msg))
    msg.guild.fetch_member.assert_awaited_once_with(7)
    cog_with_user._publish.assert_awaited_once_with(msg)


def test_reaction_by_staff_fetch_member_not_found_fails_closed(cog_with_user):
    # A reactor who left the guild (fetch_member -> NotFound) can never publish.
    cog_with_user._publish = AsyncMock()
    msg = _history_message(
        reactions=[_full_reaction("✅", me=True, users=[_user(9)])], members={})
    asyncio.run(cog_with_user._reconcile(msg))           # default fake fetch -> NotFound
    cog_with_user._publish.assert_not_awaited()


# ── backfill: empty channel + orphan reconcile ────────────────────────────────────
def _empty_history(**_kw):
    async def _gen():
        for _ in ():                                     # empty async generator
            yield  # pragma: no cover
    return _gen()


def test_backfill_empty_channel_is_tolerated(monkeypatch):
    bot = types.SimpleNamespace(user=types.SimpleNamespace(id=42))
    cog = ReviewsCog(bot=bot)
    bot.get_channel = lambda cid: types.SimpleNamespace(
        history=lambda **kw: _empty_history(**kw),
        fetch_message=AsyncMock())
    monkeypatch.setattr(reviews.github_publish, "_fetch_json", lambda *a, **k: [])
    asyncio.run(cog._backfill())                         # empty channel -> no error, no work


def test_backfill_rescans_full_history_replaying_missed_approvals(monkeypatch):
    # WR-03: approvals are REACTION events on EXISTING messages — a staff ✅ added while
    # the bot was down, on a message already scanned by an earlier startup, must still be
    # replayed. The backfill therefore scans the FULL history every time (no cursor).
    bot = types.SimpleNamespace(user=types.SimpleNamespace(id=42))
    cog = ReviewsCog(bot=bot)
    msg = _history_message(msg_id=650, reactions=[],
                           members={7: _member([STAFF_ROLE_ID])})
    history_kwargs = []

    def history(**kw):
        history_kwargs.append(kw)

        async def _gen():
            yield msg
        return _gen()

    bot.get_channel = lambda cid: types.SimpleNamespace(
        history=history, fetch_message=AsyncMock(return_value=msg))
    monkeypatch.setattr(reviews.github_publish, "_fetch_json", lambda *a, **k: [])
    cog._publish = AsyncMock()

    asyncio.run(cog._backfill())                          # first startup: pending, no ✅ yet
    msg.add_reaction.assert_awaited_once_with("✅")
    cog._publish.assert_not_awaited()

    # …staff ✅ arrives while the bot is down…
    msg.reactions = [_full_reaction("✅", me=True, users=[_user(7)])]

    asyncio.run(cog._backfill())                          # next startup: approval replayed
    cog._publish.assert_awaited_once_with(msg)
    assert all("after" not in kw for kw in history_kwargs)   # never cursor-limited


def _orphan_cog(monkeypatch, entries, fetch_message):
    bot = types.SimpleNamespace(user=types.SimpleNamespace(id=42))
    cog = ReviewsCog(bot=bot)
    channel = types.SimpleNamespace(history=lambda **kw: _empty_history(**kw),
                                    fetch_message=fetch_message)
    bot.get_channel = lambda cid: channel
    monkeypatch.setattr(reviews.github_publish, "_fetch_json", lambda *a, **k: entries)
    remove = AsyncMock(return_value={"committed": True, "count": 1})
    monkeypatch.setattr(reviews.github_publish, "remove_review", remove)
    return cog, remove


def test_backfill_removes_orphan_entry_when_message_deleted(monkeypatch):
    entries = [{"id": "1453534905706221600", "author": "Luna", "text": "x", "date": "d"}]
    fetch_message = AsyncMock(side_effect=_not_found())
    cog, remove = _orphan_cog(monkeypatch, entries, fetch_message)
    asyncio.run(cog._backfill())
    remove.assert_awaited_once_with(1453534905706221600)          # orphan healed
    fetch_message.assert_awaited_once_with(1453534905706221600)


def test_backfill_skips_malformed_entry_id(monkeypatch):
    entries = [{"id": None, "author": "x", "text": "y", "date": "d"},
               {"id": "not-a-number", "author": "x", "text": "y", "date": "d"}]
    fetch_message = AsyncMock(side_effect=_not_found())
    cog, remove = _orphan_cog(monkeypatch, entries, fetch_message)
    asyncio.run(cog._backfill())
    fetch_message.assert_not_awaited()                            # malformed ids never probed
    remove.assert_not_awaited()


def test_backfill_skips_non_dict_entries_without_aborting(monkeypatch):
    # WR-04: a truthy non-dict entry (hand-edited reviews.json) must not abort the whole
    # orphan pass with an AttributeError — later valid orphans are still healed.
    entries = ["abc", {"id": "1453534905706221600", "author": "L", "text": "x", "date": "d"}]
    fetch_message = AsyncMock(side_effect=_not_found())
    cog, remove = _orphan_cog(monkeypatch, entries, fetch_message)
    asyncio.run(cog._backfill())
    fetch_message.assert_awaited_once_with(1453534905706221600)   # valid entry still probed
    remove.assert_awaited_once_with(1453534905706221600)          # …and healed


def test_backfill_live_entry_message_left_alone(monkeypatch):
    entries = [{"id": "556", "author": "x", "text": "y", "date": "d"}]
    fetch_message = AsyncMock(return_value=types.SimpleNamespace(id=556))
    cog, remove = _orphan_cog(monkeypatch, entries, fetch_message)
    asyncio.run(cog._backfill())
    remove.assert_not_awaited()                                   # message exists -> entry stays


def test_backfill_transient_error_is_never_treated_as_deletion(monkeypatch):
    # Rate limit / permission / network failures mean "unknown", NOT "deleted" — a transient
    # outage must never mass-remove the live reviews (T-07-06).
    for boom in (discord.HTTPException(
                     types.SimpleNamespace(status=503, reason="unavailable"), "err"),
                 RuntimeError("network down")):
        entries = [{"id": "557", "author": "x", "text": "y", "date": "d"}]
        fetch_message = AsyncMock(side_effect=boom)
        cog, remove = _orphan_cog(monkeypatch, entries, fetch_message)
        asyncio.run(cog._backfill())
        remove.assert_not_awaited()                               # left alone, logged as unknown


# ── 07-04: guided collection flow (modal + persistent view + bot review embeds) ───
def _embed(description="reseña top", author_name=None,
           footer_text=reviews.REVIEW_EMBED_FOOTER):
    """A faked review embed: footer marks it, author is None ⇒ anonymous."""
    return types.SimpleNamespace(
        description=description,
        title=None,
        author=types.SimpleNamespace(name=author_name),
        footer=types.SimpleNamespace(text=footer_text),
    )


def _bot_review_message(msg_id=700, description="reseña top", author_name=None,
                        footer_text=reviews.REVIEW_EMBED_FOOTER, reactions=None,
                        created=None, members=None):
    """The cog's OWN posted review embed (a bot message carrying a marked embed)."""
    guild = types.SimpleNamespace(
        get_member=lambda uid: (members or {}).get(uid),
        fetch_member=AsyncMock(side_effect=_not_found()),
    )
    return types.SimpleNamespace(
        id=msg_id,
        author=_author(is_bot=True),
        content="",
        embeds=[_embed(description, author_name, footer_text)],
        reactions=list(reactions) if reactions else [],
        created_at=created or datetime(2026, 7, 9, 14, 5, 9, tzinfo=timezone.utc),
        guild=guild,
        add_reaction=AsyncMock(),
        remove_reaction=AsyncMock(),
        reply=AsyncMock(),
    )


# ── _is_own_review_embed marker recognition ───────────────────────────────────────
def test_is_own_review_embed_requires_bot_and_marker_footer():
    assert reviews._is_own_review_embed(_bot_review_message()) is True
    # a bot message whose embed lacks the marker footer is NOT a cog review embed
    assert reviews._is_own_review_embed(
        _bot_review_message(footer_text="otro pie")) is False
    # a non-bot message (even with a marked embed) is never a bot review embed
    plain = _live_message(msg_id=1)
    plain.embeds = [_embed()]
    assert reviews._is_own_review_embed(plain) is False


# ── seam extension: author/text resolved from the bot's own review embed ───────────
def test_seam_bot_review_embed_with_author_returns_named():
    msg = _bot_review_message(description="excelente servicio", author_name="Luna")
    author, text = reviews._review_author_and_text(msg)
    assert author == "Luna"
    assert text == "excelente servicio"


def test_seam_bot_review_embed_without_author_is_anonymous():
    msg = _bot_review_message(description="todo perfecto", author_name=None)
    author, text = reviews._review_author_and_text(msg)
    assert author is None                              # anonymity contract (T-07-02)
    assert text == "todo perfecto"


# ── full publish: anonymous ⇒ author null, named ⇒ display name ────────────────────
def test_anonymous_bot_review_publishes_with_author_none(cog_with_user, monkeypatch):
    publish = AsyncMock(return_value={"committed": True, "count": 1})
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _bot_review_message(msg_id=910, description="anónima pero real", author_name=None)
    asyncio.run(cog_with_user._publish(msg))
    entry = publish.await_args.args[0]
    assert entry["author"] is None                     # null author flows into reviews.json
    assert entry["text"] == "anónima pero real"
    assert entry["id"] == "910"


def test_named_bot_review_publishes_with_display_name(cog_with_user, monkeypatch):
    publish = AsyncMock(return_value={"committed": True, "count": 1})
    monkeypatch.setattr(reviews.github_publish, "publish_review", publish)
    msg = _bot_review_message(msg_id=911, description="con mi nombre", author_name="Kira")
    asyncio.run(cog_with_user._publish(msg))
    entry = publish.await_args.args[0]
    assert entry["author"] == "Kira"


# ── persistence contract: stable button custom_ids on a timeout=None view ──────────
def test_collect_view_button_custom_ids_are_stable_constants():
    async def _mk():
        return reviews.ReviewCollectView()             # View() needs a running loop
    view = asyncio.run(_mk())
    ids = {c.custom_id for c in view.children}
    assert ids == {reviews.REVIEW_BTN_NAMED, reviews.REVIEW_BTN_ANON}
    assert reviews.REVIEW_BTN_NAMED == "reviews:collect:named"
    assert reviews.REVIEW_BTN_ANON == "reviews:collect:anon"
    assert view.timeout is None                        # persistent (survives restart)


# ── modal on_submit: named carries identity, anonymous eliminates it ───────────────
def _modal_interaction(display_name, sent_capture):
    sent = types.SimpleNamespace(add_reaction=AsyncMock())

    async def _send(**kwargs):
        sent_capture["embed"] = kwargs.get("embed")
        return sent

    channel = types.SimpleNamespace(send=_send)
    client = types.SimpleNamespace(
        get_channel=lambda cid: channel,
        fetch_channel=AsyncMock(return_value=channel),
    )
    interaction = types.SimpleNamespace(
        client=client,
        user=types.SimpleNamespace(display_name=display_name, id=7, name=display_name),
        response=types.SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )
    return interaction, sent


def test_anonymous_modal_embed_omits_submitter_identity():
    secret = "SecretUser1234"
    captured = {}
    interaction, sent = _modal_interaction(secret, captured)

    async def _run():
        modal = reviews.ReviewModal(anonymous=True)
        modal.review_text._value = "trabajo espectacular"
        await modal.on_submit(interaction)

    asyncio.run(_run())
    embed = captured["embed"]
    assert "trabajo espectacular" in (embed.description or "")
    # identity must appear NOWHERE in the embed the bot posts
    assert (getattr(embed.author, "name", None) or "") != secret
    assert secret not in (embed.description or "")
    assert secret not in (embed.title or "")
    sent.add_reaction.assert_awaited_once_with("✅")   # marks it ✅ pending itself


def test_named_modal_embed_carries_display_name():
    name = "Luna"
    captured = {}
    interaction, sent = _modal_interaction(name, captured)

    async def _run():
        modal = reviews.ReviewModal(anonymous=False)
        modal.review_text._value = "gran experiencia"
        await modal.on_submit(interaction)

    asyncio.run(_run())
    embed = captured["embed"]
    assert embed.author.name == name
    assert "gran experiencia" in (embed.description or "")
    sent.add_reaction.assert_awaited_once_with("✅")


# ── _reconcile over the cog's OWN review embed (REV-05 — no longer blanket-skipped) ─
def test_reconcile_bot_review_embed_staff_check_publishes(cog_with_user):
    cog_with_user._publish = AsyncMock()
    msg = _bot_review_message(
        msg_id=920,
        reactions=[_full_reaction("✅", me=True, users=[_user(42, is_bot=True), _user(7)])],
        members={7: _member([STAFF_ROLE_ID])},
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._publish.assert_awaited_once_with(msg)   # bot review embed IS reconciled


def test_reconcile_bot_review_embed_staff_moon_unpublishes(cog_with_user):
    cog_with_user._unpublish = AsyncMock()
    msg = _bot_review_message(
        msg_id=921,
        reactions=[_full_reaction("🌙", users=[_user(8)])],
        members={8: _member([STAFF_ROLE_ID])},
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._unpublish.assert_awaited_once_with(msg)


def test_reconcile_bot_review_embed_already_published_left_alone(cog_with_user):
    cog_with_user._publish = AsyncMock()
    cog_with_user._unpublish = AsyncMock()
    msg = _bot_review_message(
        msg_id=922,
        reactions=[_full_reaction("🟢", me=True),
                   _full_reaction("✅", me=True, users=[_user(5)])],
        members={5: _member([STAFF_ROLE_ID])},
    )
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._publish.assert_not_awaited()            # 🟢 present -> not republished
    cog_with_user._unpublish.assert_not_awaited()
    msg.add_reaction.assert_not_awaited()


def test_reconcile_bot_non_review_message_still_skipped(cog_with_user):
    # A bot message WITHOUT the review marker is still skipped like any foreign bot post.
    cog_with_user._publish = AsyncMock()
    msg = _bot_review_message(msg_id=923, footer_text="otro pie", reactions=[])
    asyncio.run(cog_with_user._reconcile(msg))
    cog_with_user._publish.assert_not_awaited()
    msg.add_reaction.assert_not_awaited()


# ── 01-01 Wave 0: read-at-use + empty-list → gallery fallback at the gate ──────────
# EXPECTED RED until 01-03 drops config.py's frozen REVIEWS_STAFF_ROLE_IDS assignment and
# adds the config.__getattr__ shim that routes reads through settings.get (incl. CONF-03 fallback).
def test_reviews_staff_gate_reads_at_use(tmp_path, monkeypatch):
    # Strip the autouse _reviews_config pins so config.X falls through to settings.get.
    monkeypatch.delattr(config, "REVIEWS_STAFF_ROLE_IDS", raising=False)
    monkeypatch.delattr(config, "REVIEWS_CHANNEL_ID", raising=False)
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "cog.db"), raising=False)
    db.init_settings()
    settings.set("REVIEWS_STAFF_ROLE_IDS", [STAFF_ROLE_ID])
    assert reviews._is_staff(_member([STAFF_ROLE_ID])) is True
    settings.set("REVIEWS_STAFF_ROLE_IDS", [OTHER_ROLE_ID])       # change the stored list
    assert reviews._is_staff(_member([STAFF_ROLE_ID])) is False   # second read reflects it
    # empty specific list → the gate composes down to GALLERY_STAFF_ROLE_IDS (CONF-03)
    settings.set("REVIEWS_STAFF_ROLE_IDS", [])
    settings.set("GALLERY_STAFF_ROLE_IDS", [STAFF_ROLE_ID])
    assert reviews._is_staff(_member([STAFF_ROLE_ID])) is True
