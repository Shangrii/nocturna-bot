"""Behaviour tests for the atomic cross-repo commit transport (BOT-04).

These pin the contract of ``core.github_publish`` — the module that commits image
blobs + ``gallery.json`` (publish) or deletes a message's files + rewrites
``gallery.json`` (removal) as ONE commit against the website repo via the GitHub
Git Data API (blobs -> tree -> commit -> ref).

Everything HTTP is mocked: ``requests.get/post/patch`` are monkeypatched with a
programmable fake that records every call and returns canned GitHub JSON per
endpoint. The async ``publish_message`` / ``remove_message`` are driven with
``asyncio.run`` (no pytest-asyncio dependency needed).

Contract asserted here:
  * D-16: exactly ONE ``/git/commits`` POST + ONE ref PATCH per publish (atomic)
  * a publish tree holds one blob-by-sha per image + gallery.json-by-content
  * gallery.json is APPENDED to (publish), caption key OMITTED for empty captions,
    serialized ensure_ascii=False + 2-space indent (Phase 4 shape)
  * D-17: commit messages ``gallery: publish/remove N photos (discord msg <id>)``
  * D-14: removal is stateless — files derived from the exact ``{msgID}`` filename
    segment (split on '-'), never a naive substring; only matches are sha:null-deleted
  * a no-match removal is a no-op (never an empty commit)
  * T-05-04: the PAT rides in an ``Authorization: Bearer`` header and never reaches logs
  * D-18: a 422 on the ref PATCH re-fetches the ref and retries with backoff
"""

import asyncio
import base64
import json
import logging

import pytest
import requests

import config
from core import github_publish


# ── programmable fake GitHub Git Data API ─────────────────────────────────────────
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

    ``patch_statuses`` is a queue of status codes returned by successive ref PATCHes
    (default ``[200]``) so tests can inject a 422 stale-ref conflict then a 200.
    """

    def __init__(self, base_gallery, patch_statuses=None, blob_shas=None):
        self.base_gallery = base_gallery
        self.calls = []            # (method, url, headers, json_payload)
        self.timeouts = []         # the timeout kwarg of every call (CR-02)
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
            return _Resp(200, {"content": self._b64_gallery(), "encoding": "base64"})
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

    def gallery_tree_entry(self):
        return next(t for t in self.tree_entries() if t["path"] == config.WEBSITE_GALLERY_JSON)

    def new_gallery_array(self):
        return json.loads(self.gallery_tree_entry()["content"])


FAKE_PAT = "ghp_faketoken_should_never_be_logged_123456"


@pytest.fixture
def wire(monkeypatch):
    """Install the fake HTTP layer + deterministic config, silence backoff sleeps.

    Returns an ``install(fake)`` callable so each test can build its own FakeGitHub.
    """
    monkeypatch.setattr(config, "GITHUB_PAT", FAKE_PAT)
    monkeypatch.setattr(config, "WEBSITE_REPO", "Shangrii/Nocturna-Avatars")
    monkeypatch.setattr(config, "WEBSITE_BRANCH", "revamp")
    monkeypatch.setattr(config, "WEBSITE_GALLERY_JSON", "src/data/gallery.json")
    monkeypatch.setattr(config, "WEBSITE_IMAGE_DIR", "public/gallery")
    # never wait on retry backoff during tests
    monkeypatch.setattr(github_publish.time, "sleep", lambda *_a, **_k: None)

    def install(fake):
        monkeypatch.setattr(github_publish.requests, "get", fake.get)
        monkeypatch.setattr(github_publish.requests, "post", fake.post)
        monkeypatch.setattr(github_publish.requests, "patch", fake.patch)
        return fake

    return install


def _publish_entries():
    """Two images for message 987654321: one captioned, one caption-less."""
    return [
        (b"webp-bytes-image-1", 1600, 2000, "20260703-987654321-1.webp", "Luna — full outfit + toggles"),
        (b"webp-bytes-image-2", 1920, 1280, "20260703-987654321-2.webp", ""),
    ]


# ── publish: atomicity + tree shape ───────────────────────────────────────────────
def test_publish_makes_exactly_one_commit_and_one_ref_patch(wire):
    fake = wire(FakeGitHub(base_gallery=[{"file": "old.webp", "width": 10, "height": 10, "date": "D0"}]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert len(fake.commits_posted()) == 1     # D-16: never two commits
    assert len(fake.ref_patches()) == 1


def test_publish_tree_has_image_blobs_by_sha_plus_gallery_json_by_content(wire):
    fake = wire(FakeGitHub(base_gallery=[], blob_shas=["BLOB_A", "BLOB_B"]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    tree = fake.tree_entries()
    assert len(tree) == 3

    imgs = [t for t in tree if t["path"].startswith("public/gallery/")]
    assert len(imgs) == 2
    for t in imgs:
        assert t["mode"] == "100644" and t["type"] == "blob"
        assert "sha" in t and "content" not in t   # image referenced by blob sha
    assert {t["sha"] for t in imgs} == {"BLOB_A", "BLOB_B"}

    gal = [t for t in tree if t["path"] == config.WEBSITE_GALLERY_JSON]
    assert len(gal) == 1
    assert "content" in gal[0] and "sha" not in gal[0]   # json by inline content


def test_publish_uses_base_tree_and_parent_from_the_current_ref(wire):
    fake = wire(FakeGitHub(base_gallery=[]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert fake.tree_payloads[0]["base_tree"] == "BASE_TREE_SHA"
    commit = fake.commit_payloads[0]
    assert commit["parents"] == ["PARENT_SHA"]
    assert commit["tree"] == "NEW_TREE_SHA"
    assert fake.patch_payloads[0]["sha"] == "NEW_COMMIT_SHA"


def test_publish_blob_is_base64_of_the_webp_bytes(wire):
    fake = wire(FakeGitHub(base_gallery=[]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    first_blob = fake.blob_payloads[0]
    assert first_blob["encoding"] == "base64"
    assert base64.b64decode(first_blob["content"]) == b"webp-bytes-image-1"


# ── publish: gallery.json append + caption + serialization ────────────────────────
def test_publish_appends_entries_preserving_the_phase4_shape(wire):
    base = [{"file": "old.webp", "width": 10, "height": 10, "date": "D0"}]
    fake = wire(FakeGitHub(base_gallery=base))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    arr = fake.new_gallery_array()
    assert len(arr) == 3                                   # base + 2 appended
    by_file = {e["file"]: e for e in arr}
    assert "old.webp" in by_file                           # base entry preserved

    e1 = by_file["20260703-987654321-1.webp"]
    assert e1["caption"] == "Luna — full outfit + toggles"
    assert e1["width"] == 1600 and e1["height"] == 2000
    assert e1["date"] == "2026-07-03T18:30:00.000Z"


def test_publish_omits_caption_key_when_caption_is_empty(wire):
    fake = wire(FakeGitHub(base_gallery=[]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    by_file = {e["file"]: e for e in fake.new_gallery_array()}
    e2 = by_file["20260703-987654321-2.webp"]
    assert "caption" not in e2                              # never "caption": ""


def test_publish_serializes_gallery_json_unescaped_and_indented(wire):
    fake = wire(FakeGitHub(base_gallery=[]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    content = fake.gallery_tree_entry()["content"]
    assert "Luna — full outfit + toggles" in content       # ensure_ascii=False
    assert "\n  " in content                               # indent=2


def test_publish_commit_message_is_the_d17_string(wire):
    fake = wire(FakeGitHub(base_gallery=[]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert fake.commit_payloads[0]["message"] == "gallery: publish 2 photos (discord msg 987654321)"


# ── removal: stateless, exact-segment, sha:null delete ────────────────────────────
def _remove_gallery():
    return [
        {"file": "20260703-987654321-1.webp", "caption": "keep? no", "width": 100, "height": 80, "date": "D1"},
        {"file": "20260703-111-1.webp", "width": 50, "height": 50, "date": "D2"},
        # a snowflake that merely *starts* with the target id must NOT be matched (D-14)
        {"file": "20260703-9876543210-1.webp", "width": 60, "height": 60, "date": "D3"},
    ]


def test_remove_deletes_only_the_matching_message_files_with_sha_null(wire):
    fake = wire(FakeGitHub(base_gallery=_remove_gallery()))

    asyncio.run(github_publish.remove_message(987654321))

    tree = fake.tree_entries()
    deletes = [t for t in tree if t["path"].startswith("public/gallery/") and t.get("sha") is None]
    assert [t["path"] for t in deletes] == ["public/gallery/20260703-987654321-1.webp"]
    # the prefix-collision file is NOT deleted
    assert all(t["path"] != "public/gallery/20260703-9876543210-1.webp" for t in deletes)


def test_remove_rewrites_gallery_json_without_the_removed_entries(wire):
    fake = wire(FakeGitHub(base_gallery=_remove_gallery()))

    asyncio.run(github_publish.remove_message(987654321))

    files = {e["file"] for e in fake.new_gallery_array()}
    assert files == {"20260703-111-1.webp", "20260703-9876543210-1.webp"}
    assert "20260703-987654321-1.webp" not in files


def test_remove_is_one_atomic_commit(wire):
    fake = wire(FakeGitHub(base_gallery=_remove_gallery()))

    asyncio.run(github_publish.remove_message(987654321))

    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1


def test_remove_commit_message_is_the_d17_string(wire):
    fake = wire(FakeGitHub(base_gallery=_remove_gallery()))

    asyncio.run(github_publish.remove_message(987654321))

    assert fake.commit_payloads[0]["message"] == "gallery: remove 1 photos (discord msg 987654321)"


def test_remove_with_no_matching_entries_is_a_noop_no_empty_commit(wire):
    fake = wire(FakeGitHub(base_gallery=_remove_gallery()))

    result = asyncio.run(github_publish.remove_message(555000555))   # no such file

    assert fake.commits_posted() == []
    assert fake.ref_patches() == []
    assert result["committed"] is False
    assert result["count"] == 0


# ── secrets + resilience ───────────────────────────────────────────────────────────
def test_authorization_header_is_bearer_pat_on_every_call(wire):
    fake = wire(FakeGitHub(base_gallery=[]))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert fake.calls, "no HTTP calls were made"
    for method, url, headers, _payload in fake.calls:
        assert headers is not None, f"{method} {url} carried no headers"
        assert headers.get("Authorization") == f"Bearer {FAKE_PAT}"
        assert headers.get("Accept") == "application/vnd.github+json"


def test_pat_is_never_written_to_logs(wire, caplog):
    fake = wire(FakeGitHub(base_gallery=[]))

    with caplog.at_level(logging.DEBUG):
        asyncio.run(github_publish.publish_message(
            987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert FAKE_PAT not in caplog.text                     # T-05-04


def test_stale_ref_422_on_patch_refetches_ref_and_retries(wire):
    # first PATCH => 422 (ref moved), second PATCH => 200
    fake = wire(FakeGitHub(base_gallery=[], patch_statuses=[422, 200]))

    result = asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert fake.ref_get_count >= 2                         # D-18: re-fetched the ref
    assert result["committed"] is True
    assert len(fake.ref_patches()) == 2


def test_repeated_stale_ref_conflicts_eventually_raise_typed_error(wire):
    # every PATCH conflicts -> retries exhausted -> typed error the cog can catch
    fake = wire(FakeGitHub(base_gallery=[], patch_statuses=[422, 422, 422, 422, 422, 422]))

    with pytest.raises(github_publish.GitHubPublishError):
        asyncio.run(github_publish.publish_message(
            987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))


# ── CR-01: network-level failures surface as the typed error, never escape raw ─────
def test_publish_network_error_surfaces_as_typed_publish_error(wire, monkeypatch):
    # A ConnectionError (DNS down, refused, reset) — the most common real-world failure
    # for a bot on a home/VPS link — must reach the cog as GitHubPublishError so the
    # D-19 ⚠️-retry UX fires instead of dying in discord.py's generic handler.
    wire(FakeGitHub(base_gallery=[]))

    def _dns_down(url, **kw):
        raise requests.exceptions.ConnectionError(
            "Name or service not known: https://api.github.com/should-not-leak")

    monkeypatch.setattr(github_publish.requests, "get", _dns_down)

    with pytest.raises(github_publish.GitHubPublishError) as excinfo:
        asyncio.run(github_publish.publish_message(
            987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))
    # only the exception class name is interpolated — a URL must never leak (T-05-04)
    assert "ConnectionError" in str(excinfo.value)
    assert "api.github.com" not in str(excinfo.value)


def test_remove_network_error_surfaces_as_typed_publish_error(wire, monkeypatch):
    wire(FakeGitHub(base_gallery=_remove_gallery()))

    def _hang_up(url, **kw):
        raise requests.exceptions.ConnectTimeout("connect timed out")

    monkeypatch.setattr(github_publish.requests, "get", _hang_up)

    with pytest.raises(github_publish.GitHubPublishError):
        asyncio.run(github_publish.remove_message(987654321))


def test_commit_lock_released_after_network_failure(wire, monkeypatch):
    # A typed failure must release _commit_lock so the NEXT publish still works —
    # otherwise one bad request would disable the whole pipeline until restart.
    fake = wire(FakeGitHub(base_gallery=[]))
    real_get = fake.get
    state = {"down": True}

    def _flaky(url, **kw):
        if state["down"]:
            raise requests.exceptions.ConnectionError("network down")
        return real_get(url, **kw)

    monkeypatch.setattr(github_publish.requests, "get", _flaky)

    with pytest.raises(github_publish.GitHubPublishError):
        asyncio.run(github_publish.publish_message(
            987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    state["down"] = False
    result = asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))
    assert result["committed"] is True         # lock was released by the typed failure


# ── WR-01: a >1MB gallery.json must NEVER be mistaken for an empty gallery ─────────
# The Contents API returns content:"" + encoding:"none" for 1MB-100MB files; treating
# that as [] would make the next publish rewrite gallery.json with only the new
# entries, silently wiping every existing tile.
def test_fetch_gallery_over_1mb_falls_back_to_raw_and_preserves_entries(wire, monkeypatch):
    base = [{"file": "20260703-111-1.webp", "width": 5, "height": 5, "date": "D0"}]
    fake = wire(FakeGitHub(base_gallery=base))
    real_get = fake.get
    raw_hits = []

    def _get(url, headers=None, **kw):
        if "/contents/" in url:
            if headers.get("Accept") == "application/vnd.github.raw+json":
                raw_hits.append(url)
                return _Resp(200, base)          # .text is the raw JSON array
            return _Resp(200, {"content": "", "encoding": "none", "size": 1_500_000})
        return real_get(url, headers=headers, **kw)

    monkeypatch.setattr(github_publish.requests, "get", _get)

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    assert raw_hits, "raw media-type fallback was never used"
    files = {e["file"] for e in fake.new_gallery_array()}
    assert "20260703-111-1.webp" in files        # existing entries preserved
    assert "20260703-987654321-1.webp" in files  # new entries appended


def test_fetch_gallery_unreadable_and_raw_failing_raises_never_commits(wire, monkeypatch):
    fake = wire(FakeGitHub(base_gallery=[]))
    real_get = fake.get

    def _get(url, headers=None, **kw):
        if "/contents/" in url:
            if headers.get("Accept") == "application/vnd.github.raw+json":
                return _Resp(500, {})            # raw path also broken
            return _Resp(200, {"content": "", "encoding": "none", "size": 1_500_000})
        return real_get(url, headers=headers, **kw)

    monkeypatch.setattr(github_publish.requests, "get", _get)

    with pytest.raises(github_publish.GitHubPublishError):
        asyncio.run(github_publish.publish_message(
            987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))
    assert fake.commits_posted() == []           # nothing destructive was committed


# ── CR-02: every HTTP call carries an explicit timeout (requests has NO default) ───
def test_every_http_call_carries_an_explicit_timeout(wire):
    # A black-holed connection with no timeout would hold _commit_lock forever and
    # silently disable the whole pipeline — publish AND removal paths must be covered.
    fake = wire(FakeGitHub(base_gallery=_remove_gallery()))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))
    asyncio.run(github_publish.remove_message(987654321))

    assert fake.timeouts, "no HTTP calls were recorded"
    assert all(t not in (None, 0) for t in fake.timeouts)


# ── WR-06: ONE strict filename parser — deletion can never match non-bot files ─────
def test_entry_message_id_accepts_only_the_exact_bot_shape():
    assert github_publish._entry_message_id("20260703-987654321-1.webp") == "987654321"
    # loose-split bait: middle dash-segment equals a msg id but the shape is NOT ours
    assert github_publish._entry_message_id("manual-987654321-shot.png") is None
    assert github_publish._entry_message_id("goo.jpg") is None
    assert github_publish._entry_message_id("") is None
    assert github_publish._entry_message_id(None) is None


def test_remove_ignores_non_bot_filenames_with_matching_segment(wire):
    # A manually-committed file whose middle dash-segment happens to equal the message
    # id must NEVER be deleted — deletion uses the same strict parser as identification.
    base = [{"file": "manual-987654321-shot.png", "width": 1, "height": 1, "date": "D0"}]
    fake = wire(FakeGitHub(base_gallery=base))

    result = asyncio.run(github_publish.remove_message(987654321))

    assert result["committed"] is False                    # no-op — nothing matched
    assert fake.commits_posted() == []                     # and no commit was created


# ── WR-02: publish is commit-level idempotent (replace, never append-duplicate) ────
def test_publish_replaces_existing_entries_for_same_message(wire):
    # A double-✅ race or a re-✅ after a lost 🟢 must republish cleanly: existing
    # entries for THIS message are dropped before the fresh ones are appended.
    base = [
        {"file": "20260703-987654321-1.webp", "width": 1, "height": 1, "date": "D0"},
        {"file": "manual-987654321-shot.png", "width": 2, "height": 2, "date": "D0"},
    ]
    fake = wire(FakeGitHub(base_gallery=base))

    asyncio.run(github_publish.publish_message(
        987654321, _publish_entries(), date="2026-07-03T18:30:00.000Z"))

    arr = fake.new_gallery_array()
    files = [e["file"] for e in arr]
    assert files.count("20260703-987654321-1.webp") == 1   # replaced, not duplicated
    assert "manual-987654321-shot.png" in files            # non-bot filename untouched
    assert len(arr) == 3                                   # manual + 2 fresh entries
    by_file = {e["file"]: e for e in arr}
    assert by_file["20260703-987654321-1.webp"]["width"] == 1600   # the FRESH entry won
