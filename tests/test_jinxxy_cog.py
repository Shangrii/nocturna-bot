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

import discord
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


# ── _run_sync: commit failure must NOT advance the snapshot (CR-01 09-11 regression guard) ──
def test_run_sync_commit_failure_does_not_advance_snapshot(cog, monkeypatch):
    # A genuine Jinxxy field change (live price "5" ≠ snapshot "0" ≠ current "0") reconciles to
    # changed=True. If the cross-repo commit then raises, the durable snapshot must stay behind the
    # un-written store.json so the NEXT cycle re-detects the change and retries — never silently
    # dropping it as a "Jinxxy unchanged, staff edit wins" no-op (CR-01, 09-VERIFICATION truth #5).
    rec = _wire(monkeypatch, products=[{"id": "p1"}], detail=dict(DETAIL, base_price=5),
                snapshot={KEY: _snapshot_row(price="0")}, current=[_current_entry(price="0")])
    monkeypatch.setattr(
        jinxxy.github_publish, "sync_store",
        AsyncMock(side_effect=jinxxy.github_publish.GitHubPublishError("commit failed: HTTP 409")))
    with pytest.raises(jinxxy.github_publish.GitHubPublishError):
        asyncio.run(cog._run_sync())
    # snapshot did NOT advance for the changed field → change is retried next cycle
    assert not any(u.get("checkout_url") == KEY for u in rec.upserts)
    assert rec.deletes == []                       # no removals ran across the failed commit


# ══ 09-09 Task 1: snapshot advances every successful sync (WR-03) + unkeyable carry (WR-06) ══

def test_run_sync_no_change_still_advances_snapshot(cog, monkeypatch):
    # Jinxxy already matches the staff value (price 0) but the durable snapshot is STALE
    # (price 5): the cycle reports changed=False yet the snapshot MUST advance to live truth —
    # else a LATER staff edit on price is misread as a both-changed conflict and reverted (WR-03).
    rec = _wire(monkeypatch, products=[{"id": "p1"}],
                snapshot={KEY: _snapshot_row(price="5")}, current=[_current_entry(price="0")])
    result = asyncio.run(cog._run_sync())
    assert result["changed"] is False              # no repo commit on a no-change cycle (D-06)
    assert rec.sync_mock.await_count == 0
    assert any(u.get("checkout_url") == KEY for u in rec.upserts)   # snapshot advanced anyway


def test_run_sync_unkeyable_current_product_survives(cog, monkeypatch):
    # A staff-added store.json entry with no usable checkoutUrl must be carried through verbatim
    # into the written products, never silently dropped on the next changed sync (WR-06).
    orphan = {"id": "handmade", "name": {"es": "Hecho a mano", "en": "Handmade"}}
    rec = _wire(monkeypatch, products=[{"id": "p1"}], current=[orphan])
    asyncio.run(cog._run_sync())
    committed = rec.sync_mock.await_args.args[0]    # the products list handed to sync_store
    assert orphan in committed                      # unkeyable staff entry preserved verbatim


def test_run_sync_removals_only_run_on_change(cog, monkeypatch):
    # delete_store_snapshot stays inside the changed branch: a no-change cycle deletes nothing
    # even though the snapshot upsert now runs unconditionally.
    rec = _wire(monkeypatch, products=[{"id": "p1"}],
                snapshot={KEY: _snapshot_row()}, current=[_current_entry()])
    asyncio.run(cog._run_sync())
    assert rec.deletes == []


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


# ── _announce sends a branded, ENGLISH, visual embed on change (GAP-2) ──────────────
def test_announce_sends_branded_embed_on_change(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    asyncio.run(cog._announce(result))
    ch.send.assert_awaited_once()
    embed = ch.send.await_args.kwargs["embed"]
    # Brand red is unchanged; copy is English + engaging (D-05 override for STORE announces).
    assert embed.color.value == 0xC0192C
    assert embed.title == "New on the Nocturna store"
    assert "new product on our webpage" in (embed.description or "").lower()
    # The store-page link appears in the embed (as embed.url and as a field link).
    assert embed.url == config.JINXXY_STORE_URL
    assert config.JINXXY_STORE_URL in "".join(f.value for f in embed.fields)
    # The old Spanish strings are gone.
    assert "Tienda actualizada" not in (embed.title or "")
    assert (embed.footer.text or "") != "Nocturna · tienda"


# CR-01: an updated-only / removed-only cycle must NOT claim "New" — the headline has to
# reflect what actually changed (the pre-09-13 change-agnostic behaviour, restored).
def test_announce_updated_only_does_not_claim_new(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [], "updated": [KEY], "removed": [],
              "products": [_current_entry()]}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    assert embed.title == "Nocturna store updated"
    assert "new" not in (embed.title or "").lower()
    assert "new product on our webpage" not in (embed.description or "").lower()


def test_announce_removed_only_does_not_claim_new(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    # a delisted product: it's in `removed` but no longer in the current `products` catalog
    result = {"changed": True, "added": [], "updated": [], "removed": [KEY],
              "products": []}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    assert embed.title == "Nocturna store updated"
    assert "new" not in (embed.title or "").lower()
    assert "new product on our webpage" not in (embed.description or "").lower()


def test_announce_embed_links_added_product_to_checkout_url(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    joined = "".join(f.value for f in embed.fields)
    assert f"[Cahuama]({KEY})" in joined       # name rendered as a markdown link to its checkoutUrl


def test_announce_embed_sanitizes_markdown_in_product_name(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    entry = _current_entry(name="Ca[hu](evil)ama")
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [entry]}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    joined = "".join(f.value for f in embed.fields)
    assert f"[Cahuevilama]({KEY})" in joined    # []() stripped from the label (T-09-28)


# WR-02: a bucket long enough to exceed the field cap must truncate on a LINE boundary with
# an "...and N more" tail — never a hard slice that could cut inside a `[label](url)` span.
def test_announce_embed_truncates_long_bucket_at_line_boundary(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    entries = []
    added = []
    for i in range(40):                       # 40 markdown links → joined value exceeds 1024
        key = f"https://jinxxy.com/nocturna/prod{i:02d}"
        entries.append(_current_entry(key=key, name=f"Producto Numero {i:02d}"))
        added.append(key)
    result = {"changed": True, "added": added, "updated": [], "removed": [],
              "products": entries}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    field = next(f for f in embed.fields if f.name.startswith("🆕 New"))
    assert len(field.value) <= 1024                       # within Discord's field cap
    field_lines = field.value.split("\n")
    assert field_lines[-1].startswith("...and ")          # truncation indicator, not a cut link
    assert "more" in field_lines[-1]
    for line in field_lines[:-1]:                         # every kept product line is intact
        assert line.startswith("• [")
        assert line.endswith(")")                         # no dangling `[` / unterminated `(url`
        assert "](" in line


def test_announce_embed_sets_thumbnail_from_site_relative_image(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    entry = dict(_current_entry(), images=["/store/x.webp"])
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [entry]}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    assert embed.thumbnail.url == config.WEBSITE_BASE_URL + "/store/x.webp"


def test_announce_embed_no_thumbnail_when_no_product_has_images(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}      # _current_entry has no images
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    assert embed.thumbnail.url is None


# WR-01: the thumbnail fallback must only consider the CHANGED set (added + updated), never
# the full catalog — an unrelated, unchanged product's image must not leak into the embed.
def test_announce_thumbnail_ignores_unrelated_unchanged_product_image(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    OTHER = "https://jinxxy.com/nocturna/otro"
    changed = _current_entry()                                  # the updated product, NO images
    unrelated = dict(_current_entry(key=OTHER, name="Otro"),    # unchanged, HAS an image
                     images=["/store/unrelated.webp"])
    result = {"changed": True, "added": [], "updated": [KEY], "removed": [],
              "products": [changed, unrelated]}                 # both in the full catalog
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    # the changed product has no image and the unrelated one is out of scope → no thumbnail
    assert embed.thumbnail.url is None


def test_announce_thumbnail_uses_updated_product_image(cog):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    changed = dict(_current_entry(), images=["/store/changed.webp"])   # updated + HAS an image
    result = {"changed": True, "added": [], "updated": [KEY], "removed": [],
              "products": [changed]}
    asyncio.run(cog._announce(result))
    embed = ch.send.await_args.kwargs["embed"]
    assert embed.thumbnail.url == config.WEBSITE_BASE_URL + "/store/changed.webp"


# ══ 09-10 Task 3 (WR-09): a channel.send failure is logged and swallowed, never raised ══
#
# _announce's docstring promises "logged and skipped — never raised", but channel.send was
# unwrapped: discord.Forbidden (missing send perm) / HTTPException propagated — hanging the
# /tienda sync ephemeral summary and triggering a full poll restart over a cosmetic failure.


def _raising_channel(exc):
    return types.SimpleNamespace(send=AsyncMock(side_effect=exc))


def test_announce_forbidden_channel_is_logged_not_raised(cog, caplog):
    forbidden = discord.Forbidden(
        types.SimpleNamespace(status=403, reason="perms"), "missing permissions")
    cog.bot = _bot_with_channel(_raising_channel(forbidden))
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    with caplog.at_level("INFO", logger="cogs.jinxxy"):
        asyncio.run(cog._announce(result))            # must NOT raise
    assert any(r.levelname == "ERROR" for r in caplog.records)   # failure recorded (log.exception)


def test_announce_http_error_channel_does_not_raise(cog):
    http = discord.HTTPException(
        types.SimpleNamespace(status=500, reason="boom"), "boom")
    cog.bot = _bot_with_channel(_raising_channel(http))
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    asyncio.run(cog._announce(result))                # a cosmetic HTTPException never propagates


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


# ══ 09-10 Task 2 (WR-08): a mapping error (KeyError/TypeError) still hits the D-05 path ══
#
# map_product hard-indexes detail["name"]/["url"]/["base_price"]/["created_at"]; a malformed
# 2xx detail raises KeyError/TypeError — neither GitHubPublishError nor JinxxyAPIError. Before
# broadening the guard those escaped the `except (GitHubPublishError, JinxxyAPIError)` and left
# the deferred interaction hanging with no ephemeral reply.


@pytest.mark.parametrize("boom", [KeyError("name"), TypeError("NoneType not subscriptable")])
def test_sync_command_mapping_error_is_ephemeral_never_announced(cog, monkeypatch, boom):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    monkeypatch.setattr(cog, "_run_sync", AsyncMock(side_effect=boom))
    inter = _sync_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_sync(cog, inter))              # must not raise
    inter.response.defer.assert_awaited_once()
    inter.followup.send.assert_awaited_once()        # ephemeral "revisa los logs" reply
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True
    assert "logs" in inter.followup.send.await_args.args[0]
    ch.send.assert_not_awaited()                     # nothing posted publicly (D-05)


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


# ══ 09-09 Task 2: single startup reconcile (CR-01) + bounded poll cool-down (WR-02) ══
#
# The duplicate on_ready startup entry point is GONE — the poll loop's own immediate first tick
# (which tasks.loop runs right after `before_loop`) is the sole startup reconcile, so a boot
# reconciles once and announces once, not twice.


# ── CR-01: no on_ready listener / no _synced_once flag remain on the cog ─────────────
def test_no_on_ready_listener_defined():
    assert "on_ready" not in vars(jinxxy.JinxxyCog)


def test_no_synced_once_flag(cog):
    assert not hasattr(cog, "_synced_once")


# ── the poll loop body is the single startup reconcile: one tick → one _run_sync ─────
def test_poll_tick_runs_single_startup_reconcile(cog, monkeypatch):
    cog.bot = _bot_with_channel(_channel())
    result = {"changed": False, "added": [], "updated": [], "removed": [], "products": []}
    run = AsyncMock(return_value=result)
    monkeypatch.setattr(cog, "_run_sync", run)
    asyncio.run(jinxxy.JinxxyCog._poll.coro(cog))
    assert run.await_count == 1                     # exactly one sync per tick


# ── a changed poll tick announces ──────────────────────────────────────────────────
def test_poll_tick_changed_sync_announces(cog, monkeypatch):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    result = {"changed": True, "added": [KEY], "updated": [], "removed": [],
              "products": [_current_entry()]}
    monkeypatch.setattr(cog, "_run_sync", AsyncMock(return_value=result))
    asyncio.run(jinxxy.JinxxyCog._poll.coro(cog))
    ch.send.assert_awaited_once()


# ── WR-02: a failed poll waits the bounded cool-down BEFORE restarting (no tight loop) ─
def test_on_poll_error_sleeps_cooldown_before_restart(cog, monkeypatch):
    order = []

    async def _sleep(secs):
        order.append(("sleep", secs))

    monkeypatch.setattr(jinxxy.asyncio, "sleep", _sleep)
    monkeypatch.setattr(cog._poll, "restart", lambda *a, **k: order.append(("restart",)))
    asyncio.run(jinxxy.JinxxyCog._on_poll_error(cog, RuntimeError("boom")))
    assert jinxxy._POLL_RETRY_COOLDOWN_S > 0
    assert order == [("sleep", jinxxy._POLL_RETRY_COOLDOWN_S), ("restart",)]  # sleep then restart


# ══ 09-09 Task 3: a /me without a username hard-fails BEFORE any write (WR-04) ══════
#
# A malformed-but-2xx /me missing a username would build `jinxxy.com//slug` keys and mass-rewrite
# every checkoutUrl. The sync must raise a typed JinxxyAPIError before enumeration/commit instead.


def test_run_sync_missing_username_raises_before_any_write(cog, monkeypatch):
    rec = _wire(monkeypatch, products=[{"id": "p1"}], me={"display_name": "Nocturna"})
    with pytest.raises(jinxxy.jinxxy_api.JinxxyAPIError):
        asyncio.run(cog._run_sync())
    assert rec.sync_mock.await_count == 0          # no store rewrite on a malformed /me
    assert rec.deletes == []                       # and no snapshot removal


def test_run_sync_blank_username_raises_before_any_write(cog, monkeypatch):
    rec = _wire(monkeypatch, products=[{"id": "p1"}],
                me={"username": "", "display_name": "Nocturna"})
    with pytest.raises(jinxxy.jinxxy_api.JinxxyAPIError):
        asyncio.run(cog._run_sync())
    assert rec.sync_mock.await_count == 0
    assert rec.deletes == []


# ══ Plan 09-06: /tienda medios — attach staff images + description (D-14/D-15) ═══════
#
# The Creator API exposes no images/description (D-14 live probe), so staff supply them
# through Discord. `/tienda medios` optimizes attachments to WebP and commits them +
# a bilingual description into the matched product via `attach_store_media` (09-04) —
# images/description staying 100% staff-owned (the sync merge never writes them).


class _FakeAttachment:
    """A discord.Attachment stand-in that records how many times its bytes were read."""

    def __init__(self, data=b"rawbytes"):
        self._data = data
        self.reads = 0

    async def read(self):
        self.reads += 1
        return self._data


def _medios_interaction(role_ids):
    return types.SimpleNamespace(
        user=_member(role_ids),
        response=types.SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


async def _call_medios(cog, interaction, **kwargs):
    await jinxxy.JinxxyCog.medios.callback(cog, interaction, **kwargs)


# ── _optimize_attachments: raw bytes → (webp, bot-generated numeric/slug filename) ──
def test_optimize_attachments_returns_numeric_webp_filenames(monkeypatch):
    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp",
                        lambda raw: (b"WEBP:" + raw, 100, 80))
    media = jinxxy._optimize_attachments([b"a", b"b"], slug="cahuama")
    assert [f for _, f in media] == ["cahuama-1.webp", "cahuama-2.webp"]
    assert all(w.startswith(b"WEBP:") for w, _ in media)     # re-encoded, not verbatim
    assert all(f.endswith(".webp") for _, f in media)


def test_optimize_attachments_default_slug_has_no_user_text(monkeypatch):
    # No slug supplied → a bot-generated base, never raw user text (T-09-19).
    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp", lambda raw: (b"W", 1, 1))
    media = jinxxy._optimize_attachments([b"a"])
    _, fname = media[0]
    assert fname == "store-1.webp"


# ── producto autocomplete: staff → Choices; non-staff → [] with NO store read ──────
def test_producto_autocomplete_returns_choices_for_staff(cog, monkeypatch):
    rows = {KEY: _snapshot_row(name="Cahuama")}
    monkeypatch.setattr(jinxxy.db, "get_store_snapshot", lambda: dict(rows))
    inter = _medios_interaction([STAFF_ROLE_ID])
    choices = asyncio.run(cog._producto_choices(inter, ""))
    assert len(choices) == 1
    assert choices[0].value == KEY
    assert choices[0].name == "Cahuama"


def test_producto_autocomplete_empty_for_non_staff_no_store_read(cog, monkeypatch):
    called = []
    monkeypatch.setattr(jinxxy.db, "get_store_snapshot",
                        lambda: called.append(1) or {})
    inter = _medios_interaction([OTHER_ROLE_ID])
    choices = asyncio.run(cog._producto_choices(inter, ""))
    assert choices == []                            # CR-01: no Choices for non-staff
    assert called == []                             # and no store read at all


def test_producto_autocomplete_caps_at_25(cog, monkeypatch):
    rows = {f"https://jinxxy.com/nocturna/p{i}": _snapshot_row(
                key=f"https://jinxxy.com/nocturna/p{i}", name=f"P{i}")
            for i in range(40)}
    monkeypatch.setattr(jinxxy.db, "get_store_snapshot", lambda: rows)
    inter = _medios_interaction([STAFF_ROLE_ID])
    choices = asyncio.run(cog._producto_choices(inter, ""))
    assert len(choices) == 25                        # Discord's hard Choice cap


# ── the command calls attach_store_media ONCE with the checkoutUrl + media + desc ──
def test_medios_calls_attach_store_media_once(cog, monkeypatch):
    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp",
                        lambda raw: (b"W", 10, 10))
    attach = AsyncMock(return_value={"committed": True, "commit_sha": "x",
                                     "count": 1, "files": []})
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media", attach)
    inter = _medios_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=_FakeAttachment(),
                             descripcion_es="hola", descripcion_en="hi"))
    attach.assert_awaited_once()
    args = attach.await_args.args
    assert args[0] == KEY                            # matched checkoutUrl
    media = args[1]
    assert len(media) == 1 and media[0][1].endswith(".webp")
    assert args[2] == {"es": "hola", "en": "hi"}


def test_medios_description_omits_missing_locale(cog, monkeypatch):
    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp", lambda raw: (b"W", 1, 1))
    attach = AsyncMock(return_value={"committed": True})
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media", attach)
    inter = _medios_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=_FakeAttachment(),
                             descripcion_es="solo es"))
    # 'en' omitted → 09-04's None-skip preserves any existing en (no wipe on a partial edit)
    assert attach.await_args.args[2] == {"es": "solo es"}


def test_medios_no_description_passes_none(cog, monkeypatch):
    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp", lambda raw: (b"W", 1, 1))
    attach = AsyncMock(return_value={"committed": True})
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media", attach)
    inter = _medios_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=_FakeAttachment()))
    assert attach.await_args.args[2] is None        # images-only edit leaves description alone


# ── staff gate FIRST — non-staff rejected before any attachment read or attach call ─
def test_medios_non_staff_rejected_before_any_work(cog, monkeypatch):
    attach = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media", attach)
    att = _FakeAttachment()
    inter = _medios_interaction([OTHER_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=att))
    assert inter.response.send_message.await_args.args[0] == "Sin permisos."
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True
    inter.response.defer.assert_not_awaited()        # gated before defer
    assert att.reads == 0                             # no attachment bytes were read
    attach.assert_not_awaited()


# ── GitHubPublishError → ephemeral staff reply, never raised (D-05 staff-facing) ────
def test_medios_publish_error_replies_ephemeral(cog, monkeypatch):
    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp", lambda raw: (b"W", 1, 1))
    boom = jinxxy.github_publish.GitHubPublishError("no product matches checkout_url")
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media",
                        AsyncMock(side_effect=boom))
    inter = _medios_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=_FakeAttachment()))
    inter.followup.send.assert_awaited()             # staff-facing reply, not a public post
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True


# ══ 09-10 Task 1 (WR-07): a bad/bomb attachment yields an ephemeral error, not a hang ══
#
# Discord's attachment picker does not restrict content types, so staff can upload a PDF,
# a video or a decompression-bomb image. `optimize_to_webp` calls PIL.Image.open on those
# raw bytes, which raises UnidentifiedImageError / DecompressionBombError / OSError — none of
# them discord.HTTPException or GitHubPublishError. Before this guard the exception propagated
# out of `asyncio.to_thread`, leaving the deferred interaction stuck on "thinking…" with no
# staff feedback and breaking the D-05 one-ephemeral-signal contract.


def test_medios_optimize_error_replies_ephemeral_and_skips_attach(cog, monkeypatch):
    # A non-image / bomb attachment makes the optimizer raise (here UnidentifiedImageError, but
    # the guard is broad on purpose). The invoker must get ONE ephemeral error and attach_store_media
    # must never be reached — the interaction is resolved, not left hanging.
    from PIL import UnidentifiedImageError

    def _boom(raw):
        raise UnidentifiedImageError("cannot identify image file")

    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp", _boom)
    attach = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media", attach)
    inter = _medios_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=_FakeAttachment()))
    inter.followup.send.assert_awaited()             # one ephemeral signal to the invoker
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True
    attach.assert_not_awaited()                      # never commits when optimization failed


def test_medios_bomb_attachment_does_not_raise(cog, monkeypatch):
    # A decompression-bomb attachment (PIL raises DecompressionBombError) must be swallowed into
    # the ephemeral path, never propagate out of the deferred command (T-09-10-01 DoS mitigation).
    from PIL import Image

    def _bomb(raw):
        raise Image.DecompressionBombError("image is too large")

    monkeypatch.setattr(jinxxy.image_optimize, "optimize_to_webp", _bomb)
    monkeypatch.setattr(jinxxy.github_publish, "attach_store_media", AsyncMock())
    inter = _medios_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_medios(cog, inter, producto=KEY, imagen1=_FakeAttachment()))  # must not raise
    inter.followup.send.assert_awaited()
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True


# ══ Plan 09-12: /tienda editar — set a product's staff-owned `editor` (GAP-1) ════════
#
# The Creator API seeds `editor` from /me at creation (D-09); staff had no Discord path to
# CHANGE it, so crediting a creator required a forbidden hand-edit of store.json. `/tienda
# editar` validates the editor string then commits it via `set_store_editor` (09-12 transport),
# matched by checkoutUrl. Staff gate FIRST (T-09-20); validate BEFORE any transport (T-09-21);
# errors are log-only + one ephemeral reply (D-05/T-09-23).


def _editar_interaction(role_ids):
    return types.SimpleNamespace(
        user=_member(role_ids),
        response=types.SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


async def _call_editar(cog, interaction, **kwargs):
    await jinxxy.JinxxyCog.editar.callback(cog, interaction, **kwargs)


# ── staff gate FIRST — non-staff rejected before defer or any transport (T-09-20) ────
def test_editar_non_staff_rejected_before_any_work(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([OTHER_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="Shangri"))
    assert inter.response.send_message.await_args.args[0] == "Sin permisos."
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True
    inter.response.defer.assert_not_awaited()        # gated before defer
    setter.assert_not_awaited()


# ── valid editor → set_store_editor called ONCE with the cleaned (stripped) value ────
def test_editar_valid_editor_calls_set_store_editor_once_cleaned(cog, monkeypatch):
    setter = AsyncMock(return_value={"committed": True, "commit_sha": "x"})
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="  Shangri  "))
    setter.assert_awaited_once()
    args = setter.await_args.args
    assert args[0] == KEY
    assert args[1] == "Shangri"                      # stripped before the write
    inter.response.defer.assert_awaited_once()
    inter.followup.send.assert_awaited()
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True


# ── invalid editor branches → ephemeral message, transport NEVER called (T-09-21) ────
def test_editar_empty_after_strip_rejected(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="   "))
    setter.assert_not_awaited()                      # no commit on invalid input
    inter.response.send_message.assert_awaited()     # ephemeral rejection (before defer)
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True
    inter.response.defer.assert_not_awaited()


def test_editar_over_length_rejected(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="a" * 101))
    setter.assert_not_awaited()
    inter.response.send_message.assert_awaited()
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True


def test_editar_at_length_cap_is_accepted(cog, monkeypatch):
    # exactly 100 chars is valid (the cap is > 100 rejects, not >= 100)
    setter = AsyncMock(return_value={"committed": True})
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="a" * 100))
    setter.assert_awaited_once()


def test_editar_newline_char_rejected(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="Shan\ngri"))
    setter.assert_not_awaited()
    inter.response.send_message.assert_awaited()
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True


def test_editar_control_char_rejected(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", setter)
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="Shan\x07gri"))
    setter.assert_not_awaited()
    inter.response.send_message.assert_awaited()
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True


# ── GitHubPublishError → one ephemeral reply, NEVER a public post (D-05/T-09-23) ─────
def test_editar_publish_error_replies_ephemeral_never_announced(cog, monkeypatch):
    ch = _channel()
    cog.bot = _bot_with_channel(ch)
    boom = jinxxy.github_publish.GitHubPublishError("no product matches checkout_url")
    monkeypatch.setattr(jinxxy.github_publish, "set_store_editor", AsyncMock(side_effect=boom))
    inter = _editar_interaction([STAFF_ROLE_ID])
    asyncio.run(_call_editar(cog, inter, producto=KEY, editor="Shangri"))
    inter.response.defer.assert_awaited_once()
    inter.followup.send.assert_awaited_once()        # ephemeral reply to the invoker
    assert inter.followup.send.await_args.kwargs.get("ephemeral") is True
    ch.send.assert_not_awaited()                     # nothing posted publicly (D-05)


# ── editar autocomplete reuses _producto_choices → [] for a non-staff caller ─────────
def test_editar_autocomplete_empty_for_non_staff(cog, monkeypatch):
    called = []
    monkeypatch.setattr(jinxxy.db, "get_store_snapshot",
                        lambda: called.append(1) or {})
    inter = _editar_interaction([OTHER_ROLE_ID])
    choices = asyncio.run(cog._editar_producto_autocomplete(inter, ""))
    assert choices == []                             # non-staff gets no Choices (T-09-20)
    assert called == []                              # and no store read at all


def test_editar_autocomplete_returns_choices_for_staff(cog, monkeypatch):
    rows = {KEY: _snapshot_row(name="Cahuama")}
    monkeypatch.setattr(jinxxy.db, "get_store_snapshot", lambda: dict(rows))
    inter = _editar_interaction([STAFF_ROLE_ID])
    choices = asyncio.run(cog._editar_producto_autocomplete(inter, ""))
    assert len(choices) == 1
    assert choices[0].value == KEY
