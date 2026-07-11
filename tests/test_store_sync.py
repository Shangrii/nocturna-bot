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


# ── Task 2: three_way_merge + reconcile_store fixtures ─────────────────────────────
def _entry(name="Cahuama", price="0", url="https://jinxxy.com/nocturna/cahuama",
           category="avatar-props", nsfw=True, date="2026-07-10", editor=OWNER, **extra):
    """A full store.json product entry (sync-owned fields + any staff-owned extras)."""
    e = {
        "checkoutUrl": url,
        "name": {"es": name, "en": name},
        "price": price,
        "category": category,
        "editor": editor,
        "nsfw": nsfw,
        "date": date,
    }
    e.update(extra)
    return e


# ── Task 2: three_way_merge (D-12 branches) ───────────────────────────────────────
def test_merge_jinxxy_unchanged_keeps_current():
    # live == snapshot (Jinxxy didn't change) → a staff-edited current value is preserved.
    snapshot = _entry(price="10")
    live = _entry(price="10")
    current = _entry(price="99")            # staff edit
    merged, changed = store_sync.three_way_merge(snapshot, live, current)
    assert merged["price"] == "99"
    assert "price" not in changed


def test_merge_jinxxy_changed_staff_untouched_takes_live():
    snapshot = _entry(price="10")
    live = _entry(price="20")               # Jinxxy changed
    current = _entry(price="10")            # staff never touched (== snapshot)
    merged, changed = store_sync.three_way_merge(snapshot, live, current)
    assert merged["price"] == "20"
    assert "price" in changed


def test_merge_both_changed_name_staff_wins():
    snapshot = _entry(name="Old")
    live = _entry(name="JinxxyNew")         # Jinxxy changed
    current = _entry(name="StaffName")      # staff also changed
    merged, changed = store_sync.three_way_merge(snapshot, live, current)
    assert merged["name"] == {"es": "StaffName", "en": "StaffName"}   # staff wins (D-10)
    assert "name" not in changed


def test_merge_both_changed_price_jinxxy_wins():
    snapshot = _entry(price="10")
    live = _entry(price="20")               # Jinxxy changed
    current = _entry(price="15")            # staff also changed
    merged, changed = store_sync.three_way_merge(snapshot, live, current)
    assert merged["price"] == "20"          # Jinxxy wins for a pure sync-owned field
    assert "price" in changed


def test_merge_carries_staff_owned_keys_untouched():
    snapshot = _entry()
    live = _entry()
    current = _entry(
        description={"es": "hola", "en": "hello"},
        images=["/store/a.webp"],
        featured=True,
        license={"es": "L", "en": "L"},
        details={"es": "d", "en": "d"},
        updates={"es": "u", "en": "u"},
        storefronts=[{"platform": "booth", "url": "https://booth.pm/en/items/1"}],
        id="cahuama",
    )
    merged, _ = store_sync.three_way_merge(snapshot, live, current)
    assert merged["description"] == {"es": "hola", "en": "hello"}
    assert merged["images"] == ["/store/a.webp"]
    assert merged["featured"] is True
    assert merged["license"] == {"es": "L", "en": "L"}
    assert merged["details"] == {"es": "d", "en": "d"}
    assert merged["updates"] == {"es": "u", "en": "u"}
    assert merged["storefronts"] == [{"platform": "booth", "url": "https://booth.pm/en/items/1"}]
    assert merged["id"] == "cahuama"


def test_merge_never_sources_staff_fields_from_live():
    # live carries a hostile description/images/featured; the merge must ignore them entirely.
    snapshot = _entry()
    live = dict(_entry())
    live["description"] = {"es": "EVIL", "en": "EVIL"}
    live["images"] = ["http://evil/x.png"]
    live["featured"] = True
    current = _entry(description={"es": "ok", "en": "ok"})
    merged, _ = store_sync.three_way_merge(snapshot, live, current)
    assert merged["description"] == {"es": "ok", "en": "ok"}
    assert "images" not in merged
    assert "featured" not in merged


def test_merge_new_product_seeds_id_and_empty_description():
    live = _entry()                          # a freshly-mapped entry
    merged, _ = store_sync.three_way_merge(None, live, None)
    # present-but-empty description object — NOT an omitted key (StorePage.astro L71-78)
    assert merged["description"] == {"es": "", "en": ""}
    assert isinstance(merged["id"], str) and merged["id"]
    # sync-owned fields flow through from the mapped live entry
    assert merged["name"] == {"es": "Cahuama", "en": "Cahuama"}
    assert merged["checkoutUrl"] == live["checkoutUrl"]
    assert merged["price"] == "0"
    # all OTHER staff-owned fields stay omitted so the site's per-field fallbacks apply
    for staff_key in ("images", "featured", "license", "details", "updates", "storefronts"):
        assert staff_key not in merged


# ── Task 2: reconcile_store (add / update / remove / no-op / current-only) ─────────
def test_reconcile_add():
    url = "https://jinxxy.com/nocturna/new"
    res = store_sync.reconcile_store({}, {url: _entry(url=url)}, {})
    assert url in res["added"]
    assert res["updated"] == []
    assert res["removed"] == []
    assert res["changed"] is True
    assert len(res["products"]) == 1


def test_reconcile_preserves_current_only_entry():
    url = "https://jinxxy.com/nocturna/manual"
    manual = _entry(url=url, name="Manual")          # staff-added, never synced
    res = store_sync.reconcile_store({}, {}, {url: manual})
    assert manual in res["products"]                 # never dropped
    assert res["removed"] == []
    assert res["changed"] is False


def test_reconcile_remove():
    url = "https://jinxxy.com/nocturna/gone"
    res = store_sync.reconcile_store({url: _entry(url=url)}, {}, {url: _entry(url=url)})
    assert url in res["removed"]
    assert all(p.get("checkoutUrl") != url for p in res["products"])
    assert res["changed"] is True


def test_reconcile_update():
    url = "https://jinxxy.com/nocturna/cahuama"
    res = store_sync.reconcile_store(
        {url: _entry(url=url, price="10")},
        {url: _entry(url=url, price="20")},          # Jinxxy raised the price
        {url: _entry(url=url, price="10")},          # staff untouched
    )
    assert url in res["updated"]
    assert res["added"] == []
    assert res["removed"] == []
    assert res["changed"] is True
    assert res["products"][0]["price"] == "20"


def test_reconcile_no_op():
    url = "https://jinxxy.com/nocturna/cahuama"
    res = store_sync.reconcile_store(
        {url: _entry(url=url)},
        {url: _entry(url=url)},
        {url: _entry(url=url)},
    )
    assert res["added"] == []
    assert res["updated"] == []
    assert res["removed"] == []
    assert res["changed"] is False
    assert len(res["products"]) == 1
