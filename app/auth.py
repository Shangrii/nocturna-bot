"""Discord OAuth2 login + hard bot-token role gate + first-login draft (Fase 10, 10-08).

This module is the authentication trust boundary of the editor admin app. It does three
things, in this order, and nothing else:

1. **Identify** the user via Discord OAuth2 authorization-code flow (Authlib). Authlib
   generates and verifies the ``state`` param (CSRF guard, Pitfall 4 / T-10-08-01) and
   performs the token exchange — we never hand-roll it (Don't-Hand-Roll).
2. **Authorize** the user with a SERVER-SIDE call to the Discord API using the **bot
   token** (``GET /guilds/{GUILD_ID}/members/{user_id}`` with ``Authorization: Bot ...``),
   checking the current authoritative roles for ``ROLE_MODERATOR_ID`` (the editor role,
   D-07/D-15). The bot token NEVER reaches the browser (T-10-08-05); the OAuth user token
   is used only to read the user's own id, never for the role read.
3. **Provision** a first-login draft (D-09): if no ``editors.json`` entry matches the
   ``discordId``, create an empty ``EditorPage`` (``published=false``) with a normalized,
   collision-suffixed slug (Pitfall 5) and commit it via the reused cross-repo transport.

A session is issued ONLY after step 2 passes. On failure the callback raises 403/400 and
sets no session. The post-login redirect is a FIXED internal path — never a client-supplied
``next`` (open-redirect guard, Pitfall 4 / T-10-08-04). No secret, token, or OAuth code is
ever logged or returned in an error body (T-10-08-05).
"""

import asyncio
import logging

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import HTTPException
from starlette.responses import RedirectResponse

import config
from core import github_publish
from core.editors_model import EditorPage, normalize_slug

log = logging.getLogger(__name__)

# Discord REST base (v10) — used for the server-side bot-token role read.
DISCORD_API = "https://discord.com/api/v10"
# The OAuth2 authorization + token endpoints and the user resource base.
_DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
_DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
_DISCORD_API_BASE = "https://discord.com/api/"
# Only ``identify`` is needed: OAuth gives us WHO the user is; the role read is done
# server-side with the bot token, so no ``guilds.members.read`` scope is required (D-07).
_OAUTH_SCOPE = "identify"

# Fixed internal post-login target — NEVER a client-supplied redirect (Pitfall 4). 10-10
# renders the editor dashboard at the app root; a returning editor lands there.
POST_LOGIN_REDIRECT = "/"

# Explicit timeout on every outbound Discord call (no unbounded hangs on the role gate).
_HTTP_TIMEOUT = httpx.Timeout(10.0)

# UI-SPEC "Not-an-editor (403)" copy (EN · ES) — the only thing a rejected user sees.
# Carries no secret/token; safe to return in the response body (T-10-08-05).
_FORBIDDEN_COPY = (
    "This tool is for Nocturna editors only. If you should have access, ask a mod to "
    "check your role. — Esta herramienta es solo para editores de Nocturna. Si "
    "deberías tener acceso, pídele a un mod que revise tu rol."
)


# ── Authlib OAuth2 client registry ────────────────────────────────────────────────
# ``oauth.register`` merely stores the client config (it does not validate secrets at
# import time), so importing this module is safe even before the cinema ``.env`` is
# populated — the app's fail-fast lives in ``app.main.validate_config`` (startup).
oauth = OAuth()
oauth.register(
    name="discord",
    client_id=config.DISCORD_OAUTH_CLIENT_ID,
    client_secret=config.DISCORD_OAUTH_CLIENT_SECRET,
    authorize_url=_DISCORD_AUTHORIZE_URL,
    access_token_url=_DISCORD_TOKEN_URL,
    api_base_url=_DISCORD_API_BASE,
    client_kwargs={"scope": _OAUTH_SCOPE},
)


# ── authorization: the hard bot-token guild-role gate (D-07/D-15) ──────────────────
async def has_editor_role(user_id) -> bool:
    """True iff ``user_id`` currently holds the editor role in the guild (D-07/D-15).

    Reads the AUTHORITATIVE current roles from the Discord API with the **bot token**
    header — never the OAuth user token, never a token-time snapshot. A user who is not a
    guild member (404) is a clean ``False``, not an error. Because this reads live roles,
    it is safe to call on every login AND on every sensitive write (Pitfall 2 defense).
    """
    url = f"{DISCORD_API}/guilds/{config.GUILD_ID}/members/{user_id}"
    headers = {"Authorization": f"Bot {config.BOT_TOKEN}"}  # NEVER the OAuth user token
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        return False  # not a member of the guild → not an editor
    resp.raise_for_status()
    member = resp.json()
    role_ids = {str(r) for r in member.get("roles", [])}
    return str(config.ROLE_MODERATOR_ID) in role_ids


# ── first-login provisioning (D-09) ───────────────────────────────────────────────
async def _fetch_editors():
    """Fetch the live ``editors.json`` array (off the event loop; blocking ``requests``).

    Reuses the transport's audited generic array reader so ``ensure_draft`` sees the same
    source of truth every ``sync_editors`` commit merges into (Pitfall 6 consistency).
    """
    return await asyncio.to_thread(
        github_publish._fetch_json,
        config.WEBSITE_REPO,
        config.WEBSITE_BRANCH,
        config.WEBSITE_EDITORS_JSON,
    )


def _unique_slug(base: str, taken: set) -> str:
    """Return ``base`` if free, else ``base-2``, ``base-3``, … (Pitfall 5 collision suffix)."""
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


async def ensure_draft(discord_id, username) -> dict:
    """Return this editor's ``editors.json`` entry, creating an empty draft on first login.

    D-09: if no entry matches ``discord_id`` (the 1:1 key, compared as a string), build an
    empty ``EditorPage`` (``published=false``, empty ``blocks``) with a normalized slug
    derived from the Discord username (D-19), made unique against existing slugs (numeric
    suffix on collision, Pitfall 5), and commit it via the reused cross-repo transport.
    A returning editor's existing entry is returned as-is with NO commit (no gratuitous
    Pages rebuild). Identity comes only from the trusted caller (the OAuth callback), never
    a request body (D-08).
    """
    target = str(discord_id)
    editors = await _fetch_editors()
    existing = next((e for e in editors if str(e.get("discordId")) == target), None)
    if existing is not None:
        return existing

    # Derive a URL-safe slug from the username; fall back to an id-derived slug if the
    # username has no [a-z0-9] characters (normalize_slug raises on an empty result).
    try:
        base = normalize_slug(username)
    except (ValueError, TypeError):
        base = normalize_slug(f"editor-{target}")
    taken = {e.get("slug") for e in editors}
    slug = _unique_slug(base, taken)

    # Validate the shape through the same server-side gate every save passes (10-02).
    entry = EditorPage(
        slug=slug,
        discordId=target,
        published=False,
        name=(username or slug)[:100],
    ).model_dump()

    await github_publish.sync_editors(entry)
    return entry


# ── OAuth2 exchange wrappers (thin seams — Authlib does the CSRF-safe heavy lifting) ─
async def _exchange_token(request):
    """Exchange the callback code for a token; Authlib VERIFIES the ``state`` param here
    (CSRF guard, Pitfall 4). Raises ``OAuthError`` on a missing/mismatched state or a bad
    code — the callback turns that into a 400 with no session."""
    return await oauth.discord.authorize_access_token(request)


async def _fetch_user(token) -> dict:
    """Read the authenticated user's own Discord profile (``users/@me``) with the OAuth
    user token. Used ONLY to learn the user's id/username — never for the role check."""
    resp = await oauth.discord.get("users/@me", token=token)
    return resp.json()


# ── route handlers ────────────────────────────────────────────────────────────────
async def login(request):
    """Redirect to Discord's OAuth2 authorize endpoint (Authlib manages ``state``).

    The redirect URI is the FIXED registered value from config — the app never accepts an
    arbitrary post-login target from the query string (Pitfall 4 / T-10-08-04).
    """
    return await oauth.discord.authorize_redirect(
        request, config.DISCORD_OAUTH_REDIRECT_URI)


async def callback(request):
    """Handle the OAuth2 callback: verify state → identify → role-gate → session.

    Order is security-critical: the session is set ONLY after the bot-token role check and
    first-login draft succeed, so a non-editor (403) or a bad-state request (400) leaves no
    session behind (T-10-08-06 / T-10-08-01). The redirect target is a fixed internal path.
    """
    try:
        token = await _exchange_token(request)  # Authlib verifies `state` (CSRF)
    except OAuthError as exc:
        # Do not leak the code/state/secret — a generic 400 is enough.
        raise HTTPException(status_code=400, detail="Invalid OAuth state or code") from exc

    user = await _fetch_user(token)
    user_id = str(user["id"])
    username = user.get("username") or user.get("global_name") or user_id

    if not await has_editor_role(user_id):
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    entry = await ensure_draft(user_id, username)

    # Session issued last, only on the fully-authorized path.
    request.session["discord_id"] = user_id
    request.session["slug"] = entry["slug"]
    return RedirectResponse(url=POST_LOGIN_REDIRECT, status_code=303)


async def logout(request):
    """Clear the session and return to the app root."""
    request.session.clear()
    return RedirectResponse(url=POST_LOGIN_REDIRECT, status_code=303)
