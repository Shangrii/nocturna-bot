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
