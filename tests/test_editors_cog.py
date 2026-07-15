"""Unit tests for EditorsCog — role-loss auto-unpublish + optional /mi-pagina (10-09).

Closes EDIT-07's role-loss half (D-10): an editor who loses the editor role has their page
auto-unpublished, in real time via ``on_member_update`` (PRIMARY — the ``members`` intent is
enabled per 10-03) and via a periodic ``@tasks.loop`` sweep as the backstop. The sweep carries a
HARD mass-removal guard (T-10-09-02): a transient membership-check error unpublishes NOTHING.

Repo idiom: SimpleNamespace/AsyncMock fakes + ``asyncio.run`` (no pytest-asyncio); the sweep
loop's ``tasks.Loop.start`` is neutralized in the ``cog`` fixture so instantiating the cog has no
side effects; the ``unpublish_editor`` transport and the ``_fetch_json`` editors read are mocked.
"""

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import config
from cogs import editors

EDITOR_ROLE_ID = 111
OTHER_ROLE_ID = 222
GUILD_ID = 9999


@pytest.fixture(autouse=True)
def _editors_config(monkeypatch):
    # The editor role reuses the moderator role (D-15); pin both it and the guild id.
    monkeypatch.setattr(config, "ROLE_MODERATOR_ID", EDITOR_ROLE_ID, raising=False)
    monkeypatch.setattr(config, "GUILD_ID", GUILD_ID, raising=False)
    monkeypatch.setattr(config, "EDITOR_APP_BASE_URL",
                        "https://editors.nocturna-avatars.site", raising=False)


@pytest.fixture
def cog(monkeypatch):
    """An EditorsCog with the sweep loop's ``tasks.Loop.start`` neutralized (no side effects)."""
    monkeypatch.setattr(editors.tasks.Loop, "start", lambda self, *a, **k: None)
    return editors.EditorsCog(bot=types.SimpleNamespace())


# ── fakes ───────────────────────────────────────────────────────────────────────────
def _member(role_ids, uid=5, is_bot=False):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids],
        id=uid,
        bot=is_bot,
    )


def _http_error(status=500, reason="boom"):
    return discord.HTTPException(types.SimpleNamespace(status=status, reason=reason), "boom")


def _not_found(reason="gone"):
    return discord.NotFound(types.SimpleNamespace(status=404, reason=reason), "gone")


def _guild(members_by_id, fetch_side_effect=None):
    """A guild fake whose cache is ``members_by_id`` and whose ``fetch_member`` is an AsyncMock.

    ``get_member(int_id)`` returns the cached member or None; a cache miss falls through to
    ``fetch_member`` (the AsyncMock, driven by ``fetch_side_effect``).
    """
    fetch = AsyncMock(side_effect=fetch_side_effect)
    return types.SimpleNamespace(
        get_member=lambda mid: members_by_id.get(mid),
        fetch_member=fetch,
    )


# ══ on_member_update — real-time role-loss detection (D-10 PRIMARY) ══════════════════
def test_on_member_update_role_removed_unpublishes_once(cog, monkeypatch):
    unpub = AsyncMock(return_value={"committed": True, "slug": "ana"})
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    before = _member([OTHER_ROLE_ID, EDITOR_ROLE_ID], uid=42)   # had the editor role
    after = _member([OTHER_ROLE_ID], uid=42)                    # …and lost it
    asyncio.run(cog.on_member_update(before, after))
    unpub.assert_awaited_once()
    assert unpub.await_args.args[0] == "42"                     # by discordId, as a string


def test_on_member_update_role_still_present_no_unpublish(cog, monkeypatch):
    unpub = AsyncMock()
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    before = _member([EDITOR_ROLE_ID], uid=42)
    after = _member([EDITOR_ROLE_ID, OTHER_ROLE_ID], uid=42)    # gained an unrelated role
    asyncio.run(cog.on_member_update(before, after))
    unpub.assert_not_awaited()


def test_on_member_update_role_added_no_unpublish(cog, monkeypatch):
    unpub = AsyncMock()
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    before = _member([OTHER_ROLE_ID], uid=42)                  # did NOT have the role
    after = _member([OTHER_ROLE_ID, EDITOR_ROLE_ID], uid=42)   # …just got it
    asyncio.run(cog.on_member_update(before, after))
    unpub.assert_not_awaited()


# ══ periodic sweep — backstop with a hard mass-removal guard ═════════════════════════
def _patch_editors_json(monkeypatch, entries):
    monkeypatch.setattr(editors.github_publish, "_fetch_json",
                        MagicMock(return_value=list(entries)))


def test_sweep_unpublishes_only_confirmed_role_losers(cog, monkeypatch):
    # ana still holds the role → keep; beto lost it → unpublish; carla is a draft (published
    # False) → excluded from the candidate set entirely (never touched).
    _patch_editors_json(monkeypatch, [
        {"discordId": "1", "slug": "ana", "published": True},
        {"discordId": "2", "slug": "beto", "published": True},
        {"discordId": "3", "slug": "carla", "published": False},
    ])
    members = {
        1: _member([EDITOR_ROLE_ID], uid=1),                   # still an editor
        2: _member([OTHER_ROLE_ID], uid=2),                    # lost the editor role
    }
    cog.bot.get_guild = lambda gid: _guild(members)
    unpub = AsyncMock(return_value={"committed": True, "slug": "beto"})
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    asyncio.run(cog._process_role_losses())
    unpub.assert_awaited_once()
    assert unpub.await_args.args[0] == "2"                      # only beto


def test_sweep_member_left_guild_is_a_confirmed_loser(cog, monkeypatch):
    # A member who left the guild entirely (fetch_member → NotFound) has, by definition, lost
    # the role — a confirmed (not transient) loss → unpublish.
    _patch_editors_json(monkeypatch, [
        {"discordId": "7", "slug": "dana", "published": True},
    ])
    cog.bot.get_guild = lambda gid: _guild({}, fetch_side_effect=_not_found())
    unpub = AsyncMock(return_value={"committed": True, "slug": "dana"})
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    asyncio.run(cog._process_role_losses())
    unpub.assert_awaited_once_with("7")


def test_sweep_transient_membership_error_unpublishes_nothing(cog, monkeypatch):
    # MASS-REMOVAL GUARD (T-10-09-02): beto clearly lost the role, but resolving carla raises a
    # transient HTTPException → the WHOLE sweep aborts with ZERO unpublishes (mirrors the Phase-9
    # enumerate-before-remove abort). Never mass-remove on a transient outage.
    _patch_editors_json(monkeypatch, [
        {"discordId": "2", "slug": "beto", "published": True},
        {"discordId": "9", "slug": "carla", "published": True},
    ])
    members = {2: _member([OTHER_ROLE_ID], uid=2)}             # beto lost the role (a loser)
    cog.bot.get_guild = lambda gid: _guild(members, fetch_side_effect=_http_error())
    unpub = AsyncMock()
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    asyncio.run(cog._process_role_losses())
    unpub.assert_not_awaited()                                 # ZERO — not even the sure loser


def test_sweep_unresolvable_guild_unpublishes_nothing(cog, monkeypatch):
    # Can't verify membership without the guild → abort with zero unpublishes (never guess).
    _patch_editors_json(monkeypatch, [
        {"discordId": "2", "slug": "beto", "published": True},
    ])
    cog.bot.get_guild = lambda gid: None
    unpub = AsyncMock()
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    asyncio.run(cog._process_role_losses())
    unpub.assert_not_awaited()


def test_sweep_skips_already_unpublished_entries(cog, monkeypatch):
    # Idempotency at the candidate-set level (D-13/D-16): a page that is already unpublished
    # (published False) is never re-considered, so the transport's no-op guard is never even hit.
    _patch_editors_json(monkeypatch, [
        {"discordId": "3", "slug": "carla", "published": False},
    ])
    got_guild = MagicMock(return_value=_guild({}))
    cog.bot.get_guild = got_guild
    unpub = AsyncMock()
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    asyncio.run(cog._process_role_losses())
    unpub.assert_not_awaited()


def test_sweep_no_published_editors_is_a_noop(cog, monkeypatch):
    _patch_editors_json(monkeypatch, [])
    unpub = AsyncMock()
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    # get_guild must never even be reached when there are no candidates.
    cog.bot.get_guild = MagicMock(side_effect=AssertionError("should not resolve the guild"))
    asyncio.run(cog._process_role_losses())
    unpub.assert_not_awaited()


def test_unpublish_transport_error_is_swallowed_to_logs(cog, monkeypatch):
    # D-05: a transport failure goes to logs only — it must not escape the sweep/event.
    _patch_editors_json(monkeypatch, [
        {"discordId": "2", "slug": "beto", "published": True},
    ])
    members = {2: _member([OTHER_ROLE_ID], uid=2)}
    cog.bot.get_guild = lambda gid: _guild(members)
    unpub = AsyncMock(side_effect=editors.github_publish.GitHubPublishError("boom"))
    monkeypatch.setattr(editors.github_publish, "unpublish_editor", unpub)
    asyncio.run(cog._process_role_losses())                    # must NOT raise
    unpub.assert_awaited_once()


# ══ /mi-pagina — optional admin-link DM (D-05 remaining bot role) ════════════════════
def _mi_pagina_interaction(user):
    return types.SimpleNamespace(
        user=user,
        response=types.SimpleNamespace(send_message=AsyncMock()),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


def _editor_user(role_ids, uid=5):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids],
        id=uid,
        bot=False,
        send=AsyncMock(),
    )


def test_mi_pagina_non_staff_rejected_no_dm(cog):
    user = _editor_user([OTHER_ROLE_ID])                       # not an editor
    inter = _mi_pagina_interaction(user)
    asyncio.run(editors.EditorsCog.mi_pagina.callback(cog, inter))
    assert inter.response.send_message.await_args.args[0] == "Sin permisos."
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True
    user.send.assert_not_awaited()                             # no DM to a non-editor


def test_mi_pagina_dms_the_admin_link(cog):
    user = _editor_user([EDITOR_ROLE_ID])                      # an editor
    inter = _mi_pagina_interaction(user)
    asyncio.run(editors.EditorsCog.mi_pagina.callback(cog, inter))
    user.send.assert_awaited_once()
    dm = user.send.await_args.args[0]
    assert "https://editors.nocturna-avatars.site" in dm       # the admin-app link
    # Confirms to the invoker ephemerally that the DM was sent.
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True


def test_mi_pagina_dm_closed_replies_ephemerally(cog):
    user = _editor_user([EDITOR_ROLE_ID])
    user.send = AsyncMock(side_effect=_http_error(403, "cannot send to this user"))
    inter = _mi_pagina_interaction(user)
    asyncio.run(editors.EditorsCog.mi_pagina.callback(cog, inter))   # must NOT raise
    # Falls back to an ephemeral reply telling the editor to open their DMs.
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True


# ══ staff gate + lifecycle hooks ═════════════════════════════════════════════════════
def test_is_staff_matches_editor_role_only():
    assert editors._is_staff(_member([EDITOR_ROLE_ID])) is True
    assert editors._is_staff(_member([OTHER_ROLE_ID])) is False
    assert editors._is_staff(_member([])) is False


def test_before_sweep_waits_until_ready(cog):
    cog.bot.wait_until_ready = AsyncMock()
    asyncio.run(cog._before_sweep())
    cog.bot.wait_until_ready.assert_awaited_once()
