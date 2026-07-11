"""Jinxxy Creator API read client for the store auto-sync (Fase 9, STORE-SYNC-01).

A thin, pure, ``requests``-based READ client the store sync depends on. It enumerates the
storefront (``list_all_products``), fetches each product's rich detail (``get_product``),
and reads ``/me`` for the store username (checkoutUrl construction, D-17) + owner display
name (``editor`` default, D-09). It imports only stdlib + ``requests`` + ``config`` — no
``discord`` — so the whole client is unit-testable with HTTP mocked, exactly like
``core/github_publish.py`` (which this deliberately mirrors: header-only secret, explicit
timeout, one typed error, secret never logged).

Locked decisions implemented here:
  * D-04 — the Creator API is the ONLY source; there is no scraping fallback.
  * D-14 — the reduced field set the live probe confirmed (name, base_price, currency_code,
    category, tags, restrictions, visibility, url, created_at, ...). ``images`` and
    ``description`` are NOT available from the API and are never fabricated here.
  * D-17 — ``url`` is a SLUG (e.g. "cahuama"), not a URL; the checkoutUrl is CONSTRUCTED
    downstream from the ``/me`` store username + the slug (this module just returns them).

Security / resilience contract (STRIDE T-09-03..T-09-06):
  * The ``x-api-key`` secret is read from ``config`` at call time and placed ONLY in a
    request header — never logged, never interpolated into an error or a commit.
  * Every call carries an explicit ``_TIMEOUT``; ``requests`` has no default, so an
    unbounded connection could otherwise hang the sync loop forever.
  * All ``requests`` failures are converted to a single typed ``JinxxyAPIError`` whose
    message names ONLY ``exc.__class__.__name__`` — never ``str(exc)`` or the url/key.
  * A 429 backs off (honoring ``Retry-After`` as a delta / ``X-RateLimit-Reset`` as an
    epoch when present, else a bounded exponential backoff) and retries a small number of
    times, then raises. EVERY branch is clamped to ``_MAX_BACKOFF`` so an untrusted server
    header can never drive an unbounded ``time.sleep`` that freezes the sync (CR-02).
  * No read path ever swallows a failure into an empty list: an outage raises, so the cog
    can treat it as "unknown" and never mistake it for "the storefront is empty" (T-09-05).
"""

import logging
import time

import requests

import config

log = logging.getLogger(__name__)

_BASE = "https://api.creators.jinxxy.com/v1"
# (connect, read) seconds — requests has NO default timeout; a black-holed connection would
# otherwise hang the whole sync loop (mirrors github_publish._TIMEOUT, CR-02).
_TIMEOUT = (10, 60)

_PAGE_LIMIT = 100                   # max page size the Creator API accepts
_RATELIMIT_STATUS = 429
_MAX_RETRIES = 4                    # 429 backoff attempts before giving up
_BACKOFF_BASE = 0.5                 # seconds; exponential: 0.5, 1.0, 2.0, 4.0 ...
_MAX_BACKOFF = 60.0                 # seconds — never trust a server hint beyond this (CR-02)


class JinxxyAPIError(RuntimeError):
    """Raised when a Creator API read cannot be completed (network, non-2xx, or 429 exhaust).

    Mirrors ``GitHubPublishError``: the caller (cog) logs it — errors NEVER reach Discord
    (D-05). The message never carries the api_key, the url, or ``str(exc)``.
    """


# ── low-level helpers ───────────────────────────────────────────────────────────────
def _headers(api_key=None):
    # Key read at call time (so config/.env changes and tests take effect); never logged.
    return {"x-api-key": api_key or config.JINXXY_API_KEY}


def _ok(resp):
    return 200 <= resp.status_code < 300


def _require(resp, what):
    """Log the endpoint label + status (never the key) and raise on a non-2xx response."""
    log.debug("jinxxy %s -> HTTP %s", what, resp.status_code)
    if not _ok(resp):
        raise JinxxyAPIError(f"{what} failed: HTTP {resp.status_code}")
    return resp


def _http(method, url, what, headers=None, **kw):
    """Issue one HTTP request, keeping the typed-error contract airtight.

    Only the exception CLASS NAME is interpolated (never ``str(exc)``) so a url or the
    api_key can never leak into the error text or the logs. Every call carries an explicit
    ``_TIMEOUT`` so a timeout raises ``requests.Timeout`` -> ``JinxxyAPIError`` instead of
    hanging the sync loop.
    """
    kw.setdefault("timeout", _TIMEOUT)
    try:
        return getattr(requests, method)(url, headers=headers, **kw)
    except requests.RequestException as exc:
        raise JinxxyAPIError(
            f"{what} failed: network error ({exc.__class__.__name__})") from exc


def _retry_delay(resp, attempt):
    """Seconds to wait before retrying a 429 — ALWAYS clamped to ``_MAX_BACKOFF``.

    Every branch is bounded so an untrusted server (or proxy) header can never drive an
    unbounded ``time.sleep`` that freezes the sync thread (CR-02, T-09-08-01/02):

      * ``Retry-After`` is a DELTA in seconds — clamp ``min(_MAX_BACKOFF, max(0.0, value))``.
      * ``X-RateLimit-Reset`` is a unix EPOCH timestamp — convert to a delta via
        ``value - time.time()`` first, then clamp (a far-future epoch would otherwise be
        mis-read as a multi-decade delta; a past epoch clamps up to ``0.0``). These two
        headers are handled in SEPARATE branches for exactly this reason.
      * No usable / malformed header falls through to the bounded exponential backoff,
        itself clamped to ``_MAX_BACKOFF``.
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return min(_MAX_BACKOFF, max(0.0, float(retry_after)))
        except (TypeError, ValueError):
            pass
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset is not None:
        try:
            # epoch semantics: convert to a delta from now, then clamp
            return min(_MAX_BACKOFF, max(0.0, float(reset) - time.time()))
        except (TypeError, ValueError):
            pass
    return min(_MAX_BACKOFF, _BACKOFF_BASE * (2 ** attempt))


def _get(path, what, api_key=None, params=None):
    """GET one Creator API endpoint with header auth, explicit timeout, and 429 backoff.

    Retries a bounded number of times on 429 (backing off per ``_retry_delay``); any other
    non-2xx or a transport failure raises ``JinxxyAPIError`` immediately. Never returns a
    non-2xx response to the caller.
    """
    url = f"{_BASE}{path}"
    headers = _headers(api_key)
    attempt = 0
    while True:
        resp = _http("get", url, what, headers=headers, params=params)
        if resp.status_code == _RATELIMIT_STATUS and attempt < _MAX_RETRIES:
            delay = _retry_delay(resp, attempt)
            log.warning("jinxxy %s -> HTTP 429, backing off %.1fs (retry %d/%d)",
                        what, delay, attempt + 1, _MAX_RETRIES)
            time.sleep(delay)
            attempt += 1
            continue
        return _require(resp, what)


# ── public read client ──────────────────────────────────────────────────────────────
def get_me(api_key=None) -> dict:
    """GET ``/me`` — the authenticated creator (store username + display name).

    Needed for D-17 (checkoutUrl = ``jinxxy.com/{username}/{slug}``) and D-09 (``editor``
    default = the owner display name). Fetched once per sync and passed into the mapper.
    """
    return _get("/me", "GET /me", api_key=api_key).json()


def list_all_products(api_key=None) -> list[dict]:
    """Enumerate EVERY storefront product across all pages, newest first.

    Follows pagination (``page`` from 1 until ``page >= page_count``) with ``limit=100`` and
    ``sort_field=created_at&sort_order=desc``, concatenating every page's ``results``. These
    are the light list records; call :func:`get_product` for the rich per-product detail.

    Never returns a partial or empty list on error: any unrecoverable failure raises
    ``JinxxyAPIError`` so the cog treats an outage as "unknown", never "storefront is empty"
    (T-09-05 removal-safety).
    """
    products: list[dict] = []
    page = 1
    while True:
        body = _get(
            "/products", "GET /products", api_key=api_key,
            params={"page": page, "limit": _PAGE_LIMIT,
                    "sort_field": "created_at", "sort_order": "desc"},
        ).json()
        products.extend(body.get("results") or [])
        page_count = body.get("page_count") or 1
        if page >= page_count:
            return products
        page += 1


def get_product(product_id, api_key=None) -> dict:
    """GET ``/products/{id}`` — the rich detail record for one product (D-14 field set)."""
    what = f"GET /products/{product_id}"
    return _get(f"/products/{product_id}", what, api_key=api_key).json()
