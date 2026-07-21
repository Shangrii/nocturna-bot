"""Behaviour tests for the editor admin app auth core (Fase 10, plan 10-08).

Pins the security-critical trust boundary the admin app establishes BEFORE any editing
UI exists (EDIT-04/EDIT-05):

Task 1 — ``app/auth.py``:
  * ``has_editor_role`` reads the guild member with the **BOT token** header
    (``Authorization: Bot {BOT_TOKEN}``), never an OAuth user token, and returns True
    ONLY when the mocked roles include ``ROLE_MODERATOR_ID`` (D-07/D-15).
  * the OAuth ``callback`` with a valid code + editor role sets the session identity
    (``discord_id`` + ``slug``) and redirects to a FIXED internal path — never a
    client-supplied ``?next`` (open-redirect guard, Pitfall 4).
  * a valid code but NO editor role → 403 and NO session issued (T-10-08-06).
  * a bad/missing OAuth ``state`` (Authlib ``OAuthError``) → rejected, no session
    (CSRF guard, Pitfall 4 / T-10-08-01).
  * first login for a never-seen ``discordId`` creates an empty draft (``published:false``,
    empty ``blocks``) with a normalized unique slug; a slug collision appends a numeric
    suffix (D-09 / Pitfall 5).

Task 2 — ``app/main.py`` + ``app/deps.py``:
  * ``require_editor`` reads identity from ``request.session`` ONLY (401 without a
    session); it never reads slug/discordId from a body (D-08 IDOR).
  * ``require_editor`` re-checks the role each call and clears the session + 403s on
    role revocation (Pitfall 2 stale-session guard).
  * ``validate_config`` fails fast when ``SESSION_SECRET`` / OAuth config is empty.

Everything network/OAuth is mocked; the async handlers are driven with ``asyncio.run``
(no pytest-asyncio dependency needed — mirrors the existing cog/transport test suites).
No real bot token, client secret, or OAuth code is ever used or asserted-present in output.
"""

import asyncio
import re

import pytest
from authlib.integrations.starlette_client import OAuthError
from fastapi import HTTPException

import config
from app import auth


# ── fakes ─────────────────────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _make_fake_client(status_code, payload, sink):
    """A stand-in for ``httpx.AsyncClient`` that records every GET (url + headers)."""

    class _FakeAsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            sink.append({"url": url, "headers": dict(headers or {})})
            return _FakeResp(status_code, payload)

    return _FakeAsyncClient


class _FakeRequest:
    """Minimal Starlette-Request stand-in: a mutable ``session`` dict + a hostile
    ``?next`` query param that a correct callback must ignore (open-redirect guard)."""

    def __init__(self):
        self.session = {}
        self.query_params = {"next": "https://evil.example/pwn"}


# ── Task 1: has_editor_role — the bot-token role gate (D-07/D-15) ──────────────────
def test_has_editor_role_true_only_when_role_present_and_uses_bot_token(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "test-bot-token")
    monkeypatch.setattr(config, "GUILD_ID", 999)
    monkeypatch.setattr(config, "ROLE_MODERATOR_ID", 42)
    sink = []
    monkeypatch.setattr(
        auth.httpx, "AsyncClient",
        _make_fake_client(200, {"roles": ["42", "7"]}, sink))

    assert asyncio.run(auth.has_editor_role("123")) is True

    call = sink[0]
    # The BOT token, never the OAuth user token (T-10-08-05).
    assert call["headers"]["Authorization"] == "Bot test-bot-token"
    assert "/guilds/999/members/123" in call["url"]


def test_has_editor_role_false_when_role_absent(monkeypatch):
    monkeypatch.setattr(config, "ROLE_MODERATOR_ID", 42)
    sink = []
    monkeypatch.setattr(
        auth.httpx, "AsyncClient",
        _make_fake_client(200, {"roles": ["7", "8"]}, sink))
    assert asyncio.run(auth.has_editor_role("123")) is False


def test_has_editor_role_false_when_not_a_guild_member(monkeypatch):
    # A 404 (user not in the guild) is a clean "no", not an exception.
    sink = []
    monkeypatch.setattr(
        auth.httpx, "AsyncClient",
        _make_fake_client(404, {"message": "Unknown Member"}, sink))
    assert asyncio.run(auth.has_editor_role("123")) is False


# ── Task 1: ensure_draft — first-login auto-draft + slug uniqueness (D-09/Pitfall 5)
def test_ensure_draft_creates_empty_unique_draft(monkeypatch):
    committed = {}

    async def fake_fetch():
        return []

    async def fake_sync(entry, images=(), *, message=None):
        committed["entry"] = entry
        return {"committed": True, "commit_sha": "abc", "slug": entry["slug"]}

    monkeypatch.setattr(auth, "_fetch_editors", fake_fetch)
    monkeypatch.setattr(auth.github_publish, "sync_editors", fake_sync)

    entry = asyncio.run(auth.ensure_draft("555", "Aria"))

    assert entry["discordId"] == "555"
    assert entry["published"] is False
    assert entry["blocks"] == []
    assert entry["slug"] == "aria"
    # committed via sync_editors with the same entry
    assert committed["entry"]["slug"] == "aria"
    assert committed["entry"]["discordId"] == "555"


def test_ensure_draft_appends_numeric_suffix_on_slug_collision(monkeypatch):
    existing = [{"discordId": "111", "slug": "aria", "published": True}]

    async def fake_fetch():
        return existing

    async def fake_sync(entry, images=(), *, message=None):
        return {"committed": True}

    monkeypatch.setattr(auth, "_fetch_editors", fake_fetch)
    monkeypatch.setattr(auth.github_publish, "sync_editors", fake_sync)

    entry = asyncio.run(auth.ensure_draft("555", "Aria"))
    assert entry["slug"] == "aria-2"


def test_ensure_draft_returns_existing_entry_without_committing(monkeypatch):
    existing = [{"discordId": "555", "slug": "aria", "published": True, "blocks": []}]
    sync_calls = []

    async def fake_fetch():
        return existing

    async def fake_sync(*a, **k):
        sync_calls.append(1)
        return {}

    monkeypatch.setattr(auth, "_fetch_editors", fake_fetch)
    monkeypatch.setattr(auth.github_publish, "sync_editors", fake_sync)

    entry = asyncio.run(auth.ensure_draft("555", "whatever-new-name"))
    assert entry["slug"] == "aria"
    assert sync_calls == []  # a returning editor never triggers a fresh commit


def test_ensure_draft_falls_back_when_username_has_no_slug_chars(monkeypatch):
    # A username that normalizes to empty (all punctuation) must not raise — it falls
    # back to a discord-id-derived slug (Pitfall 5: never let a bad slug crash login).
    async def fake_fetch():
        return []

    async def fake_sync(entry, images=(), *, message=None):
        return {"committed": True}

    monkeypatch.setattr(auth, "_fetch_editors", fake_fetch)
    monkeypatch.setattr(auth.github_publish, "sync_editors", fake_sync)

    entry = asyncio.run(auth.ensure_draft("555", "!!!"))
    assert entry["slug"]  # non-empty, charset-valid
    assert "555" in entry["slug"]


def test_ensure_draft_seeds_random_media_id(monkeypatch):
    import asyncio
    from app import auth

    captured = {}

    async def fake_fetch_editors():
        return []

    async def fake_sync(entry, *a, **k):
        captured["entry"] = entry
        return {"committed": True, "commit_sha": "x", "slug": entry["slug"], "files": []}

    monkeypatch.setattr(auth, "_fetch_editors", fake_fetch_editors)
    monkeypatch.setattr(auth.github_publish, "sync_editors", fake_sync)

    result = asyncio.run(auth.ensure_draft("999888777", "NewEditor"))

    assert re.fullmatch(r"[0-9a-f]{16}", result["mediaId"])
    assert captured["entry"]["mediaId"] == result["mediaId"]


# ── Task 1: callback — the OAuth trust boundary (D-07/D-08/D-09, Pitfall 4) ─────────
def _patch_callback_happy(monkeypatch, *, role: bool):
    async def fake_exchange(request):
        return {"access_token": "x"}

    async def fake_user(token):
        return {"id": "555", "username": "Aria"}

    async def fake_role(uid):
        return role

    async def fake_draft(uid, username):
        return {"slug": "aria", "discordId": uid, "published": False, "blocks": []}

    monkeypatch.setattr(auth, "_exchange_token", fake_exchange)
    monkeypatch.setattr(auth, "_fetch_user", fake_user)
    monkeypatch.setattr(auth, "has_editor_role", fake_role)
    monkeypatch.setattr(auth, "ensure_draft", fake_draft)


def test_callback_valid_editor_sets_session_and_fixed_redirect(monkeypatch):
    _patch_callback_happy(monkeypatch, role=True)
    req = _FakeRequest()

    resp = asyncio.run(auth.callback(req))

    assert req.session["discord_id"] == "555"
    assert req.session["slug"] == "aria"
    assert resp.status_code in (302, 303, 307)
    # FIXED internal path — never the client-supplied ?next (open-redirect guard).
    assert resp.headers["location"] == auth.POST_LOGIN_REDIRECT
    assert "evil.example" not in resp.headers["location"]


def test_callback_non_editor_403_and_no_session(monkeypatch):
    _patch_callback_happy(monkeypatch, role=False)
    req = _FakeRequest()

    with pytest.raises(HTTPException) as ei:
        asyncio.run(auth.callback(req))

    assert ei.value.status_code == 403
    assert req.session == {}  # no session issued to a non-editor
    # 403 body carries only the UI-SPEC copy — no secret/token leakage (T-10-08-05).
    assert "test-bot-token" not in str(ei.value.detail)


def test_callback_rejects_bad_or_missing_state(monkeypatch):
    async def fake_exchange(request):
        raise OAuthError("mismatching_state")

    monkeypatch.setattr(auth, "_exchange_token", fake_exchange)
    req = _FakeRequest()

    with pytest.raises(HTTPException) as ei:
        asyncio.run(auth.callback(req))

    assert ei.value.status_code == 400
    assert req.session == {}  # CSRF-guarded callback issues no session


# ── Task 2: require_editor — session-only identity + live role re-check (D-08/Pitfall 2)
def test_require_editor_401_without_session():
    from app import deps
    req = _FakeRequest()  # empty session
    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_editor(req))
    assert ei.value.status_code == 401


def test_require_editor_returns_identity_from_session_only(monkeypatch):
    from app import deps

    async def fake_role(uid):
        return True

    monkeypatch.setattr(deps, "has_editor_role", fake_role)
    req = _FakeRequest()
    # A hostile body-style slug/discordId is NOT consulted — identity is the session's.
    req.session = {"discord_id": "555", "slug": "aria"}
    ident = asyncio.run(deps.require_editor(req))
    assert ident == {"discord_id": "555", "slug": "aria"}


def test_require_editor_403_and_clears_session_on_role_loss(monkeypatch):
    from app import deps

    async def fake_role(uid):
        return False  # role revoked since login

    monkeypatch.setattr(deps, "has_editor_role", fake_role)
    req = _FakeRequest()
    req.session = {"discord_id": "555", "slug": "aria"}

    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_editor(req))

    assert ei.value.status_code == 403
    assert req.session == {}  # stale session cleared (Pitfall 2)


# ── Task 2: app assembly — SessionMiddleware secure flags + fail-fast config ────────
def test_session_middleware_configured_with_secure_flags():
    from starlette.middleware.sessions import SessionMiddleware

    from app.main import app

    entry = next(m for m in app.user_middleware if m.cls is SessionMiddleware)
    kw = dict(getattr(entry, "kwargs", {}) or {})
    assert kw.get("https_only") is True
    assert kw.get("same_site") == "lax"
    assert kw.get("max_age") and kw["max_age"] <= 6 * 3600  # short TTL (Pitfall 2)


def test_validate_config_raises_when_session_secret_empty(monkeypatch):
    from app import main

    monkeypatch.setattr(config, "SESSION_SECRET", "")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    with pytest.raises(RuntimeError):
        main.validate_config()


def test_validate_config_passes_when_all_set(monkeypatch):
    from app import main

    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 32)
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setattr(config, "DISCORD_OAUTH_REDIRECT_URI", "https://x/auth/callback")

    main.validate_config()  # must not raise


# ── Task 2 (02-02): require_owner — narrows require_editor to the single owner ─────
# (PANEL-01, D-10). The `DISCORD_USER_ID` fail-closed trap (Pitfall 1) and the
# str-session/int-config type mismatch (Pitfall 4) each get a dedicated test.
def test_require_owner_403_when_owner_id_unset(monkeypatch):
    from app import deps

    monkeypatch.setattr(config, "DISCORD_USER_ID", 0)
    req = _FakeRequest()
    req.session = {"discord_id": "555"}

    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_owner(req))

    assert ei.value.status_code == 403


def test_require_owner_200_for_matching_owner(monkeypatch):
    from app import deps

    monkeypatch.setattr(config, "DISCORD_USER_ID", 555)
    req = _FakeRequest()
    req.session = {"discord_id": "555"}

    ident = asyncio.run(deps.require_owner(req))

    assert ident["discord_id"] == "555"


def test_require_owner_403_for_non_owner_session(monkeypatch):
    from app import deps

    monkeypatch.setattr(config, "DISCORD_USER_ID", 555)
    req = _FakeRequest()
    req.session = {"discord_id": "999"}  # a real editor, but not the owner

    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_owner(req))

    assert ei.value.status_code == 403


def test_require_owner_403_without_session(monkeypatch):
    from app import deps

    monkeypatch.setattr(config, "DISCORD_USER_ID", 555)
    req = _FakeRequest()  # empty session

    with pytest.raises(HTTPException) as ei:
        asyncio.run(deps.require_owner(req))

    assert ei.value.status_code == 403
