"""Behaviour tests for the D-11 gallery editor-credit + D-04 NSFW flag (Fase 10, EDIT-08).

Two halves, both mocked exactly like ``test_github_publish_editors.py`` /
``test_gallery_cog.py`` (no pytest-asyncio):

  * TRANSPORT — ``core.github_publish.publish_message`` gains an OPTIONAL ``editor`` slug
    (D-11/D-12) + ``nsfw`` flag (D-04) written into the gallery.json entry, and a new
    ``set_gallery_editor(message_id, editor=, nsfw=)`` post-✅ credit write path that updates
    the already-published entries for a message (keyed by the D-14 ``{msgID}`` filename
    segment) WITHOUT re-uploading images. ``requests.get/post/patch`` are monkeypatched with a
    programmable ``FakeGitHub`` serving the gallery ARRAY; the async API is driven with
    ``asyncio.run``.
  * COG — the ephemeral slug-autocomplete follow-up (chosen affordance, RESEARCH Open Q1):
    ``GalleryCog._do_creditar`` is ``_is_staff``-gated (T-10-06-01) and validates the chosen
    slug against the live ``editors.json`` slug set (D-12 exact match, T-10-06-02) before it
    ever calls the transport. Discord objects are ``types.SimpleNamespace`` + ``AsyncMock``.

Contract asserted here:
  * publishing WITH a credited slug writes ``entry.editor == "<slug>"``
  * publishing WITHOUT a credit omits ``editor`` (optional field, no BOT-01/02 regression)
  * flagging NSFW writes ``entry.nsfw == True``; an unflagged publish OMITS the field (SFW)
  * ``set_gallery_editor`` credits an already-published message's entries; other messages
    stay byte-identical; no matching entries / an unchanged credit is a no-op (no commit)
  * the credit affordance is staff-gated; an unknown slug is rejected against editors.json
  * the credit commit message never interpolates the raw editor slug into free text
"""

import asyncio
import base64
import json
import types
from unittest.mock import AsyncMock

import pytest

import config
from cogs import gallery
from cogs.gallery import GalleryCog
from core import github_publish


# ── programmable fake GitHub Git Data API (gallery.json array body) ──────────────────
class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload

    def json(self):
        return self._payload

    @property
    def text(self):
        return json.dumps(self._payload)


class FakeGitHub:
    """Records every HTTP call and answers each Git Data API endpoint with canned JSON.

    Serves the current gallery ARRAY on the ``/contents/`` endpoint. Mirrors the harness in
    ``test_github_publish_editors.py`` (gallery variant).
    """

    def __init__(self, base_gallery, patch_statuses=None, blob_shas=None):
        self.base_gallery = base_gallery
        self.calls = []
        self.timeouts = []
        self.ref_get_count = 0
        self.blob_payloads = []
        self.tree_payloads = []
        self.commit_payloads = []
        self.patch_payloads = []
        self._patch_statuses = list(patch_statuses or [200])
        self._blob_shas = list(blob_shas or [])
        self._blob_i = 0

    def _b64_gallery(self):
        raw = json.dumps(self.base_gallery).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    def get(self, url, headers=None, **kw):
        self.calls.append(("GET", url, headers, None))
        self.timeouts.append(kw.get("timeout"))
        if "/git/ref/heads/" in url:
            self.ref_get_count += 1
            return _Resp(200, {"object": {"sha": "PARENT_SHA"}})
        if "/git/commits/" in url:
            return _Resp(200, {"tree": {"sha": "BASE_TREE_SHA"}})
        if "/contents/" in url:
            return _Resp(200, {"content": self._b64_gallery(), "encoding": "base64"})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers=None, json=None, **kw):
        self.calls.append(("POST", url, headers, json))
        self.timeouts.append(kw.get("timeout"))
        if url.endswith("/git/blobs"):
            self.blob_payloads.append(json)
            sha = self._blob_shas[self._blob_i] if self._blob_i < len(self._blob_shas) \
                else f"BLOB_SHA_{self._blob_i}"
            self._blob_i += 1
            return _Resp(201, {"sha": sha})
        if url.endswith("/git/trees"):
            self.tree_payloads.append(json)
            return _Resp(201, {"sha": "NEW_TREE_SHA"})
        if url.endswith("/git/commits"):
            self.commit_payloads.append(json)
            return _Resp(201, {"sha": "NEW_COMMIT_SHA"})
        raise AssertionError(f"unexpected POST {url}")

    def patch(self, url, headers=None, json=None, **kw):
        self.calls.append(("PATCH", url, headers, json))
        self.timeouts.append(kw.get("timeout"))
        self.patch_payloads.append(json)
        status = self._patch_statuses.pop(0) if self._patch_statuses else 200
        return _Resp(status, {"object": {"sha": "NEW_COMMIT_SHA"}})

    def commits_posted(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/git/commits")]

    def ref_patches(self):
        return [c for c in self.calls if c[0] == "PATCH"]

    def tree_entries(self):
        return self.tree_payloads[-1]["tree"]

    def gallery_tree_entry(self):
        return next(t for t in self.tree_entries()
                    if t["path"] == config.WEBSITE_GALLERY_JSON)

    def new_gallery_array(self):
        return json.loads(self.gallery_tree_entry()["content"])


FAKE_PAT = "ghp_faketoken_should_never_be_logged_123456"


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(config, "GITHUB_PAT", FAKE_PAT)
    monkeypatch.setattr(config, "WEBSITE_REPO", "Shangrii/Nocturna-Avatars")
    monkeypatch.setattr(config, "WEBSITE_BRANCH", "revamp")
    monkeypatch.setattr(config, "WEBSITE_GALLERY_JSON", "src/data/gallery.json")
    monkeypatch.setattr(config, "WEBSITE_IMAGE_DIR", "public/gallery")
    monkeypatch.setattr(github_publish.time, "sleep", lambda *_a, **_k: None)

    def install(fake):
        monkeypatch.setattr(github_publish.requests, "get", fake.get)
        monkeypatch.setattr(github_publish.requests, "post", fake.post)
        monkeypatch.setattr(github_publish.requests, "patch", fake.patch)
        return fake

    return install


# ── data builders ────────────────────────────────────────────────────────────────────
def _entry(file, width=800, height=600, date="2026-07-04T00:00:00.000Z", **extra):
    e = {"file": file, "width": width, "height": height, "date": date}
    e.update(extra)
    return e


def _pub_entries(caption="", filename="20260704-555-1.webp"):
    # (raw, width, height, filename, caption) — the publish_message tuple shape.
    return [(b"webp-bytes", 800, 600, filename, caption)]


# ── publish_message: optional editor + nsfw (D-11/D-04) ──────────────────────────────
def test_publish_message_with_editor_writes_entry_editor(wire):
    fake = wire(FakeGitHub(base_gallery=[]))
    asyncio.run(github_publish.publish_message(555, _pub_entries(), date="D", editor="aria"))
    arr = fake.new_gallery_array()
    assert arr[-1]["editor"] == "aria"


def test_publish_message_without_credit_omits_editor_and_nsfw(wire):
    fake = wire(FakeGitHub(base_gallery=[]))
    result = asyncio.run(github_publish.publish_message(555, _pub_entries(), date="D"))
    entry = fake.new_gallery_array()[-1]
    assert "editor" not in entry            # optional — omitted when uncredited
    assert "nsfw" not in entry              # missing = SFW (historical shape preserved)
    assert entry["file"] == "20260704-555-1.webp"
    assert result["committed"] is True      # still succeeds (no BOT-01/02 regression)


def test_publish_message_nsfw_true_writes_flag(wire):
    fake = wire(FakeGitHub(base_gallery=[]))
    asyncio.run(github_publish.publish_message(555, _pub_entries(), date="D", nsfw=True))
    assert fake.new_gallery_array()[-1]["nsfw"] is True


def test_publish_message_nsfw_false_omits_flag(wire):
    fake = wire(FakeGitHub(base_gallery=[]))
    asyncio.run(github_publish.publish_message(556, _pub_entries(), date="D", nsfw=False))
    assert "nsfw" not in fake.new_gallery_array()[-1]


def test_publish_message_keeps_phase4_entry_shape_with_credit(wire):
    fake = wire(FakeGitHub(base_gallery=[]))
    asyncio.run(github_publish.publish_message(
        555, _pub_entries(caption="Luna fit"), date="2026-07-04T00:00:00.000Z",
        editor="aria", nsfw=True))
    entry = fake.new_gallery_array()[-1]
    assert entry == {
        "file": "20260704-555-1.webp", "caption": "Luna fit",
        "width": 800, "height": 600, "date": "2026-07-04T00:00:00.000Z",
        "editor": "aria", "nsfw": True,
    }


# ── set_gallery_editor: post-✅ credit write path (keyed by message id) ────────────────
def test_set_gallery_editor_credits_matching_entries_only(wire):
    base = [_entry("20260704-555-1.webp"), _entry("20260704-555-2.webp"),
            _entry("20260704-999-1.webp")]
    fake = wire(FakeGitHub(base_gallery=base))
    result = asyncio.run(github_publish.set_gallery_editor(555, editor="aria"))
    by_file = {e["file"]: e for e in fake.new_gallery_array()}
    assert by_file["20260704-555-1.webp"]["editor"] == "aria"
    assert by_file["20260704-555-2.webp"]["editor"] == "aria"
    assert "editor" not in by_file["20260704-999-1.webp"]   # other message untouched
    assert result["committed"] is True
    assert result["count"] == 2


def test_set_gallery_editor_writes_nsfw_flag(wire):
    fake = wire(FakeGitHub(base_gallery=[_entry("20260704-555-1.webp")]))
    asyncio.run(github_publish.set_gallery_editor(555, editor="aria", nsfw=True))
    entry = fake.new_gallery_array()[0]
    assert entry["editor"] == "aria" and entry["nsfw"] is True


def test_set_gallery_editor_no_matching_entries_is_noop(wire):
    fake = wire(FakeGitHub(base_gallery=[_entry("20260704-999-1.webp")]))
    result = asyncio.run(github_publish.set_gallery_editor(555, editor="aria"))
    assert result["committed"] is False
    assert fake.commits_posted() == []
    assert fake.ref_patches() == []


def test_set_gallery_editor_unchanged_credit_is_noop(wire):
    fake = wire(FakeGitHub(base_gallery=[_entry("20260704-555-1.webp", editor="aria")]))
    result = asyncio.run(github_publish.set_gallery_editor(555, editor="aria"))
    assert result["committed"] is False
    assert fake.ref_patches() == []


def test_set_gallery_editor_commit_message_is_id_only_no_slug_text(wire):
    fake = wire(FakeGitHub(base_gallery=[_entry("20260704-555-1.webp")]))
    asyncio.run(github_publish.set_gallery_editor(555, editor="SENSITIVE-slug"))
    msg = fake.commit_payloads[0]["message"]
    assert "SENSITIVE-slug" not in msg
    assert "555" in msg


def test_set_gallery_editor_ignores_sample_named_entries(wire):
    # A non-bot filename never parses to a message id, so it is never credited (D-14).
    fake = wire(FakeGitHub(base_gallery=[_entry("nocturna-sample-01.webp")]))
    result = asyncio.run(github_publish.set_gallery_editor(555, editor="aria"))
    assert result["committed"] is False


# ── COG: ephemeral slug-autocomplete follow-up (staff gate + slug validation) ─────────
STAFF_ROLE_ID = 111
OTHER_ROLE_ID = 222


def _member(role_ids, is_bot=False):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids], bot=is_bot)


def _interaction(role_ids):
    return types.SimpleNamespace(
        user=_member(role_ids),
        response=types.SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


@pytest.fixture(autouse=True)
def _credit_config(monkeypatch):
    monkeypatch.setattr(config, "GALLERY_STAFF_ROLE_IDS", [STAFF_ROLE_ID], raising=False)


@pytest.fixture
def cog(monkeypatch):
    monkeypatch.setattr(gallery.db, "init_gallery_state", lambda: None)
    return GalleryCog(bot=types.SimpleNamespace())


def test_editor_choices_empty_for_non_staff(cog, monkeypatch):
    monkeypatch.setattr(gallery.github_publish, "_fetch_json",
                        lambda *a, **k: [{"slug": "aria"}])
    result = asyncio.run(cog._editor_choices(_interaction([OTHER_ROLE_ID]), ""))
    assert result == []


def test_editor_choices_returns_filtered_slug_choices_for_staff(cog, monkeypatch):
    monkeypatch.setattr(gallery.github_publish, "_fetch_json",
                        lambda *a, **k: [{"slug": "aria"}, {"slug": "bob"}])
    result = asyncio.run(cog._editor_choices(_interaction([STAFF_ROLE_ID]), "ar"))
    assert [c.value for c in result] == ["aria"]


def test_creditar_non_staff_denied(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "set_gallery_editor", setter)
    interaction = _interaction([OTHER_ROLE_ID])
    asyncio.run(cog._do_creditar(interaction, "555", "aria", False))
    interaction.response.send_message.assert_awaited_once()
    setter.assert_not_awaited()


def test_creditar_invalid_message_id_rejected_before_transport(cog, monkeypatch):
    setter = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "set_gallery_editor", setter)
    interaction = _interaction([STAFF_ROLE_ID])
    asyncio.run(cog._do_creditar(interaction, "not-an-id", "aria", False))
    setter.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()


def test_creditar_unknown_slug_rejected(cog, monkeypatch):
    monkeypatch.setattr(gallery.github_publish, "_fetch_json",
                        lambda *a, **k: [{"slug": "aria"}])
    setter = AsyncMock()
    monkeypatch.setattr(gallery.github_publish, "set_gallery_editor", setter)
    interaction = _interaction([STAFF_ROLE_ID])
    asyncio.run(cog._do_creditar(interaction, "555", "ghost", False))
    setter.assert_not_awaited()                       # D-12: unknown slug never written
    interaction.followup.send.assert_awaited()


def test_creditar_valid_slug_credits_with_nsfw(cog, monkeypatch):
    monkeypatch.setattr(gallery.github_publish, "_fetch_json",
                        lambda *a, **k: [{"slug": "aria"}])
    setter = AsyncMock(return_value={"committed": True, "count": 1})
    monkeypatch.setattr(gallery.github_publish, "set_gallery_editor", setter)
    interaction = _interaction([STAFF_ROLE_ID])
    asyncio.run(cog._do_creditar(interaction, "555", "aria", True))
    setter.assert_awaited_once_with(555, editor="aria", nsfw=True)
