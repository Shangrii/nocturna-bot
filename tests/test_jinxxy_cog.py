"""Unit tests for the JinxxyCog store-sync controller (Fase 9, plan 09-05).

Drives ``_run_sync`` / ``_is_staff`` / the ``/tienda sync`` command / ``_announce`` / ``on_ready``
directly with ``SimpleNamespace`` + ``AsyncMock`` fakes and ``asyncio.run`` (repo idiom, no
pytest-asyncio). The pure core (``store_sync``) runs for real; the API read client, the durable
DB snapshot store and the cross-repo transport are monkeypatched so the cog's orchestration,
removal-safety (T-09-15) and D-05 errors-never-Discord discipline are asserted without any
network/DB/Discord side effect.
"""

import asyncio
import types
from unittest.mock import AsyncMock

import pytest

import config
from cogs import jinxxy

STAFF_ROLE_ID = 111
OTHER_ROLE_ID = 222
ANNOUNCE_CHANNEL_ID = 4242

# A single Jinxxy product detail (map_product reads name/url/base_price/category/
# restrictions/created_at). Its constructed checkoutUrl is the store link key.
DETAIL = {
    "id": "p1", "name": "Cahuama", "url": "cahuama", "base_price": 0,
    "category": "avatar-props", "restrictions": [], "created_at": "2026-07-01T12:00:00Z",
}
KEY = "https://jinxxy.com/nocturna/cahuama"


def _member(role_ids):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids], bot=False)


@pytest.fixture(autouse=True)
def _jinxxy_config(monkeypatch):
    monkeypatch.setattr(config, "JINXXY_STAFF_ROLE_IDS", [STAFF_ROLE_ID], raising=False)
    monkeypatch.setattr(config, "JINXXY_ANNOUNCE_CHANNEL_ID", ANNOUNCE_CHANNEL_ID,
                        raising=False)


class _Recorder:
    def __init__(self):
        self.upserts = []
        self.deletes = []
        self.synced = []


@pytest.fixture
def cog(monkeypatch):
    """A JinxxyCog with the DB table init + poll-loop start neutralized (no side effects)."""
    monkeypatch.setattr(jinxxy.db, "init_store_state", lambda: None)
    monkeypatch.setattr(jinxxy.tasks.Loop, "start", lambda self, *a, **k: None)
    return jinxxy.JinxxyCog(bot=types.SimpleNamespace())


def _wire(monkeypatch, *, products, detail=DETAIL, me=None, snapshot=None,
          current=None, list_error=None):
    """Patch the API/DB/transport cores around a REAL store_sync merge; return a recorder."""
    rec = _Recorder()
    me = me or {"username": "nocturna", "display_name": "Nocturna"}

    def _get_me(*a, **k):
        return me

    def _list(*a, **k):
        if list_error is not None:
            raise list_error
        return products

    def _get_product(pid, *a, **k):
        return dict(detail, id=pid)

    monkeypatch.setattr(jinxxy.jinxxy_api, "get_me", _get_me)
    monkeypatch.setattr(jinxxy.jinxxy_api, "list_all_products", _list)
    monkeypatch.setattr(jinxxy.jinxxy_api, "get_product", _get_product)
    monkeypatch.setattr(jinxxy.db, "get_store_snapshot", lambda: dict(snapshot or {}))
    monkeypatch.setattr(jinxxy.db, "upsert_store_snapshot",
                        lambda **kw: rec.upserts.append(kw))
    monkeypatch.setattr(jinxxy.db, "delete_store_snapshot",
                        lambda url: rec.deletes.append(url))

    def _fetch_store(repo, branch, path):
        return {"_comment": "schema", "products": list(current or [])}

    monkeypatch.setattr(jinxxy.github_publish, "_fetch_store", _fetch_store)

    async def _sync_store(prods, *a, **k):
        rec.synced.append(list(prods))
        return {"committed": True, "commit_sha": "abc", "count": len(prods)}

    monkeypatch.setattr(jinxxy.github_publish, "sync_store", AsyncMock(side_effect=_sync_store))
    rec.sync_mock = jinxxy.github_publish.sync_store
    return rec


def _snapshot_row(key=KEY, name="Cahuama", price="0", category="avatar-props",
                  nsfw=0, date="2026-07-01"):
    return {"checkout_url": key, "jinxxy_id": "p1", "name": name, "price": price,
            "category": category, "nsfw": nsfw, "date": date, "synced_at": "2026-07-01T00:00:00Z"}


def _current_entry(key=KEY, name="Cahuama", price="0", category="avatar-props",
                   nsfw=False, date="2026-07-01"):
    return {"checkoutUrl": key, "id": "cahuama", "name": {"es": name, "en": name},
            "price": price, "category": category, "editor": "Nocturna", "nsfw": nsfw,
            "date": date, "description": {"es": "", "en": ""}}


# ── _is_staff (T-09-14 role gate) ──────────────────────────────────────────────────
def test_is_staff_true_when_role_intersects():
    assert jinxxy._is_staff(_member([OTHER_ROLE_ID, STAFF_ROLE_ID])) is True


def test_is_staff_false_without_matching_role():
    assert jinxxy._is_staff(_member([OTHER_ROLE_ID])) is False


def test_is_staff_false_for_roleless_member():
    assert jinxxy._is_staff(_member([])) is False


# ── _run_sync: commit-on-change + snapshot upsert ──────────────────────────────────
def test_run_sync_new_product_commits_once_and_upserts(cog, monkeypatch):
    rec = _wire(monkeypatch, products=[{"id": "p1"}])
    result = asyncio.run(cog._run_sync())
    assert rec.sync_mock.await_count == 1          # exactly one commit on a change
    assert result["changed"] is True
    assert KEY in result["added"]
    # snapshot upserted for the live product
    assert any(u.get("checkout_url") == KEY for u in rec.upserts)
    assert rec.deletes == []                       # nothing removed on an add-only sync


def test_run_sync_new_product_carries_description_and_string_id(cog, monkeypatch):
    rec = _wire(monkeypatch, products=[{"id": "p1"}])
    asyncio.run(cog._run_sync())
    committed = rec.sync_mock.await_args.args[0]   # the products list handed to sync_store
    prod = next(p for p in committed if p["checkoutUrl"] == KEY)
    assert prod["description"] == {"es": "", "en": ""}   # StorePage.astro structural filter
    assert isinstance(prod["id"], str) and prod["id"]


# ── _run_sync: no-op when nothing changed (D-06 silent) ────────────────────────────
def test_run_sync_no_change_does_not_commit(cog, monkeypatch):
    rec = _wire(monkeypatch, products=[{"id": "p1"}],
                snapshot={KEY: _snapshot_row()}, current=[_current_entry()])
    result = asyncio.run(cog._run_sync())
    assert result["changed"] is False
    assert rec.sync_mock.await_count == 0          # zero commits — silent no-op


# ── _run_sync: removal-safety on API failure (T-09-15) ─────────────────────────────
def test_run_sync_api_failure_aborts_no_removal_no_commit(cog, monkeypatch):
    boom = jinxxy.jinxxy_api.JinxxyAPIError("GET /products failed: HTTP 503")
    # A pre-existing product that WOULD be removed if list returned []; the outage must not.
    rec = _wire(monkeypatch, products=[], snapshot={KEY: _snapshot_row()},
                current=[_current_entry()], list_error=boom)
    with pytest.raises(jinxxy.jinxxy_api.JinxxyAPIError):
        asyncio.run(cog._run_sync())
    assert rec.sync_mock.await_count == 0          # never commits on an outage
    assert rec.deletes == []                       # never mass-removes the storefront


# ══ Task 2: /tienda sync command + branded announce embed (D-05/D-06) ═══════════════

def _channel():
    return types.SimpleNamespace(send=AsyncMock())


def _bot_with_channel(channel):
    return types.SimpleNamespace(
        get_channel=lambda cid: channel,
        fetch_channel=AsyncMock(return_value=channel),
        wait_until_ready=AsyncMock(),
    )


def _sync_interaction(role_ids):
    return types.SimpleNamespace(
        user=_member(role_ids),
        response=types.SimpleNamespace(
            send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: False),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


async def _call_sync(cog, interaction):
    await jinxxy.JinxxyCog.sync.callback(cog, interaction)


# ── _announce silent on no change (D-06) ───────────────────────────────────────────
def test_announce_silent_on_no_change(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    asyncio.run(cog._announce({"changed": False, "added": [], "updated": [], "removed": [],
                               "products": []}))
    ch.send.assert_not_awaited()


# ── _announce sends a branded embed on change ──────────────────────────────────────
def test_announce_sends_branded_embed_on_change(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    asyncio.run(cog._announce(result))
    ch.send.assert_awaited_once()
    embed = ch.send.await_args.kwargs["embed"]
    assert embed.color.value == 0xC0192C
    assert "Cahuama" in "".join(f.value for f in embed.fields)


# ── /tienda sync staff gate FIRST (T-09-14) ────────────────────────────────────────
def test_sync_command_non_staff_rejected_before_any_work(cog, monkeypatch):
    called = []
    monkeypatch.setattr(cog, "_run_sync",
                        AsyncMock(side_effect=lambda: called.append(1)))
    inter = _sync_interaction([OTHER_ROLE_ID])
    asyncio.run(_call_sync(cog, inter))
    assert inter.response.send_message.await_args.args[0] == "Sin permisos."
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True
    inter.response.defer.assert_not_awaited()      # gated before defer
    assert called == []                            # _run_sync never ran


# ── /tienda sync error → ephemeral to invoker, NEVER announced (D-05) ──────────────
def test_sync_command_error_is_ephemeral_never_announced(cog, monkeypatch):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    boom = jinxxy.github_publish.GitHubPublishError("commit failed")
    monkeypatch.setattr(cog, "_run_sync", AsyncMock(side_effect=boom))
    inter = _sync_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_sync(cog, inter))
    inter.response.defer.assert_awaited_once()
    inter.followup.send.assert_awaited_once()      # ephemeral reply to the invoker
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True
    ch.send.assert_not_awaited()                   # nothing posted to the announce channel


# ── /tienda sync success announces + confirms ──────────────────────────────────────
def test_sync_command_success_announces_and_confirms(cog, monkeypatch):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    monkeypatch.setattr(cog, "_run_sync", AsyncMock(return_value=result))
    inter = _sync_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_sync(cog, inter))
    ch.send.assert_awaited_once()                  # announced on change
    inter.followup.send.assert_awaited_once()      # ephemeral summary to invoker
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True
