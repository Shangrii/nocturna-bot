"""Pure heart of the Jinxxy → ``store.json`` sync (Fase 9, plan 09-03).

This module holds ONLY the deterministic, import-safe core of the store sync: the
Jinxxy-detail → ``store.json``-entry mapper, an https-scheme guard for the constructed
checkout URL, the D-12 three-way field-ownership merge, and the whole-store reconcile that
computes adds/updates/removals. There is deliberately **no** Discord code, no ``requests``
call, no DB access and no ``async def setup(bot)`` here — the cog (09-05) orchestrates
snapshot (DB) / live (API) / current (``store.json``) into these functions. Importing this
module has no Discord/network/DB side effects; it imports only the standard library.

Field ownership (interface contract, LOCKED with the Phase-6 ``store.json`` schema):

  SYNC-OWNED   (the merge may write these)  : name, price, checkoutUrl, category, nsfw, date
  STAFF-OWNED  (the merge never sources from live) : id, description, images, featured,
                                                     license, details, updates, storefronts

``name`` is *staff-editable-after-first-write*: once a staff edit diverges from the last-synced
snapshot, staff wins on a Jinxxy conflict (D-10/D-12). The other sync-owned fields let Jinxxy
win on change. ``editor`` is staff-editable (D-09): it is seeded from ``/me`` at creation and
thereafter carried through from the current entry, never re-sourced from live.

Creation exception (D-12/D-15): a brand-new entry is seeded with a generated string ``id`` and
a present-but-empty ``description`` object ``{"es": "", "en": ""}`` — NOT an omitted key —
because ``src/components/sections/StorePage.astro`` (L71-78) drops any product whose
``description`` is not an object. After creation both are staff-owned and never rewritten.
"""

from urllib.parse import urlparse

# Sync-owned fields, in a stable order (drives merge iteration + the changed-field summary).
SYNC_OWNED = ("name", "price", "checkoutUrl", "category", "nsfw", "date")

# On a both-changed conflict these fields yield to the staff edit; the rest let Jinxxy win.
STAFF_WINS_ON_CONFLICT = ("name",)

# Never sourced from ``live`` — carried through from the current entry unchanged (D-12/D-15).
STAFF_OWNED = ("id", "description", "images", "featured", "license", "details",
               "updates", "storefronts")


def map_product(detail: dict, store_username: str, owner_name: str) -> dict:
    """Map a Jinxxy product ``detail`` to the sync-owned subset of a ``store.json`` entry.

    Builds the entry from API-available fields only (live probe D-14..D-17); ``images`` and
    ``description`` (and every other staff-owned key) are deliberately omitted — they are
    staff-owned (D-15) and assigned at creation elsewhere. ``checkoutUrl`` is CONSTRUCTED
    because ``detail['url']`` is a slug, not a URL (D-17); ``nsfw`` derives from the
    ``restrictions`` enum (D-16); ``name`` goes verbatim into both locales (D-10, name only);
    ``category`` falls back to the D-09 default; ``price`` is stringified (the site adds "$ … USD").
    """
    name = detail["name"]
    slug = detail["url"]                                    # a slug e.g. "cahuama" (D-17)
    restrictions = detail.get("restrictions") or []
    return {
        "checkoutUrl": f"https://jinxxy.com/{store_username}/{slug}",  # D-17 link key
        "name": {"es": name, "en": name},                  # verbatim into both (D-10)
        "price": str(detail["base_price"]),                # plain number string, NO $
        "category": detail.get("category") or "assets",    # D-09 default
        "editor": owner_name,                              # from /me (D-09)
        "nsfw": "CONTENT_MATURE" in restrictions,          # D-16 (live-confirmed)
        "date": detail["created_at"][:10],                 # YYYY-MM-DD
        # images{}, description{}, featured/license/details/updates/storefronts/id
        # are NEVER emitted here — staff-owned (D-12/D-15).
    }


def is_https_url(url: str) -> bool:
    """True iff ``url`` parses with an ``https`` scheme and a network location (V5 guard).

    The constructed ``checkoutUrl`` (and any ``storefronts[].url``) must be ``https://`` only
    before it can reach the transport — this rejects ``http://``, ``javascript:`` and any
    malformed/relative input, closing the tampering path T-09-07.
    """
    try:
        parts = urlparse(str(url))
    except (ValueError, TypeError):
        return False
    return parts.scheme == "https" and bool(parts.netloc)


def _id_from_checkout(checkout_url: str) -> str:
    """Derive a stable string ``id`` from a checkout URL (its final path segment / slug).

    ``https://jinxxy.com/nocturna/cahuama`` → ``"cahuama"``. The slug is unique within a
    single storefront (the product page path), so it makes a stable, deterministic id — no
    random UUIDs that would churn on every sync.
    """
    slug = str(checkout_url).rstrip("/").rsplit("/", 1)[-1]
    return slug or str(checkout_url)


def three_way_merge(snapshot: dict | None, live: dict, current: dict | None):
    """Merge one product across (snapshot, live, current) → ``(merged_entry, changed_fields)``.

    ``snapshot`` = the last-synced Jinxxy values (DB, sync-owned fields only), ``live`` = the
    freshly-mapped Jinxxy entry (``map_product`` output), ``current`` = the full ``store.json``
    entry (sync-owned + staff-owned fields). Implements the D-12 field-ownership rules so a
    staff edit is never clobbered (Pitfall 3):

      * Jinxxy unchanged (``live == snapshot``)                    → keep ``current`` (staff edit wins)
      * Jinxxy changed, staff untouched (``current == snapshot``)  → take ``live``
      * both changed                                              → staff wins for ``name`` (D-10),
                                                                    Jinxxy wins for the rest

    ``changed_fields`` lists the sync-owned fields whose merged value differs from ``current``
    (drives the reconcile ``updated`` bucket + the no-op guard). Staff-owned keys are always
    carried through from ``current`` unchanged — never sourced from ``live``.

    Current-absent product (``current is None``): resurrect a COMPLETE entry from ``live``.
    This covers BOTH a brand-new product (``snapshot is None`` — never synced) AND a product
    staff DELETED from ``store.json`` while it is still live on Jinxxy (``snapshot`` present).
    In either case the merged entry is the mapped ``live`` entry PLUS a generated stable string
    ``id`` PLUS a present-but-empty ``description`` object ``{"es": "", "en": ""}`` (REQUIRED —
    StorePage.astro L71-78 drops any product whose ``description`` is not an object). Every other
    staff-owned field stays omitted so the site's per-field fallbacks apply; after creation they
    are staff-owned and the sync never rewrites them. Broadening this guard from the old
    ``snapshot is None and current is None`` closes WR-05: a staff-deleted-while-live product can
    no longer fall through to the field-loop and append an empty/partial ``{}`` into ``products``.
    """
    if current is None:
        merged = dict(live)                       # sync-owned fields + editor from the mapper
        merged["id"] = _id_from_checkout(live["checkoutUrl"])
        merged["description"] = {"es": "", "en": ""}   # present-but-empty (StorePage.astro L71-78)
        return merged, [f for f in SYNC_OWNED if f in merged]

    snapshot = snapshot or {}
    current = current or {}
    merged = dict(current)                         # preserve staff-owned + editor + any extra keys
    changed: list[str] = []
    for field in SYNC_OWNED:
        live_v = live.get(field)
        snap_v = snapshot.get(field)
        cur_v = current.get(field)
        if live_v == snap_v:
            new_v = cur_v                          # Jinxxy unchanged → keep current (staff edit)
        elif cur_v == snap_v:
            new_v = live_v                         # staff untouched → take live
        elif field in STAFF_WINS_ON_CONFLICT:
            new_v = cur_v                          # both changed, staff wins (name, D-10)
        else:
            new_v = live_v                         # both changed, Jinxxy wins (price/etc.)
        if field in merged or new_v is not None:
            merged[field] = new_v
        if new_v != cur_v:
            changed.append(field)
    return merged, changed


def reconcile_store(snapshots: dict, live_by_key: dict, current_by_key: dict) -> dict:
    """Reconcile the whole store keyed by ``checkoutUrl`` → adds/updates/removals + a summary.

    ``snapshots`` = last-synced values per key (DB), ``live_by_key`` = freshly-mapped Jinxxy
    entries per key, ``current_by_key`` = current ``store.json`` entries per key. Returns
    ``{"products", "added", "updated", "removed", "changed"}``.

    Live entries drive the output (preserving Jinxxy's sort order): each is three-way-merged;
    a key absent from both snapshot and current is an ``added``, an existing key whose merge
    reports changed fields is an ``updated``. A current entry ABSENT from live is removed ONLY
    if it had a snapshot (it was synced before, so Jinxxy dropping it is authoritative) —
    a current-only entry with no snapshot (staff-added, never synced) is preserved unchanged
    and never dropped. ``changed`` is True iff anything was added, updated or removed.

    Removal safety (T-09-09): the caller must pass ``live_by_key`` ONLY on a successful full
    Jinxxy enumeration — never on an API error/partial page — so a transient outage can never
    mass-remove the store.
    """
    products: list[dict] = []
    added: list[str] = []
    updated: list[str] = []
    removed: list[str] = []

    for key, live in live_by_key.items():
        snap = snapshots.get(key)
        cur = current_by_key.get(key)
        merged, changed_fields = three_way_merge(snap, live, cur)
        products.append(merged)
        if snap is None and cur is None:
            added.append(key)
        elif changed_fields:
            updated.append(key)

    for key, cur in current_by_key.items():
        if key in live_by_key:
            continue
        if snapshots.get(key) is not None:
            removed.append(key)                    # synced before, now gone from Jinxxy → drop
        else:
            products.append(cur)                   # staff-added, never synced → preserve

    return {
        "products": products,
        "added": added,
        "updated": updated,
        "removed": removed,
        "changed": bool(added or updated or removed),
    }
