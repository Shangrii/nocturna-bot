"""Behaviour tests for the editors cross-repo commit transport (Fase 10, EDIT-06/EDIT-07).

These pin the contract of ``core.github_publish.sync_editors`` / ``unpublish_editor`` —
the editor-page variant of the reviews/gallery transport. ``editors.json`` is a top-level
ARRAY (like ``gallery.json``/``reviews.json``, D-18), so these reuse the same generic
``_fetch_json`` array reader + ``_commit_with_retry`` atomic blobs->tree->commit->ref core;
NO new commit path is invented (the gallery/store/reviews transports stay byte-for-byte
unchanged — asserted by the untouched ``test_github_publish.py`` suite).

Everything HTTP is mocked exactly like ``test_store_publish.py`` / ``test_github_publish.py``:
``requests.get/post/patch`` are monkeypatched with a programmable fake that records every
call and returns canned GitHub JSON per endpoint. The async ``sync_editors`` /
``unpublish_editor`` are driven with ``asyncio.run`` (no pytest-asyncio dependency needed).

Contract asserted here:
  * D-06: sync_editors commits editors.json + uploaded image blobs in ONE atomic commit,
    upserting THIS editor by ``discordId`` into the FRESHLY fetched array
  * Pitfall 6: a concurrent save (409/422 stale-ref retry) re-fetches and the upsert still
    targets the fresh array — a concurrent editor entry is merged, never clobbered
  * D-17: image blobs land under ``public/editors/<slug>/`` in the SAME tree as editors.json
  * serialization is ensure_ascii=False + 2-space indent (ES/EN text stays readable)
  * commit messages use a FIXED template (never interpolate raw editor text) — T-10-05-02
  * unpublish_editor flips ``published`` to false, leaving the entry (and images) in place
  * unpublish_editor on an unknown / already-unpublished editor is a no-op (no commit)
  * T-10-05-02: the PAT rides in an ``Authorization: Bearer`` header and never reaches logs
"""

import asyncio
import base64
import json
import logging

import pytest

import config
from core import github_publish


# ── programmable fake GitHub Git Data API (editors.json array body + image blobs) ────
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

    Serves the current editors ARRAY on the ``/contents/`` endpoint. ``patch_statuses`` is
    a queue of status codes returned by successive ref PATCHes (default ``[200]``) so tests
    can inject a 422 stale-ref conflict then a 200. ``contents_sequence`` (optional) serves a
    DIFFERENT array on each successive ``/contents/`` GET so a concurrent-save race can be
    simulated across a retry (Pitfall 6).
    """

    def __init__(self, base_editors, patch_statuses=None, blob_shas=None,
                 contents_sequence=None):
        self.base_editors = base_editors
        self._contents_sequence = list(contents_sequence) if contents_sequence else None
        self.calls = []            # (method, url, headers, json_payload)
        self.timeouts = []         # the timeout kwarg of every call
        self.ref_get_count = 0
        self.blob_payloads = []
        self.tree_payloads = []
        self.commit_payloads = []
        self.patch_payloads = []
        self._patch_statuses = list(patch_statuses or [200])
        self._blob_shas = list(blob_shas or [])
        self._blob_i = 0

    def _current_editors(self):
        if self._contents_sequence:
            if len(self._contents_sequence) > 1:
                return self._contents_sequence.pop(0)
            return self._contents_sequence[0]
        return self.base_editors

    def _b64_editors(self):
        raw = json.dumps(self._current_editors()).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    # -- request verbs ------------------------------------------------------------
    def get(self, url, headers=None, **kw):
        self.calls.append(("GET", url, headers, None))
        self.timeouts.append(kw.get("timeout"))
        if "/git/ref/heads/" in url:
            self.ref_get_count += 1
            return _Resp(200, {"object": {"sha": "PARENT_SHA"}})
        if "/git/commits/" in url:
            return _Resp(200, {"tree": {"sha": "BASE_TREE_SHA"}})
        if "/contents/" in url:
            return _Resp(200, {"content": self._b64_editors(), "encoding": "base64"})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers=None, json=None, **kw):
        self.calls.append(("POST", url, headers, json))
        self.timeouts.append(kw.get("timeout"))
        if url.endswith("/git/blobs"):
            self.blob_payloads.append(json)
            if self._blob_i < len(self._blob_shas):
                sha = self._blob_shas[self._blob_i]
            else:
                sha = f"BLOB_SHA_{self._blob_i}"
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

    # -- assertion helpers --------------------------------------------------------
    def commits_posted(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/git/commits")]

    def ref_patches(self):
        return [c for c in self.calls if c[0] == "PATCH"]

    def tree_entries(self):
        return self.tree_payloads[0]["tree"]

    def editors_tree_entry(self):
        return next(t for t in self.tree_entries() if t["path"] == config.WEBSITE_EDITORS_JSON)

    def blob_tree_entries(self):
        return [t for t in self.tree_entries() if "sha" in t]

    def new_editors_array(self):
        return json.loads(self.editors_tree_entry()["content"])


FAKE_PAT = "ghp_faketoken_should_never_be_logged_123456"


@pytest.fixture
def wire(monkeypatch):
    """Install the fake HTTP layer + deterministic config, silence backoff sleeps.

    Returns an ``install(fake)`` callable so each test can build its own FakeGitHub.
    """
    monkeypatch.setattr(config, "GITHUB_PAT", FAKE_PAT)
    monkeypatch.setattr(config, "WEBSITE_REPO", "Shangrii/Nocturna-Avatars")
    monkeypatch.setattr(config, "WEBSITE_BRANCH", "revamp")
    monkeypatch.setattr(config, "WEBSITE_EDITORS_JSON", "src/data/editors.json")
    monkeypatch.setattr(config, "WEBSITE_EDITORS_IMAGE_DIR", "public/editors")
    # never wait on retry backoff during tests
    monkeypatch.setattr(github_publish.time, "sleep", lambda *_a, **_k: None)

    def install(fake):
        monkeypatch.setattr(github_publish.requests, "get", fake.get)
        monkeypatch.setattr(github_publish.requests, "post", fake.post)
        monkeypatch.setattr(github_publish.requests, "patch", fake.patch)
        return fake

    return install


# ── data builders ──────────────────────────────────────────────────────────────────
def _editor(slug="aria", discord_id="123456789012345678", published=True, name="Aria",
            **extra):
    e = {
        "slug": slug,
        "discordId": discord_id,
        "published": published,
        "name": name,
        "avatar": f"/editors/{slug}/avatar.webp",
        "tagline": {"es": "Editora de avatares", "en": "Avatar editor"},
        "links": [],
        "blocks": [],
    }
    e.update(extra)
    return e


# ── sync_editors: upsert-by-discordId (append + replace) ─────────────────────────────
def test_sync_editors_appends_new_editor_preserving_existing(wire):
    # A new editor whose discordId is absent is appended; existing entries preserved.
    existing = _editor(slug="bob", discord_id="BBB", name="Bob")
    fake = wire(FakeGitHub(base_editors=[existing]))
    new = _editor(slug="aria", discord_id="AAA", name="Aria")

    result = asyncio.run(github_publish.sync_editors(new))

    arr = fake.new_editors_array()
    by_id = {e["discordId"]: e for e in arr}
    assert set(by_id) == {"AAA", "BBB"}                     # both present
    assert by_id["BBB"] == existing                         # existing entry byte-identical
    assert by_id["AAA"]["slug"] == "aria"
    assert result["committed"] is True


def test_sync_editors_upsert_replaces_only_matching_discordId(wire):
    # An existing discordId is REPLACED (upsert); every other entry stays byte-identical.
    other = _editor(slug="bob", discord_id="BBB", name="Bob")
    old = _editor(slug="aria", discord_id="AAA", name="Aria Vieja")
    fake = wire(FakeGitHub(base_editors=[other, old]))
    updated = _editor(slug="aria", discord_id="AAA", name="Aria Nueva",
                      tagline={"es": "Nueva bio", "en": "New bio"})

    asyncio.run(github_publish.sync_editors(updated))

    arr = fake.new_editors_array()
    by_id = {e["discordId"]: e for e in arr}
    assert len(arr) == 2                                    # no duplicate for AAA
    assert by_id["AAA"]["name"] == "Aria Nueva"            # replaced
    assert by_id["AAA"]["tagline"] == {"es": "Nueva bio", "en": "New bio"}
    assert by_id["BBB"] == other                           # untouched sibling byte-identical


def test_sync_editors_stale_ref_retry_upsert_targets_fresh_array(wire):
    # Pitfall 6: on a 422 stale-ref first attempt, the retry re-fetches — a CONCURRENT
    # editor entry added between attempts must survive (merged, never clobbered).
    concurrent = _editor(slug="bob", discord_id="BBB", name="Bob")
    fake = wire(FakeGitHub(
        base_editors=[],
        # attempt 0 sees [], attempt 1 (after 422) sees a concurrently-added editor
        contents_sequence=[[], [concurrent]],
        patch_statuses=[422, 200]))
    mine = _editor(slug="aria", discord_id="AAA", name="Aria")

    result = asyncio.run(github_publish.sync_editors(mine))

    assert fake.ref_get_count >= 2                          # re-fetched the ref
    arr = fake.new_editors_array()
    ids = {e["discordId"] for e in arr}
    assert ids == {"AAA", "BBB"}                            # concurrent entry NOT lost
    assert result["committed"] is True


# ── sync_editors: image blobs + editors.json in ONE commit (D-17) ────────────────────
def test_sync_editors_images_and_json_land_in_one_commit(wire):
    fake = wire(FakeGitHub(base_editors=[], blob_shas=["BLOB_A", "BLOB_B"]))
    entry = _editor(slug="aria", discord_id="AAA")
    images = [("avatar.webp", b"avatar-bytes"), ("shot.webp", b"shot-bytes")]

    result = asyncio.run(github_publish.sync_editors(entry, images))

    # ONE commit, ONE ref patch
    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1
    # two image blobs under public/editors/<slug>/ + the editors.json blob, one tree
    tree = fake.tree_entries()
    imgs = [t for t in tree if t["path"].startswith("public/editors/")]
    assert {t["path"] for t in imgs} == {
        "public/editors/aria/avatar.webp", "public/editors/aria/shot.webp"}
    for t in imgs:
        assert t["mode"] == "100644" and t["type"] == "blob"
        assert "sha" in t and "content" not in t           # image by blob sha
    assert {t["sha"] for t in imgs} == {"BLOB_A", "BLOB_B"}
    ed = fake.editors_tree_entry()
    assert "content" in ed and "sha" not in ed             # json by inline content
    assert result["committed"] is True
    assert set(result["files"]) == {"avatar.webp", "shot.webp"}


def test_sync_editors_no_images_writes_only_the_json_blob(wire):
    fake = wire(FakeGitHub(base_editors=[]))

    asyncio.run(github_publish.sync_editors(_editor()))

    tree = fake.tree_entries()
    assert len(tree) == 1
    assert tree[0]["path"] == config.WEBSITE_EDITORS_JSON
    assert fake.blob_tree_entries() == []


def test_sync_editors_blob_is_base64_of_the_image_bytes(wire):
    fake = wire(FakeGitHub(base_editors=[]))

    asyncio.run(github_publish.sync_editors(
        _editor(slug="aria"), [("avatar.webp", b"avatar-raw-bytes")]))

    first_blob = fake.blob_payloads[0]
    assert first_blob["encoding"] == "base64"
    assert base64.b64decode(first_blob["content"]) == b"avatar-raw-bytes"


# ── sync_editors: serialization + fixed commit message ───────────────────────────────
def test_sync_editors_serializes_unescaped_and_indented(wire):
    fake = wire(FakeGitHub(base_editors=[]))

    asyncio.run(github_publish.sync_editors(
        _editor(slug="aria", name="Aria Diseñadora",
                tagline={"es": "Edición de avatares", "en": "Avatar editing"})))

    content = fake.editors_tree_entry()["content"]
    assert "Aria Diseñadora" in content                    # ensure_ascii=False
    assert "\n  " in content                               # indent=2


def test_sync_editors_commit_message_is_fixed_template_no_editor_text(wire):
    # T-10-05-02: the commit message references the slug ONLY; raw editor text (name/bio)
    # is NEVER interpolated into the message.
    fake = wire(FakeGitHub(base_editors=[]))
    secret = "SENSITIVE_BIO_TEXT_xyz"

    asyncio.run(github_publish.sync_editors(
        _editor(slug="aria", name=secret, tagline={"es": secret, "en": secret})))

    msg = fake.commit_payloads[0]["message"]
    assert msg == "editors: publish aria"
    assert secret not in msg


def test_sync_editors_custom_message_override(wire):
    fake = wire(FakeGitHub(base_editors=[]))

    asyncio.run(github_publish.sync_editors(
        _editor(slug="aria"), message="editors: custom message"))

    assert fake.commit_payloads[0]["message"] == "editors: custom message"


# ── sync_editors: secrets hygiene (PAT only in the Authorization header) ──────────────
def test_sync_editors_authorization_header_is_bearer_pat_on_every_call(wire):
    fake = wire(FakeGitHub(base_editors=[]))

    result = asyncio.run(github_publish.sync_editors(
        _editor(slug="aria"), [("avatar.webp", b"x")]))

    assert fake.calls, "no HTTP calls were made"
    for method, url, headers, _payload in fake.calls:
        assert headers is not None, f"{method} {url} carried no headers"
        assert headers.get("Authorization") == f"Bearer {FAKE_PAT}"
        assert headers.get("Accept") == "application/vnd.github+json"
    # the PAT never appears in the returned result dict
    assert FAKE_PAT not in json.dumps(result)


def test_sync_editors_pat_is_never_written_to_logs(wire, caplog):
    fake = wire(FakeGitHub(base_editors=[]))

    with caplog.at_level(logging.DEBUG):
        asyncio.run(github_publish.sync_editors(
            _editor(slug="aria"), [("avatar.webp", b"x")]))

    assert FAKE_PAT not in caplog.text                     # T-10-05-02


def test_sync_editors_every_http_call_carries_an_explicit_timeout(wire):
    fake = wire(FakeGitHub(base_editors=[]))

    asyncio.run(github_publish.sync_editors(
        _editor(slug="aria"), [("avatar.webp", b"x")]))

    assert fake.timeouts, "no HTTP calls were recorded"
    assert all(t not in (None, 0) for t in fake.timeouts)
