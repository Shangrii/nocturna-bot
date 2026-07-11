"""Behaviour tests for the Jinxxy Creator API read client (Fase 9, STORE-SYNC-01).

These pin the contract of ``core.jinxxy_api`` — the thin, pure, ``requests``-based read
client the store sync depends on: ``get_me`` (store username + owner name), paginated
``list_all_products``, per-product ``get_product``, header-only ``x-api-key`` auth, an
explicit timeout on every call, one typed ``JinxxyAPIError`` for all network failures, and
bounded 429 backoff. It imports only stdlib + ``requests`` + ``config`` (no ``discord``), so
the whole thing is unit-testable with HTTP mocked — mirroring ``test_reviews_publish.py``.

Contract asserted here:
  * ``get_me`` GETs ``/me`` with ``x-api-key: <key>`` and returns the parsed dict
  * every request carries an explicit timeout (a ``requests.Timeout`` becomes a typed error)
  * a ``requests.RequestException`` becomes ONE ``JinxxyAPIError`` naming only the exc class
  * the api_key never reaches logs and never appears in an error message
  * a non-2xx response raises ``JinxxyAPIError`` with the endpoint label + status (never key)
  * ``list_all_products`` follows pagination, sends ``limit/sort_*`` params, concatenates
  * ``get_product`` GETs ``/products/{id}`` and returns the detail dict
  * a transient 429 backs off (patched sleep) and recovers; a persistent 429 raises
  * an error mid-pagination raises — the function never masks a failure as an empty list
"""

import logging
import time

import pytest
import requests

import config
from core import jinxxy_api


FAKE_KEY = "jinxxy_secret_key_should_never_be_logged_abc123"
_BASE = "https://api.creators.jinxxy.com/v1"


# ── programmable fake Jinxxy Creator API ───────────────────────────────────────────
class _Resp:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.headers = headers or {}

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


class FakeJinxxy:
    """Records every GET and answers each Creator API endpoint with canned JSON.

    ``list_statuses`` / ``me_statuses`` are queues of status codes returned by successive
    ``/products`` (list) / ``/me`` calls (default ``[200]``) so tests can inject a 429 then
    a 200, or a persistent 5xx. ``pages`` maps a 1-based page number -> a page body
    ``{"results": [...], "page_count": N}``.
    """

    def __init__(self, me=None, product=None, pages=None, list_statuses=None, me_statuses=None):
        self.me = me if me is not None else {"username": "nocturna", "display_name": "Nocturna"}
        self.product = product if product is not None else {"id": "p1", "name": "Cahuama", "url": "cahuama"}
        self.pages = pages
        self.calls = []            # (method, url, headers, params)
        self.timeouts = []         # the timeout kwarg of every call
        self._list_statuses = list(list_statuses or [])
        self._me_statuses = list(me_statuses or [])

    def get(self, url, headers=None, params=None, **kw):
        self.calls.append(("GET", url, headers, params))
        self.timeouts.append(kw.get("timeout"))
        if url.endswith("/me"):
            status = self._me_statuses.pop(0) if self._me_statuses else 200
            return _Resp(status, self.me, headers={"Retry-After": "0"})
        if "/products/" in url:
            return _Resp(200, self.product)
        if url.endswith("/products"):
            status = self._list_statuses.pop(0) if self._list_statuses else 200
            if status != 200:
                return _Resp(status, {}, headers={"Retry-After": "0"})
            page = (params or {}).get("page", 1)
            if self.pages is not None:
                body = self.pages[page]
            else:
                body = {"results": [{"id": f"p{page}"}], "page_count": 1}
            return _Resp(200, body)
        raise AssertionError(f"unexpected GET {url}")

    # -- assertion helpers --------------------------------------------------------
    def list_calls(self):
        return [c for c in self.calls if c[1].endswith("/products")]


@pytest.fixture
def wire(monkeypatch):
    """Install the fake HTTP layer + deterministic config, silence backoff sleeps.

    Returns an ``install(fake)`` callable so each test can build its own FakeJinxxy.
    """
    monkeypatch.setattr(config, "JINXXY_API_KEY", FAKE_KEY)
    monkeypatch.setattr(jinxxy_api.time, "sleep", lambda *_a, **_k: None)

    def install(fake):
        monkeypatch.setattr(jinxxy_api.requests, "get", fake.get)
        return fake

    return install


# ── Task 1: /me, header, timeout, typed errors, key-not-logged ─────────────────────
def test_get_me_uses_api_key_header_and_returns_dict(wire):
    fake = wire(FakeJinxxy(me={"username": "nocturna", "display_name": "Nocturna Team"}))

    result = jinxxy_api.get_me()

    assert result == {"username": "nocturna", "display_name": "Nocturna Team"}
    method, url, headers, params = fake.calls[0]
    assert url == f"{_BASE}/me"
    assert headers["x-api-key"] == FAKE_KEY


def test_get_me_accepts_an_explicit_api_key_argument(wire):
    fake = wire(FakeJinxxy())

    jinxxy_api.get_me(api_key="override_key_xyz")

    _, _, headers, _ = fake.calls[0]
    assert headers["x-api-key"] == "override_key_xyz"


def test_every_call_carries_an_explicit_timeout(wire):
    fake = wire(FakeJinxxy())

    jinxxy_api.get_me()

    assert fake.timeouts, "no HTTP calls were recorded"
    assert all(t not in (None, 0) for t in fake.timeouts)


def test_timeout_becomes_a_typed_error_not_a_hang(wire, monkeypatch):
    wire(FakeJinxxy())

    def boom(url, headers=None, **kw):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(jinxxy_api.requests, "get", boom)
    with pytest.raises(jinxxy_api.JinxxyAPIError):
        jinxxy_api.get_me()


def test_network_error_becomes_one_typed_error_naming_only_the_class(wire, monkeypatch):
    wire(FakeJinxxy())

    def boom(url, headers=None, **kw):
        # str(exc) deliberately carries the url + key-ish text to prove it never leaks
        raise requests.ConnectionError(f"failed to connect to {url} with {FAKE_KEY}")

    monkeypatch.setattr(jinxxy_api.requests, "get", boom)
    with pytest.raises(jinxxy_api.JinxxyAPIError) as ei:
        jinxxy_api.get_me()

    msg = str(ei.value)
    assert "ConnectionError" in msg          # only the class name is interpolated
    assert FAKE_KEY not in msg               # str(exc) is NEVER interpolated
    assert _BASE not in msg                  # the url never leaks either


def test_api_key_is_never_written_to_logs(wire, caplog):
    wire(FakeJinxxy())

    with caplog.at_level(logging.DEBUG):
        jinxxy_api.get_me()

    assert FAKE_KEY not in caplog.text


def test_non_2xx_raises_typed_error_with_status_not_key(wire):
    wire(FakeJinxxy(me_statuses=[500]))

    with pytest.raises(jinxxy_api.JinxxyAPIError) as ei:
        jinxxy_api.get_me()

    msg = str(ei.value)
    assert "500" in msg
    assert FAKE_KEY not in msg


def test_module_imports_no_discord():
    # The client stays pure: importing it must never pull in discord.
    assert "discord" not in getattr(jinxxy_api, "__dict__", {})
    src = jinxxy_api.__file__
    with open(src, encoding="utf-8") as fh:
        assert "import discord" not in fh.read()


# ── Task 2: paginated list_all_products, get_product, 429 backoff ──────────────────
def test_list_all_products_follows_pagination_and_concatenates(wire):
    pages = {
        1: {"results": [{"id": "a"}, {"id": "b"}], "page_count": 3},
        2: {"results": [{"id": "c"}], "page_count": 3},
        3: {"results": [{"id": "d"}], "page_count": 3},
    }
    fake = wire(FakeJinxxy(pages=pages))

    result = jinxxy_api.list_all_products()

    assert len(fake.list_calls()) == 3                       # one GET /products per page
    assert [p["id"] for p in result] == ["a", "b", "c", "d"]  # every page's results, in order


def test_list_all_products_sends_expected_query_params_and_header(wire):
    fake = wire(FakeJinxxy(pages={1: {"results": [], "page_count": 1}}))

    jinxxy_api.list_all_products()

    _, url, headers, params = fake.list_calls()[0]
    assert url == f"{_BASE}/products"
    assert params["limit"] == 100
    assert params["sort_field"] == "created_at"
    assert params["sort_order"] == "desc"
    assert params["page"] == 1
    assert headers["x-api-key"] == FAKE_KEY


def test_get_product_hits_detail_endpoint_and_returns_dict(wire):
    fake = wire(FakeJinxxy(product={"id": "p9", "name": "Cahuama", "url": "cahuama"}))

    result = jinxxy_api.get_product("p9")

    assert result == {"id": "p9", "name": "Cahuama", "url": "cahuama"}
    _, url, headers, _ = fake.calls[0]
    assert url == f"{_BASE}/products/p9"
    assert headers["x-api-key"] == FAKE_KEY


def test_transient_429_backs_off_then_succeeds(wire, monkeypatch):
    sleeps = []
    monkeypatch.setattr(jinxxy_api.time, "sleep", lambda s, *_a, **_k: sleeps.append(s))
    fake = wire(FakeJinxxy(pages={1: {"results": [{"id": "x"}], "page_count": 1}},
                           list_statuses=[429, 200]))

    result = jinxxy_api.list_all_products()

    assert sleeps, "backoff sleep was never invoked on a 429"
    assert [p["id"] for p in result] == ["x"]                # recovered on the retry
    assert len(fake.list_calls()) == 2                       # 429 then the successful retry


def test_persistent_429_eventually_raises_typed_error(wire):
    wire(FakeJinxxy(pages={1: {"results": [], "page_count": 1}},
                    list_statuses=[429, 429, 429, 429, 429, 429, 429]))

    with pytest.raises(jinxxy_api.JinxxyAPIError):
        jinxxy_api.list_all_products()


def test_mid_pagination_error_raises_never_returns_partial_or_empty(wire, monkeypatch):
    # page 1 succeeds (page_count=2); page 2's transport dies. The function must raise —
    # never return the partial [a] and never a silent [] (T-09-05 removal-safety).
    fake = wire(FakeJinxxy(pages={1: {"results": [{"id": "a"}], "page_count": 2}}))
    real_get = fake.get

    def flaky_get(url, headers=None, params=None, **kw):
        if url.endswith("/products") and (params or {}).get("page") == 2:
            raise requests.ConnectionError("connection reset mid-pagination")
        return real_get(url, headers=headers, params=params, **kw)

    monkeypatch.setattr(jinxxy_api.requests, "get", flaky_get)
    with pytest.raises(jinxxy_api.JinxxyAPIError):
        jinxxy_api.list_all_products()


# ── CR-02: _retry_delay is clamped; epoch reset is a delta, never an unbounded sleep ──
def test_retry_delay_clamps_a_huge_retry_after_to_max_backoff():
    # Retry-After is a delta in seconds; a hostile/huge value must clamp to the cap,
    # never drive time.sleep() for ~11 days (CR-02, T-09-08-01).
    resp = _Resp(429, {}, headers={"Retry-After": "999999"})

    delay = jinxxy_api._retry_delay(resp, attempt=0)

    assert delay == jinxxy_api._MAX_BACKOFF
    assert delay <= jinxxy_api._MAX_BACKOFF


def test_retry_delay_treats_x_ratelimit_reset_as_epoch_and_clamps():
    # X-RateLimit-Reset is a unix epoch timestamp, NOT a delta: a far-future epoch must
    # be converted via `- time.time()` and then clamped — never a multi-decade sleep
    # (CR-02, T-09-08-02).
    far_future_epoch = time.time() + 10 ** 9   # ~31 years out
    resp = _Resp(429, {}, headers={"X-RateLimit-Reset": str(far_future_epoch)})

    delay = jinxxy_api._retry_delay(resp, attempt=0)

    assert delay == jinxxy_api._MAX_BACKOFF


def test_retry_delay_epoch_reset_in_the_past_is_never_negative():
    # A reset timestamp at (or before) now yields a non-negative, sub-cap delay.
    resp = _Resp(429, {}, headers={"X-RateLimit-Reset": str(time.time() - 5)})

    delay = jinxxy_api._retry_delay(resp, attempt=0)

    assert 0.0 <= delay <= jinxxy_api._MAX_BACKOFF


def test_retry_delay_small_retry_after_is_unchanged_below_the_cap():
    # A small valid Retry-After passes through unchanged (behaviour below the cap).
    resp = _Resp(429, {}, headers={"Retry-After": "2"})

    assert jinxxy_api._retry_delay(resp, attempt=0) == 2.0


def test_retry_delay_malformed_header_falls_through_to_clamped_backoff():
    # A malformed header value falls through to the exponential fallback, itself clamped.
    resp = _Resp(429, {}, headers={"Retry-After": "not-a-number"})

    delay = jinxxy_api._retry_delay(resp, attempt=2)

    # fallback = _BACKOFF_BASE * 2**2 = 2.0, still <= cap
    assert delay == jinxxy_api._BACKOFF_BASE * (2 ** 2)
    assert delay <= jinxxy_api._MAX_BACKOFF


def test_retry_delay_fallback_is_clamped_at_high_attempts():
    # With no server hint, a large attempt exponent must still clamp to the cap.
    resp = _Resp(429, {}, headers={})

    assert jinxxy_api._retry_delay(resp, attempt=20) == jinxxy_api._MAX_BACKOFF
