"""Behaviour tests for the OBJECT-aware store cross-repo commit transport (Fase 9, STORE-SYNC-01).

These pin the contract of ``core.github_publish.sync_store`` / ``attach_store_media`` /
``_fetch_store`` — the store variant of the reviews transport that commits a SINGLE
``store.json`` blob (plus image blobs for the attach flow) against the website repo via the
same GitHub Git Data API dance (ref -> tree -> commit -> ref), reusing ``_headers`` /
``_http`` / ``_create_blob`` / ``_create_tree`` / ``_create_commit`` / ``_update_ref`` /
``_commit_lock`` / ``_commit_with_retry`` / ``GitHubPublishError`` and the retry/backoff core.

The load-bearing divergence from gallery/reviews (RESEARCH Pattern 2 / Pitfall 1):
``store.json`` is an OBJECT ``{"_comment": "<schema doc>", "products": [...]}``, not an
array. ``_fetch_json`` raises "expected a JSON array" on a dict body, so the store needs a
dict-expecting sibling that PRESERVES ``_comment`` (and any staff-added top-level keys) on
every commit.

Everything HTTP is mocked exactly like ``test_reviews_publish.py``: ``requests
.get/post/patch`` are monkeypatched with a programmable fake that records every call and
returns canned GitHub JSON per endpoint. The async ``sync_store`` / ``attach_store_media``
are driven with ``asyncio.run`` (no pytest-asyncio dependency needed).

Contract asserted here:
  * ``_fetch_store`` returns the WHOLE object (``_comment`` + ``products`` + unknown keys)
  * an array body, or a dict missing ``products``, raises the typed error (object-shape guard)
  * ``sync_store`` preserves ``_comment`` + staff-added top-level keys, replacing only ``products``
  * ``sync_store`` with no change is a no-op (no commit, no ref PATCH, no Pages rebuild)
  * serialization is ensure_ascii=False + 2-space indent (Spanish text readable, byte-shape matches)
  * ``attach_store_media`` commits image blobs under ``public/store`` + writes ``images[]`` /
    ``description`` into the matched product in ONE commit, leaving every other product intact
  * a ``checkout_url`` matching no product raises (never silently discards staff work)
  * images-only leaves ``description`` untouched and vice-versa
"""

import asyncio
import base64
import json

import pytest

import config
from core import github_publish


COMMENT = "SCHEMA: productos de la tienda. NO editar a mano salvo images/description."


# ── programmable fake GitHub Git Data API (store.json object body + image blobs) ────
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
    Serves the current store OBJECT on the ``/contents/`` endpoint.
    """

    def __init__(self, base_store, patch_statuses=None):
        self.base_store = base_store
        self.calls = []            # (method, url, headers, json_payload)
        self.timeouts = []         # the timeout kwarg of every call
        self.ref_get_count = 0
        self.blob_payloads = []
        self.tree_payloads = []
        self.commit_payloads = []
        self.patch_payloads = []
        self._patch_statuses = list(patch_statuses or [200])
        self._blob_counter = 0

    def _b64_store(self):
        raw = json.dumps(self.base_store).encode("utf-8")
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
            return _Resp(200, {"content": self._b64_store(), "encoding": "base64"})
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url, headers=None, json=None, **kw):
        self.calls.append(("POST", url, headers, json))
        self.timeouts.append(kw.get("timeout"))
        if url.endswith("/git/blobs"):
            self.blob_payloads.append(json)
            self._blob_counter += 1
            return _Resp(201, {"sha": f"BLOB_SHA_{self._blob_counter}"})
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

    def store_tree_entry(self):
        return next(t for t in self.tree_entries() if t["path"] == config.WEBSITE_STORE_JSON)

    def blob_tree_entries(self):
        return [t for t in self.tree_entries() if "sha" in t]

    def new_store_object(self):
        return json.loads(self.store_tree_entry()["content"])


FAKE_PAT = "ghp_faketoken_should_never_be_logged_123456"


@pytest.fixture
def wire(monkeypatch):
    """Install the fake HTTP layer + deterministic config, silence backoff sleeps.

    Returns an ``install(fake)`` callable so each test can build its own FakeGitHub.
    """
    monkeypatch.setattr(config, "GITHUB_PAT", FAKE_PAT)
    monkeypatch.setattr(config, "WEBSITE_REPO", "Shangrii/Nocturna-Avatars")
    monkeypatch.setattr(config, "WEBSITE_BRANCH", "revamp")
    monkeypatch.setattr(config, "WEBSITE_STORE_JSON", "src/data/store.json")
    monkeypatch.setattr(config, "WEBSITE_STORE_IMAGE_DIR", "public/store")
    # never wait on retry backoff during tests
    monkeypatch.setattr(github_publish.time, "sleep", lambda *_a, **_k: None)

    def install(fake):
        monkeypatch.setattr(github_publish.requests, "get", fake.get)
        monkeypatch.setattr(github_publish.requests, "post", fake.post)
        monkeypatch.setattr(github_publish.requests, "patch", fake.patch)
        return fake

    return install


# ── data builders ──────────────────────────────────────────────────────────────────
def _product(checkout="https://jinxxy.com/nocturna/cahuama", name="Cahuama", **extra):
    p = {
        "checkoutUrl": checkout,
        "name": {"es": name, "en": name},
        "price": "25",
        "category": "assets",
        "nsfw": False,
        "date": "2026-07-01",
    }
    p.update(extra)
    return p


def _store(products=None, comment=COMMENT, **extra):
    obj = {"_comment": comment, "products": [] if products is None else products}
    obj.update(extra)
    return obj


def _raw_contents_get(raw_bytes):
    """A ``requests.get`` stand-in serving arbitrary raw bytes on ``/contents/``."""
    def get(url, headers=None, **kw):
        assert "/contents/" in url
        return _Resp(200, {"content": base64.b64encode(raw_bytes).decode("ascii"),
                           "encoding": "base64"})
    return get


# ── _fetch_store: whole-object read + object-shape rejection ────────────────────────
def test_fetch_store_returns_whole_object_including_comment(wire):
    wire(FakeGitHub(base_store=_store(products=[_product()])))

    obj = github_publish._fetch_store("Shangrii/Nocturna-Avatars", "revamp",
                                      "src/data/store.json")

    assert obj["_comment"] == COMMENT
    assert obj["products"] == [_product()]


def test_fetch_store_on_array_body_raises_typed_error(wire, monkeypatch):
    wire(FakeGitHub(base_store=_store()))
    monkeypatch.setattr(github_publish.requests, "get", _raw_contents_get(b"[]"))
    with pytest.raises(github_publish.GitHubPublishError, match="products"):
        github_publish._fetch_store("Shangrii/Nocturna-Avatars", "revamp",
                                    "src/data/store.json")


def test_fetch_store_on_dict_missing_products_raises_typed_error(wire, monkeypatch):
    wire(FakeGitHub(base_store=_store()))
    monkeypatch.setattr(github_publish.requests, "get",
                        _raw_contents_get(b'{"_comment": "x"}'))
    with pytest.raises(github_publish.GitHubPublishError, match="products"):
        github_publish._fetch_store("Shangrii/Nocturna-Avatars", "revamp",
                                    "src/data/store.json")


# ── sync_store: _comment preserved, products replaced, no-op guard, serialization ───
def test_sync_store_preserves_comment_and_sets_products(wire):
    # LOAD-BEARING: the committed blob must still carry _comment with its original text.
    fake = wire(FakeGitHub(base_store=_store(products=[_product(name="Old")])))
    new_products = [_product(name="Nuevo")]

    result = asyncio.run(github_publish.sync_store(new_products))

    obj = fake.new_store_object()
    assert obj["_comment"] == COMMENT                      # schema doc survives
    assert obj["products"] == new_products                 # products replaced
    assert result["committed"] is True


def test_sync_store_preserves_staff_added_top_level_key(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[], _note="mano de staff")))

    asyncio.run(github_publish.sync_store([_product()]))

    obj = fake.new_store_object()
    assert obj["_note"] == "mano de staff"                 # unknown top-level key survives
    assert obj["_comment"] == COMMENT


def test_sync_store_no_change_is_a_noop_no_commit(wire):
    existing = [_product()]
    fake = wire(FakeGitHub(base_store=_store(products=existing)))

    result = asyncio.run(github_publish.sync_store([_product()]))   # identical list

    assert fake.commits_posted() == []                     # no empty commit
    assert fake.ref_patches() == []                        # no ref PATCH -> no Pages rebuild
    assert result["committed"] is False


def test_sync_store_is_one_atomic_commit(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[])))

    asyncio.run(github_publish.sync_store([_product()]))

    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1
    # a single store.json blob by inline content, no image blobs on a plain sync
    tree = fake.tree_entries()
    assert len(tree) == 1
    assert tree[0]["path"] == config.WEBSITE_STORE_JSON
    assert "content" in tree[0] and "sha" not in tree[0]


def test_sync_store_serializes_unescaped_and_indented(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[])))

    asyncio.run(github_publish.sync_store([_product(name="Diseño Increíble")]))

    content = fake.store_tree_entry()["content"]
    assert "Diseño Increíble" in content                   # ensure_ascii=False
    assert "\n  " in content                               # indent=2


def test_sync_store_stale_ref_422_refetches_and_retries(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[]), patch_statuses=[422, 200]))

    result = asyncio.run(github_publish.sync_store([_product()]))

    assert fake.ref_get_count >= 2                          # re-fetched the ref
    assert result["committed"] is True
    assert len(fake.ref_patches()) == 2


# ── WR-01: build_tree re-grafts staff-owned fields from the fresh fetch ──────────────
def test_sync_store_regrafts_staff_fields_from_fresh_fetch(wire):
    # A /tienda medios attach landed in the LIVE store (staff images + description)
    # AFTER the merge computed its products list. The sync re-fetches the store inside
    # build_tree and must re-graft those staff fields so the concurrent attach is never
    # reverted (WR-01 / gap #1). JINXXY_DEPLOY.md tells staff to run /tienda medios per
    # product right after the first sync, so this race is on the documented happy path.
    live_prod = _product(name="Old", price="25",
                         images=["/store/cahuama-0.webp"],
                         description={"es": "hecho por staff", "en": "by staff"})
    fake = wire(FakeGitHub(base_store=_store(products=[live_prod])))
    # The merged list for the SAME checkoutUrl OMITS the staff fields but carries a real
    # Jinxxy price change — the sync-owned change must still propagate.
    merged = [_product(name="Old", price="30")]

    result = asyncio.run(github_publish.sync_store(merged))

    obj = fake.new_store_object()
    committed = next(p for p in obj["products"]
                     if p["checkoutUrl"] == "https://jinxxy.com/nocturna/cahuama")
    # staff-owned fields re-grafted from the fresh fetch (NOT reverted to the merged list)
    assert committed["images"] == ["/store/cahuama-0.webp"]
    assert committed["description"] == {"es": "hecho por staff", "en": "by staff"}
    # sync-owned change from the merged list still applied (Jinxxy changes propagate)
    assert committed["price"] == "30"
    assert result["committed"] is True


def test_sync_store_new_product_absent_from_fresh_is_written_verbatim(wire):
    # A genuinely new product whose checkoutUrl is absent from the fresh store: no graft
    # applied, written verbatim, no crash.
    fake = wire(FakeGitHub(base_store=_store(products=[])))          # empty live store
    new = [_product(checkout="https://jinxxy.com/nocturna/nuevo", name="Nuevo")]

    result = asyncio.run(github_publish.sync_store(new))

    obj = fake.new_store_object()
    assert obj["products"] == new                                   # verbatim, no graft
    assert result["committed"] is True


# ── attach_store_media: image blobs + description in ONE commit, staff-owned fields ──
def test_attach_media_commits_blobs_and_updates_matched_product(wire):
    prod = _product(checkout="https://jinxxy.com/nocturna/cahuama")
    other = _product(checkout="https://jinxxy.com/nocturna/otro", name="Otro")
    fake = wire(FakeGitHub(base_store=_store(products=[prod, other])))
    media = [(b"img1bytes", "111-0.webp"), (b"img2bytes", "111-1.webp")]
    desc = {"es": "Descripción", "en": "Description"}

    result = asyncio.run(github_publish.attach_store_media(
        "https://jinxxy.com/nocturna/cahuama", media=media, description=desc))

    # ONE commit, ONE ref patch
    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1
    # two image blobs written under public/store
    blobs = fake.blob_tree_entries()
    assert len(blobs) == 2
    assert {b["path"] for b in blobs} == {"public/store/111-0.webp",
                                          "public/store/111-1.webp"}
    # matched product carries site-relative /store/ paths + the new description
    obj = fake.new_store_object()
    matched = next(p for p in obj["products"]
                   if p["checkoutUrl"] == "https://jinxxy.com/nocturna/cahuama")
    assert matched["images"] == ["/store/111-0.webp", "/store/111-1.webp"]
    assert matched["description"] == desc
    assert result["committed"] is True


def test_attach_media_preserves_comment_and_other_products(wire):
    prod = _product(checkout="https://jinxxy.com/nocturna/cahuama")
    other = _product(checkout="https://jinxxy.com/nocturna/otro", name="Otro")
    fake = wire(FakeGitHub(base_store=_store(products=[prod, other])))

    asyncio.run(github_publish.attach_store_media(
        "https://jinxxy.com/nocturna/cahuama",
        media=[(b"x", "1.webp")], description={"es": "d", "en": "d"}))

    obj = fake.new_store_object()
    assert obj["_comment"] == COMMENT
    kept = next(p for p in obj["products"]
                if p["checkoutUrl"] == "https://jinxxy.com/nocturna/otro")
    assert kept == other                                   # byte-identical, untouched


def test_attach_media_no_matching_product_raises(wire):
    wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama")])))

    with pytest.raises(github_publish.GitHubPublishError, match="checkoutUrl"):
        asyncio.run(github_publish.attach_store_media(
            "https://jinxxy.com/nocturna/inexistente", media=[(b"x", "1.webp")]))


def test_attach_media_images_only_leaves_description_untouched(wire):
    prod = _product(checkout="https://jinxxy.com/nocturna/cahuama",
                    description={"es": "orig", "en": "orig"})
    fake = wire(FakeGitHub(base_store=_store(products=[prod])))

    asyncio.run(github_publish.attach_store_media(
        "https://jinxxy.com/nocturna/cahuama", media=[(b"x", "1.webp")]))

    p = fake.new_store_object()["products"][0]
    assert p["images"] == ["/store/1.webp"]
    assert p["description"] == {"es": "orig", "en": "orig"}   # untouched (description=None)


def test_attach_media_description_only_leaves_images_untouched(wire):
    prod = _product(checkout="https://jinxxy.com/nocturna/cahuama",
                    images=["/store/existing.webp"])
    fake = wire(FakeGitHub(base_store=_store(products=[prod])))

    asyncio.run(github_publish.attach_store_media(
        "https://jinxxy.com/nocturna/cahuama", description={"es": "nuevo", "en": "new"}))

    p = fake.new_store_object()["products"][0]
    assert p["description"] == {"es": "nuevo", "en": "new"}
    assert p["images"] == ["/store/existing.webp"]           # untouched (no media)
    assert fake.blob_tree_entries() == []                    # no blobs created


# ── set_store_editor: editor-only write to the matched product ──────────────────────
def test_set_store_editor_sets_editor_and_preserves_comment(wire):
    # LOAD-BEARING: the committed blob must still carry _comment AND set editor only on
    # the checkoutUrl-matched product, leaving every other field/product untouched.
    prod = _product(checkout="https://jinxxy.com/nocturna/cahuama", editor="Old")
    other = _product(checkout="https://jinxxy.com/nocturna/otro", name="Otro",
                     editor="Nadie")
    fake = wire(FakeGitHub(base_store=_store(products=[prod, other])))

    result = asyncio.run(github_publish.set_store_editor(
        "https://jinxxy.com/nocturna/cahuama", "Shangri"))

    obj = fake.new_store_object()
    assert obj["_comment"] == COMMENT                       # schema doc survives
    matched = next(p for p in obj["products"]
                   if p["checkoutUrl"] == "https://jinxxy.com/nocturna/cahuama")
    assert matched["editor"] == "Shangri"                  # editor set
    # only editor changed — every other field of the matched product intact
    assert matched["price"] == "25" and matched["name"] == {"es": "Cahuama", "en": "Cahuama"}
    kept = next(p for p in obj["products"]
                if p["checkoutUrl"] == "https://jinxxy.com/nocturna/otro")
    assert kept == other                                   # other product byte-identical
    assert result["committed"] is True


def test_set_store_editor_is_one_atomic_commit_no_blobs(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama", editor="Old")])))

    asyncio.run(github_publish.set_store_editor(
        "https://jinxxy.com/nocturna/cahuama", "Shangri"))

    assert len(fake.commits_posted()) == 1
    assert len(fake.ref_patches()) == 1
    # a single store.json blob by inline content, NO image blobs (editor is text-only)
    tree = fake.tree_entries()
    assert len(tree) == 1
    assert tree[0]["path"] == config.WEBSITE_STORE_JSON
    assert "content" in tree[0] and "sha" not in tree[0]
    assert fake.blob_tree_entries() == []


def test_set_store_editor_no_matching_product_raises(wire):
    wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama")])))

    with pytest.raises(github_publish.GitHubPublishError, match="checkoutUrl"):
        asyncio.run(github_publish.set_store_editor(
            "https://jinxxy.com/nocturna/inexistente", "Shangri"))


def test_set_store_editor_unchanged_is_a_noop_no_commit(wire):
    # The matched product's editor already equals the requested value → no commit, no ref
    # PATCH, no Pages rebuild (parity with the sync_store D-06 no-op guard).
    fake = wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama", editor="Shangri")])))

    result = asyncio.run(github_publish.set_store_editor(
        "https://jinxxy.com/nocturna/cahuama", "Shangri"))

    assert fake.commits_posted() == []                     # no empty commit
    assert fake.ref_patches() == []                        # no ref PATCH -> no Pages rebuild
    assert result["committed"] is False


def test_set_store_editor_serializes_unescaped_and_indented(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama", editor="Old")])))

    asyncio.run(github_publish.set_store_editor(
        "https://jinxxy.com/nocturna/cahuama", "Diseñador Íñigo"))

    content = fake.store_tree_entry()["content"]
    assert "Diseñador Íñigo" in content                     # ensure_ascii=False
    assert "\n  " in content                               # indent=2


def test_set_store_editor_stale_ref_422_refetches_and_retries(wire):
    fake = wire(FakeGitHub(
        base_store=_store(products=[
            _product(checkout="https://jinxxy.com/nocturna/cahuama", editor="Old")]),
        patch_statuses=[422, 200]))

    result = asyncio.run(github_publish.set_store_editor(
        "https://jinxxy.com/nocturna/cahuama", "Shangri"))

    assert fake.ref_get_count >= 2                          # re-fetched the ref
    assert result["committed"] is True
    assert len(fake.ref_patches()) == 2


def test_set_store_editor_commit_message_references_url_not_editor(wire):
    # T-09-22: the raw editor text must NEVER be interpolated into the commit message;
    # the message references the validated checkoutUrl key only.
    fake = wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama", editor="Old")])))
    secret = "SENSITIVE_EDITOR_NAME_xyz"

    asyncio.run(github_publish.set_store_editor(
        "https://jinxxy.com/nocturna/cahuama", secret))

    commit_payload = fake.commit_payloads[0]
    assert "https://jinxxy.com/nocturna/cahuama" in commit_payload["message"]
    assert secret not in commit_payload["message"]         # editor value never leaks


# ── secrets + serialization on the attach path ─────────────────────────────────────
def test_attach_media_authorization_header_is_bearer_pat_on_every_call(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama")])))

    asyncio.run(github_publish.attach_store_media(
        "https://jinxxy.com/nocturna/cahuama", media=[(b"x", "1.webp")]))

    assert fake.calls, "no HTTP calls were made"
    for method, url, headers, _payload in fake.calls:
        assert headers is not None, f"{method} {url} carried no headers"
        assert headers.get("Authorization") == f"Bearer {FAKE_PAT}"


def test_attach_media_every_http_call_carries_an_explicit_timeout(wire):
    fake = wire(FakeGitHub(base_store=_store(products=[
        _product(checkout="https://jinxxy.com/nocturna/cahuama")])))

    asyncio.run(github_publish.attach_store_media(
        "https://jinxxy.com/nocturna/cahuama", media=[(b"x", "1.webp")]))

    assert fake.timeouts, "no HTTP calls were recorded"
    assert all(t not in (None, 0) for t in fake.timeouts)
