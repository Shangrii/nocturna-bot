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
    import sys
    assert "discord" not in getattr(jinxxy_api, "__dict__", {})
    src = jinxxy_api.__file__
    with open(src, encoding="utf-8") as fh:
        assert "import discord" not in fh.read()
