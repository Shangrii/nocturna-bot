"""Behaviour tests for the reviews cross-repo commit transport (Fase 7, REV-04/REV-05).

These pin the contract of ``core.github_publish.publish_review`` / ``remove_review`` —
the thin path that commits a SINGLE ``reviews.json`` blob (no image blobs) against the
website repo via the same GitHub Git Data API dance the gallery uses (ref -> tree ->
commit -> ref), reusing ``_headers`` / ``_http`` / ``_create_tree`` / ``_create_commit`` /
``_update_ref`` / ``_commit_lock`` / ``GitHubPublishError`` and the retry/backoff core.

Everything HTTP is mocked exactly like ``test_github_publish.py``: ``requests
.get/post/patch`` are monkeypatched with a programmable fake that records every call and
returns canned GitHub JSON per endpoint. The async ``publish_review`` / ``remove_review``
are driven with ``asyncio.run`` (no pytest-asyncio dependency needed).

Contract asserted here:
  * a publish commits exactly ONE ``/git/commits`` POST + ONE ref PATCH (atomic)
  * the publish tree holds a SINGLE ``reviews.json`` entry by inline content (no blobs)
  * ``reviews.json`` is APPENDED to, deduped by ``entry["id"]`` (idempotent re-publish)
  * ``author: null`` is preserved verbatim (never coerced to "" or a name)
  * serialization is ensure_ascii=False + 2-space indent (reuses ``_serialize_json``)
  * commit messages: ``reviews: publish/remove review (discord msg <id>)``
  * removal drops the matching id; a no-match removal is a no-op (no empty commit)
  * a 422 on the ref PATCH re-fetches the ref and retries with backoff
  * the PAT rides in an ``Authorization: Bearer`` header and never reaches logs
  * every HTTP call carries an explicit timeout
"""

import asyncio
import base64
import json
import logging

import pytest

import config
from core import github_publish


# ── programmable fake GitHub Git Data API (reviews.json, no blobs) ─────────────────
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
    Serves the current reviews array on the ``/contents/`` endpoint.
    """

    def __init__(self, base_reviews, patch_statuses=None):
        self.base_reviews = base_reviews
        self.calls = []            # (method, url, headers, json_payload)
        self.timeouts = []         # the timeout kwarg of every call
        self.ref_get_count = 0
        self.tree_payloads = []
        self.commit_payloads = []
        self.patch_payloads = []
        self._patch_statuses = list(patch_statuses or [200])

    def _b64_reviews(self):
        raw = json.dumps(self.base_reviews).encode("utf-8")
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
            return _Resp(200, {"content": self._b64_reviews(), "encoding": "base64"})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers=None, json=None, **kw):
        self.calls.append(("POST", url, headers, json))
        self.timeouts.append(kw.get("timeout"))
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

    def reviews_tree_entry(self):
        return next(t for t in self.tree_entries() if t["path"] == config.WEBSITE_REVIEWS_JSON)

    def new_reviews_array(self):
        return json.loads(self.reviews_tree_entry()["content"])


FAKE_PAT = "ghp_faketoken_should_never_be_logged_123456"


@pytest.fixture
def wire(monkeypatch):
    """Install the fake HTTP layer + deterministic config, silence backoff sleeps.

    Returns an ``install(fake)`` callable so each test can build its own FakeGitHub.
    """
    monkeypatch.setattr(config, "GITHUB_PAT", FAKE_PAT)
    monkeypatch.setattr(config, "WEBSITE_REPO", "Shangrii/Nocturna-Avatars")
    monkeypatch.setattr(config, "WEBSITE_BRANCH", "revamp")
    monkeypatch.setattr(config, "WEBSITE_REVIEWS_JSON", "src/data/reviews.json")
    # never wait on retry backoff during tests
    monkeypatch.setattr(github_publish.time, "sleep", lambda *_a, **_k: None)

    def install(fake):
        monkeypatch.setattr(github_publish.requests, "get", fake.get)
        monkeypatch.setattr(github_publish.requests, "post", fake.post)
        monkeypatch.setattr(github_publish.requests, "patch", fake.patch)
        return fake

    return install


def _entry(msg_id="987654321", author="Luna", text="Amazing work!", date="2026-07-08T18:30:00.000Z"):
    return {"id": str(msg_id), "author": author, "text": text, "date": date}


# ── publish: atomicity + tree shape ───────────────────────────────────────────────
def test_publish_makes_exactly_one_commit_and_one_ref_patch(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(_entry()))

    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1


def test_publish_tree_is_a_single_reviews_json_by_content_no_blobs(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(_entry()))

    tree = fake.tree_entries()
    assert len(tree) == 1                                  # only reviews.json, no image blobs
    entry = tree[0]
    assert entry["path"] == config.WEBSITE_REVIEWS_JSON
    assert entry["mode"] == "100644" and entry["type"] == "blob"
    assert "content" in entry and "sha" not in entry       # inline content, never a blob sha
    # no blob POSTs were ever made
    assert all(not c[1].endswith("/git/blobs") for c in fake.calls if c[0] == "POST")


def test_publish_uses_base_tree_and_parent_from_the_current_ref(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(_entry()))

    assert fake.tree_payloads[0]["base_tree"] == "BASE_TREE_SHA"
    commit = fake.commit_payloads[0]
    assert commit["parents"] == ["PARENT_SHA"]
    assert commit["tree"] == "NEW_TREE_SHA"
    assert fake.patch_payloads[0]["sha"] == "NEW_COMMIT_SHA"


# ── publish: append + dedupe + author:null + serialization ────────────────────────
def test_publish_appends_entry_preserving_existing_reviews(wire):
    base = [{"id": "111", "author": "Sol", "text": "Great!", "date": "D0"}]
    fake = wire(FakeGitHub(base_reviews=base))

    asyncio.run(github_publish.publish_review(_entry(msg_id="987654321")))

    arr = fake.new_reviews_array()
    ids = {e["id"] for e in arr}
    assert ids == {"111", "987654321"}                     # base preserved + new appended
    result_count = asyncio.run(github_publish.publish_review(_entry(msg_id="222")))
    assert result_count["committed"] is True
    assert result_count["count"] == 1


def test_publish_is_idempotent_dedupes_by_id(wire):
    # A re-publish of the same discord message id replaces the entry, never duplicates it.
    base = [{"id": "987654321", "author": "OLD", "text": "old text", "date": "D0"}]
    fake = wire(FakeGitHub(base_reviews=base))

    asyncio.run(github_publish.publish_review(
        _entry(msg_id="987654321", author="NEW", text="new text")))

    arr = fake.new_reviews_array()
    ids = [e["id"] for e in arr]
    assert ids.count("987654321") == 1                     # replaced, not duplicated
    by_id = {e["id"]: e for e in arr}
    assert by_id["987654321"]["author"] == "NEW"           # the FRESH entry won
    assert by_id["987654321"]["text"] == "new text"


def test_publish_preserves_author_null(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(_entry(msg_id="987654321", author=None)))

    arr = fake.new_reviews_array()
    entry = next(e for e in arr if e["id"] == "987654321")
    assert entry["author"] is None                         # null preserved verbatim
    # and the serialized JSON literally contains a null, not "" or a name
    content = fake.reviews_tree_entry()["content"]
    assert '"author": null' in content


def test_publish_serializes_reviews_json_unescaped_and_indented(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(
        _entry(text="Trabajo increíble — ¡gracias!")))

    content = fake.reviews_tree_entry()["content"]
    assert "Trabajo increíble — ¡gracias!" in content      # ensure_ascii=False
    assert "\n  " in content                               # indent=2


def test_publish_commit_message_is_the_reviews_string(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(_entry(msg_id="987654321")))

    assert fake.commit_payloads[0]["message"] == "reviews: publish review (discord msg 987654321)"


def test_publish_returns_committed_true_with_count_one(wire):
    wire(FakeGitHub(base_reviews=[]))

    result = asyncio.run(github_publish.publish_review(_entry()))

    assert result["committed"] is True
    assert result["count"] == 1
    assert result["commit_sha"] == "NEW_COMMIT_SHA"


# ── removal: drop-by-id, atomic, no-op on no-match ─────────────────────────────────
def _remove_reviews():
    return [
        {"id": "987654321", "author": "Luna", "text": "remove me", "date": "D1"},
        {"id": "111", "author": None, "text": "keep me", "date": "D2"},
    ]


def test_remove_drops_only_the_matching_id(wire):
    fake = wire(FakeGitHub(base_reviews=_remove_reviews()))

    asyncio.run(github_publish.remove_review(987654321))

    ids = {e["id"] for e in fake.new_reviews_array()}
    assert ids == {"111"}                                  # only the match dropped
    assert "987654321" not in ids


def test_remove_is_one_atomic_commit(wire):
    fake = wire(FakeGitHub(base_reviews=_remove_reviews()))

    asyncio.run(github_publish.remove_review(987654321))

    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1


def test_remove_commit_message_is_the_reviews_string(wire):
    fake = wire(FakeGitHub(base_reviews=_remove_reviews()))

    asyncio.run(github_publish.remove_review(987654321))

    assert fake.commit_payloads[0]["message"] == "reviews: remove review (discord msg 987654321)"


def test_remove_preserves_author_null_on_the_kept_entries(wire):
    fake = wire(FakeGitHub(base_reviews=_remove_reviews()))

    asyncio.run(github_publish.remove_review(987654321))

    kept = fake.new_reviews_array()
    assert kept == [{"id": "111", "author": None, "text": "keep me", "date": "D2"}]


def test_remove_with_no_matching_entry_is_a_noop_no_empty_commit(wire):
    fake = wire(FakeGitHub(base_reviews=_remove_reviews()))

    result = asyncio.run(github_publish.remove_review(555000555))   # no such id

    assert fake.commits_posted() == []
    assert fake.ref_patches() == []
    assert result["committed"] is False
    assert result["count"] == 0


# ── secrets + resilience ───────────────────────────────────────────────────────────
def test_authorization_header_is_bearer_pat_on_every_call(wire):
    fake = wire(FakeGitHub(base_reviews=[]))

    asyncio.run(github_publish.publish_review(_entry()))

    assert fake.calls, "no HTTP calls were made"
    for method, url, headers, _payload in fake.calls:
        assert headers is not None, f"{method} {url} carried no headers"
        assert headers.get("Authorization") == f"Bearer {FAKE_PAT}"
        assert headers.get("Accept") == "application/vnd.github+json"


def test_pat_is_never_written_to_logs(wire, caplog):
    fake = wire(FakeGitHub(base_reviews=[]))

    with caplog.at_level(logging.DEBUG):
        asyncio.run(github_publish.publish_review(_entry()))

    assert FAKE_PAT not in caplog.text


def test_stale_ref_422_on_patch_refetches_ref_and_retries(wire):
    fake = wire(FakeGitHub(base_reviews=[], patch_statuses=[422, 200]))

    result = asyncio.run(github_publish.publish_review(_entry()))

    assert fake.ref_get_count >= 2                          # re-fetched the ref
    assert result["committed"] is True
    assert len(fake.ref_patches()) == 2


def test_repeated_stale_ref_conflicts_eventually_raise_typed_error(wire):
    wire(FakeGitHub(base_reviews=[], patch_statuses=[422, 422, 422, 422, 422, 422]))

    with pytest.raises(github_publish.GitHubPublishError):
        asyncio.run(github_publish.publish_review(_entry()))


def test_every_http_call_carries_an_explicit_timeout(wire):
    fake = wire(FakeGitHub(base_reviews=_remove_reviews()))

    asyncio.run(github_publish.publish_review(_entry()))
    asyncio.run(github_publish.remove_review(987654321))

    assert fake.timeouts, "no HTTP calls were recorded"
    assert all(t not in (None, 0) for t in fake.timeouts)


# ── WR-04: malformed reviews.json is normalized into the typed error ────────────────
def _raw_contents_get(raw_bytes):
    """A ``requests.get`` stand-in serving arbitrary raw bytes on ``/contents/``."""
    def get(url, headers=None, **kw):
        assert "/contents/" in url
        return _Resp(200, {"content": base64.b64encode(raw_bytes).decode("ascii"),
                           "encoding": "base64"})
    return get


def test_fetch_json_invalid_json_raises_typed_error(wire, monkeypatch):
    # A manually-edited/partially-written file must raise GitHubPublishError (the cog's
    # ⚠️ retry UX), never a bare JSONDecodeError escaping the typed-error contract.
    wire(FakeGitHub(base_reviews=[]))
    monkeypatch.setattr(github_publish.requests, "get", _raw_contents_get(b"{ not json !"))
    with pytest.raises(github_publish.GitHubPublishError, match="invalid JSON"):
        github_publish._fetch_json("Shangrii/Nocturna-Avatars", "revamp",
                                   "src/data/reviews.json")


def test_fetch_json_non_array_body_raises_typed_error(wire, monkeypatch):
    # A non-array body (e.g. someone commits {}) would make build_tree raise
    # AttributeError on e.get("id") — reject it at the transport boundary instead.
    wire(FakeGitHub(base_reviews=[]))
    monkeypatch.setattr(github_publish.requests, "get", _raw_contents_get(b'{"id": "1"}'))
    with pytest.raises(github_publish.GitHubPublishError, match="expected a JSON array"):
        github_publish._fetch_json("Shangrii/Nocturna-Avatars", "revamp",
                                   "src/data/reviews.json")


def test_publish_over_malformed_reviews_json_raises_typed_error(wire, monkeypatch):
    # End-to-end through publish_review: corruption surfaces as the typed error.
    fake = wire(FakeGitHub(base_reviews=[]))

    def bad_contents_get(url, headers=None, **kw):
        if "/contents/" in url:
            return _Resp(200, {"content": base64.b64encode(b"[oops").decode("ascii"),
                               "encoding": "base64"})
        return fake.get(url, headers=headers, **kw)

    monkeypatch.setattr(github_publish.requests, "get", bad_contents_get)
    with pytest.raises(github_publish.GitHubPublishError):
        asyncio.run(github_publish.publish_review(_entry()))
