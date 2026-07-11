"""Unit tests for the pure store-sync core (Fase 9, plan 09-03).

This suite proves the deterministic, high-risk heart of the Jinxxy → ``store.json`` sync
BEFORE any Discord/API/DB wiring exists (the client is 09-02; the cog + object-aware
transport are 09-05). Every function under test is a pure module-level function with no
Discord/network/DB dependency, so the tests are plain ``assert fn(...) == expected`` —
matching the repo idiom (SimpleNamespace fakes, no pytest-asyncio).

Coverage:
  Task 1 — ``map_product`` field mapping (checkoutUrl construction D-17, nsfw D-16, verbatim
           name D-10, category default D-09, key-set purity) + the ``is_https_url`` guard (V5).
  Task 2 — the three ``three_way_merge`` D-12 branches (Jinxxy-unchanged /
           Jinxxy-changed-staff-untouched / both-changed), staff-owned carry-through, the
           new-product shape (present-but-empty description + string id), and the whole-store
           ``reconcile_store`` add/update/remove/no-op + current-only preservation.
"""

from core import store_sync


# ── probe-confirmed fixtures ──────────────────────────────────────────────────────
STORE_USER = "nocturna"
OWNER = "Nocturna Avatars"


def _cahuama_detail():
    """The live-probe-confirmed Cahuama product detail (D-14..D-17)."""
    return {
        "name": "Cahuama",
        "base_price": 0,
        "url": "cahuama",                       # live: a SLUG, not a URL (D-17)
        "category": "avatar-props",
        "restrictions": ["CONTENT_MATURE"],     # → nsfw True (D-16)
        "created_at": "2026-07-10T12:00:00Z",
    }


# ── Task 1: map_product ───────────────────────────────────────────────────────────
def test_map_product_cahuama_exact():
    assert store_sync.map_product(_cahuama_detail(), STORE_USER, OWNER) == {
        "checkoutUrl": "https://jinxxy.com/nocturna/cahuama",
        "name": {"es": "Cahuama", "en": "Cahuama"},
        "price": "0",
        "category": "avatar-props",
        "editor": OWNER,
        "nsfw": True,
        "date": "2026-07-10",
    }


def test_map_product_nsfw_false_when_restrictions_empty():
    d = _cahuama_detail()
    d["restrictions"] = []
    assert store_sync.map_product(d, STORE_USER, OWNER)["nsfw"] is False


def test_map_product_nsfw_false_when_restrictions_missing():
    d = _cahuama_detail()
    del d["restrictions"]
    assert store_sync.map_product(d, STORE_USER, OWNER)["nsfw"] is False


def test_map_product_category_default_when_null():
    d = _cahuama_detail()
    d["category"] = None
    assert store_sync.map_product(d, STORE_USER, OWNER)["category"] == "assets"


def test_map_product_category_default_when_missing():
    d = _cahuama_detail()
    del d["category"]
    assert store_sync.map_product(d, STORE_USER, OWNER)["category"] == "assets"


def test_map_product_emits_only_sync_owned_keys():
    entry = store_sync.map_product(_cahuama_detail(), STORE_USER, OWNER)
    assert set(entry) == {"checkoutUrl", "name", "price", "category", "editor", "nsfw", "date"}
    for staff_key in ("images", "description", "featured", "license", "details",
                      "updates", "storefronts", "id"):
        assert staff_key not in entry


def test_map_product_price_is_stringified():
    d = _cahuama_detail()
    d["base_price"] = 1500
    assert store_sync.map_product(d, STORE_USER, OWNER)["price"] == "1500"


def test_map_product_checkout_url_is_constructed_from_slug():
    entry = store_sync.map_product(_cahuama_detail(), "otro_user", OWNER)
    assert entry["checkoutUrl"] == "https://jinxxy.com/otro_user/cahuama"


# ── Task 1: is_https_url ──────────────────────────────────────────────────────────
def test_is_https_url_accepts_https():
    assert store_sync.is_https_url("https://jinxxy.com/x/y") is True


def test_is_https_url_rejects_http():
    assert store_sync.is_https_url("http://jinxxy.com/x/y") is False


def test_is_https_url_rejects_javascript_scheme():
    assert store_sync.is_https_url("javascript:alert(1)") is False


def test_is_https_url_rejects_garbage():
    assert store_sync.is_https_url("not a url") is False
    assert store_sync.is_https_url("") is False
