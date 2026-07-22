"""Discord OAuth2 login + hard bot-token role gate + first-login draft (Fase 10, 10-08;
generalized to a 3-tier owner/Manager/editor resolver in Phase 3, 03-05).

This module is the authentication trust boundary of the editor admin app. It does three
things, in this order, and nothing else:

1. **Identify** the user via Discord OAuth2 authorization-code flow (Authlib). Authlib
   generates and verifies the ``state`` param (CSRF guard, Pitfall 4 / T-10-08-01) and
   performs the token exchange — we never hand-roll it (Don't-Hand-Roll).
2. **Authorize** the user with a SERVER-SIDE call to the Discord API using the **bot
   token** (``GET /guilds/{GUILD_ID}/members/{user_id}`` with ``Authorization: Bot ...``),
   resolving the current authoritative roles against the editable ``manager_roles`` /
   ``editor_roles`` mapping (D-08) plus the hardcoded owner id (D-04). The bot token NEVER
   reaches the browser (T-10-08-05); the OAuth user token is used only to read the user's
   own id, never for the role read.
3. **Provision** a first-login draft (D-09) for any user who resolves to the editor tier:
   if no ``editors.json`` entry matches the ``discordId``, create an empty ``EditorPage``
   (``published=false``) with a normalized, collision-suffixed slug (Pitfall 5) and commit
   it via the reused cross-repo transport.

A session is issued ONLY after step 2 passes (at least one tier resolves, D-01). On failure
the callback raises 403/400 and sets no session. The post-login redirect is a FIXED
internal path, chosen per-tier (owner/manager → ``/overview``, editor-only → ``/editor``) —
never a client-supplied ``next`` (open-redirect guard, Pitfall 4 / T-10-08-04 / D-03/T-03-16).
The session stores only ``discord_id`` (+ ``slug`` for editors) — never a cached tier (D-02).
No secret, token, or OAuth code is ever logged or returned in an error body (T-10-08-05).
"""

import asyncio
import logging
import secrets

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import HTTPException
from starlette.responses import RedirectResponse

import config
from core import github_publish, settings
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
# renders the editor dashboard at the app root; used for the post-LOGOUT redirect (the
# post-LOGIN redirect is now tier-specific, see _REDIRECT_MANAGER_TIER/_REDIRECT_EDITOR_TIER).
POST_LOGIN_REDIRECT = "/"

# Per-tier post-login redirect targets (D-03/Pitfall 1, T-03-16) — fixed, server-chosen,
# never derived from a client ``?next``. Owner and Manager land on the dashboard overview;
# an editor-only identity (no owner/manager tier) lands on their own presentation section.
_REDIRECT_MANAGER_TIER = "/overview"
_REDIRECT_EDITOR_TIER = "/editor"

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


# ── authorization: the shared bot-token guild-role read (D-07/D-15) ────────────────
async def _fetch_member_roles(user_id) -> set[str] | None:
    """Return the LIVE guild-member role-id set for ``user_id``, or ``None`` if not a member.

    Reads the AUTHORITATIVE current roles from the Discord API with the **bot token**
    header — never the OAuth user token, never a token-time snapshot. A user who is not a
    guild member (404) resolves to ``None`` (a clean "no roles", not an error). This is the
    SINGLE shared read used by both ``has_editor_role`` and ``app.deps._resolve_roles`` —
    callers must call it at most once per request (FastAPI ``Depends(..., use_cache=True)``
    on the dependency side) to avoid an N+1 Discord REST read per page.
    """
    url = f"{DISCORD_API}/guilds/{config.GUILD_ID}/members/{user_id}"
    headers = {"Authorization": f"Bot {config.BOT_TOKEN}"}  # NEVER the OAuth user token
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code == 404:
        return None  # not a member of the guild
    resp.raise_for_status()
    member = resp.json()
    return {str(r) for r in member.get("roles", [])}


async def has_editor_role(user_id) -> bool:
    """True iff ``user_id`` currently holds one of the editable ``editor_roles`` (D-08).

    Thin wrapper over ``_fetch_member_roles``: a non-member (``None``) is a clean ``False``.
    The comparison set is read fresh from the settings store on every call — an owner edit
    to ``editor_roles`` takes effect on the very next request, with no cog/app restart
    (mirrors the read-at-use discipline the rest of the settings store already guarantees).
    """
    role_ids = await _fetch_member_roles(user_id)
    if role_ids is None:
        return False
    editor_ids = {str(r) for r in settings.get("editor_roles")}
    return bool(role_ids & editor_ids)


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
    # A fresh draft defaults to Spanish (the team's primary language, D-13) and the
    # Midnight-Nocturna theme (ThemeModel default, D-26) — the editor tunes both later.
    entry = EditorPage(
        slug=slug,
        discordId=target,
        mediaId=secrets.token_hex(8),
        published=False,
        name=(username or slug)[:100],
        lang="es",
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
    """Handle the OAuth2 callback: verify state → identify → tier-resolve → session.

    Order is security-critical: the session is set ONLY after tier resolution (and, for the
    editor tier, the first-login draft) succeed, so a user with NO tier at all (403) or a
    bad-state request (400) leaves no session behind (T-10-08-06 / T-10-08-01 / D-01 login
    gate). Tier facts come from a single live bot-token role read plus the owner id — never
    from the request. The redirect target is a FIXED internal path chosen per-tier (D-03/
    Pitfall 1): owner or Manager → ``/overview``; editor-only → ``/editor``. The session
    stores only ``discord_id`` (+ ``slug`` when the editor tier resolves) — never a tier
    (D-02).
    """
    try:
        token = await _exchange_token(request)  # Authlib verifies `state` (CSRF)
    except OAuthError as exc:
        # Do not leak the code/state/secret — a generic 400 is enough.
        raise HTTPException(status_code=400, detail="Invalid OAuth state or code") from exc

    user = await _fetch_user(token)
    user_id = str(user["id"])
    username = user.get("username") or user.get("global_name") or user_id

    # Owner tier is independent of the editable mapping (D-04) — never locked out even if
    # manager_roles/editor_roles is empty/misconfigured; fails closed on unset DISCORD_USER_ID.
    is_owner = bool(config.DISCORD_USER_ID) and str(user_id) == str(config.DISCORD_USER_ID)
    # ONE shared live role read for both the manager and editor tier checks (Pitfall 4).
    role_ids = await _fetch_member_roles(user_id) or set()
    manager_ids = {str(r) for r in settings.get("manager_roles")}
    editor_ids = {str(r) for r in settings.get("editor_roles")}
    is_manager = bool(role_ids & manager_ids)
    is_editor = bool(role_ids & editor_ids)

    if not (is_owner or is_manager or is_editor):
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    # First-login draft provisioning stays on the editor path only (D-09 unchanged scope).
    entry = await ensure_draft(user_id, username) if is_editor else None

    # Session issued last, only on the fully-authorized path — no tier is ever cached (D-02).
    request.session["discord_id"] = user_id
    if entry is not None:
        request.session["slug"] = entry["slug"]

    redirect_target = (
        _REDIRECT_MANAGER_TIER if (is_owner or is_manager) else _REDIRECT_EDITOR_TIER
    )
    return RedirectResponse(url=redirect_target, status_code=303)


async def logout(request):
    """Clear the session and return to the app root."""
    request.session.clear()
    return RedirectResponse(url=POST_LOGIN_REDIRECT, status_code=303)
