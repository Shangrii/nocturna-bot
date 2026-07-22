"""Ownership-scoped request dependencies for the editor admin app (Fase 10, 10-08; Phase 2,
02-02; generalized to a 3-tier owner/Manager/editor union resolver in Phase 3, 03-05).

``require_editor`` is the SINGLE choke point that enforces D-08 ("an editor can only ever
edit their own page") and the Pitfall-2 stale-session guard. It is deliberately tiny and
has exactly one job: resolve the editable identity from the signed SESSION and re-prove the
role is still live — then hand back ``{discord_id, slug}`` for downstream handlers to scope
their writes to.

Two invariants this module guarantees (and that the tests pin):

* **Identity from the session ONLY (D-08 IDOR).** ``discord_id``/``slug`` come from
  ``request.session`` — NEVER from a request body, query param, or path. Every later save
  endpoint (10-09) resolves the target ``editors.json`` entry from the value this dependency
  returns, so a logged-in editor can never address another editor's page by smuggling a slug
  or discordId into the payload (Pitfall 1 / T-10-08-02).
* **Live re-check on every call (Pitfall 2).** The bot-token role read runs on each protected
  request, not just at ``/login``. If the editor lost the role since login, the session is
  cleared and a 403 is raised — an offboarded editor's still-valid cookie can no longer act,
  even before the 10-09 ``on_member_update`` unpublish fires (T-10-08-03).

``require_owner`` (Phase 2, PANEL-01/D-10) narrows ``require_editor``'s already-established
session to the single configured owner (``config.DISCORD_USER_ID``). Two invariants pinned
by its tests:

* **Fails closed on the ``0``/unset owner id (D-10, Pitfall 1).** ``DISCORD_USER_ID``
  defaults to ``0`` when unset; that must never double as "no restriction" — the falsy guard
  runs BEFORE the identity comparison, so a misconfigured owner id always denies.
* **Session identity is str, config owner id is int (Pitfall 4).** Both operands are
  normalized with ``str()`` before comparing so the real owner isn't locked out by a type
  mismatch, while identity is still read from ``request.session`` only (same D-08 discipline).

``_resolve_roles``/``require_manager`` (Phase 3, 03-05, ACCESS-01..04) generalize the same
choke-point discipline into a 3-tier owner/Manager/editor union: ``_resolve_roles`` does ONE
live bot-token role read per request (shared via FastAPI's default ``Depends(...,
use_cache=True)`` — Pitfall 4, never a hand-rolled ``request.state`` cache) and returns which
tiers resolve; ``require_manager`` admits owner OR Manager and raises the distinguishable
``TierForbidden`` otherwise. ``require_owner``/``require_editor`` are UNCHANGED by this
addition — the owner-never-locked-out guarantee (D-04) stays on the exact dependency
``/admin/settings`` already used, no new code path.
"""

from fastapi import Depends, HTTPException, Request

import config
from app import auth
from app.auth import _FORBIDDEN_COPY, has_editor_role
from core import settings

_OWNER_FORBIDDEN_COPY = (
    "Solo el propietario puede acceder a esta página. — "
    "Only the owner can access this page."
)


async def require_editor(request: Request) -> dict:
    """Return the session-scoped editor identity, or raise 401/403.

    * No session (or no ``discord_id`` in it) → **401** (not authenticated).
    * Session present but the role is no longer held → clear the session, **403**
      (Pitfall 2 stale-session revocation).
    * Otherwise → ``{"discord_id": ..., "slug": ...}`` read straight from the session.

    The returned identity is the ONLY authoritative source of "which page may I edit" —
    callers must never accept a slug/discordId from the request body (D-08).
    """
    discord_id = request.session.get("discord_id")
    if not discord_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Re-prove the role on every protected action (defense against a stale session after
    # role loss, Pitfall 2). Cheap: one bot-token REST read against the live guild roles.
    if not await has_editor_role(discord_id):
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    # Identity from the SESSION only — never from the request body (D-08 IDOR choke point).
    return {"discord_id": discord_id, "slug": request.session.get("slug")}


async def require_owner(request: Request) -> dict:
    """Return the session identity iff it is the configured owner, else 403 (PANEL-01/D-10).

    * ``DISCORD_USER_ID`` unset/``0`` → **403**, regardless of session content. This guard
      MUST run before the equality check — the ``0`` default must never authorize (fail-closed,
      Pitfall 1).
    * No session, or session ``discord_id`` != the configured owner → **403** (never 401 — by
      the time a caller reaches this dependency they are already an authenticated editor;
      "authenticated but not the owner" is a strict authorization denial, not a login gate).
    * Otherwise → ``{"discord_id": ...}`` read straight from the session.

    Both operands are normalized with ``str()`` before comparing: ``config.DISCORD_USER_ID``
    is an ``int``, while ``request.session["discord_id"]`` is stored as a ``str`` (set in
    ``app/auth.py::callback``) — comparing the raw types would false-negative the real owner
    (Pitfall 4). Identity comes from the SESSION only — never the request body/query (same
    D-08 IDOR discipline as ``require_editor``); the owner authenticates via the existing
    editor-role OAuth flow, which this dependency does not modify (D-11).
    """
    discord_id = request.session.get("discord_id")
    owner_id = config.DISCORD_USER_ID
    if not owner_id:  # fail closed: unset/0 owner id must never authorize
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)
    if not discord_id or str(discord_id) != str(owner_id):
        raise HTTPException(status_code=403, detail=_OWNER_FORBIDDEN_COPY)

    return {"discord_id": discord_id}


class TierForbidden(HTTPException):
    """403 raised by ``require_manager`` (and future tier-gated dependencies) that carries
    ``.required_tier`` so the app's exception handler can render a tier-specific page
    (``forbidden.html``) instead of the generic editor-only ``login.html`` branch (D-16 /
    Pitfall 2 — never reuse ``_FORBIDDEN_COPY`` for a tier denial, the copy differs)."""

    def __init__(self, required_tier: str):
        super().__init__(status_code=403, detail=f"needs {required_tier} access")
        self.required_tier = required_tier


async def _resolve_roles(request: Request) -> dict:
    """Resolve the session identity's owner/Manager/editor tiers from a SINGLE live
    bot-token role read (ACCESS-01..04).

    * No ``discord_id`` in session → **401** (not authenticated).
    * ``is_owner`` is hardcoded to ``config.DISCORD_USER_ID`` (D-04) — independent of the
      editable mapping, so the owner is NEVER locked out even if ``manager_roles``/
      ``editor_roles`` is empty or misconfigured; fails closed when unset (same Pitfall-1
      discipline as ``require_owner``).
    * ONE ``auth._fetch_member_roles`` call resolves the live guild roles (never a
      session-cached tier, D-02); a non-member (``None``) clears the session and 403s, same
      as a user who resolves to no tier at all — both are treated as "no longer authorized"
      (matches the OAuth callback's own login gate, D-01).
    * Returns ``{"discord_id", "is_owner", "is_manager", "is_editor"}`` for downstream
      dependencies (``require_manager``) and route handlers (sidebar lock-icon rendering) to
      share via FastAPI's default ``Depends(..., use_cache=True)`` — collapsing repeat calls
      within one request to this single REST read (Pitfall 4, never a hand-rolled
      ``request.state`` cache).
    """
    discord_id = request.session.get("discord_id")
    if not discord_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    is_owner = bool(config.DISCORD_USER_ID) and str(discord_id) == str(config.DISCORD_USER_ID)

    role_ids = await auth._fetch_member_roles(discord_id)
    if role_ids is None:
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    manager_ids = {str(r) for r in settings.get("manager_roles")}
    editor_ids = {str(r) for r in settings.get("editor_roles")}
    is_manager = bool(role_ids & manager_ids)
    is_editor = bool(role_ids & editor_ids)

    if not (is_owner or is_manager or is_editor):
        request.session.clear()
        raise HTTPException(status_code=403, detail=_FORBIDDEN_COPY)

    return {
        "discord_id": discord_id,
        "is_owner": is_owner,
        "is_manager": is_manager,
        "is_editor": is_editor,
    }


async def require_manager(roles: dict = Depends(_resolve_roles)) -> dict:
    """Return the resolved roles dict for the owner or a Manager, else raise
    ``TierForbidden(required_tier="manager")``.

    Gates the six operational dashboard modules (Overview/Gallery/Reviews/Reminders/
    Jinxxy/Meetings, ACCESS-02). ``/admin/settings`` stays on the UNCHANGED ``require_owner``
    dependency — a Manager session can never satisfy it, so the tier-assignment mapping
    itself stays owner-only (T-03-12 self-elevation guard, D-04).
    """
    if not (roles["is_owner"] or roles["is_manager"]):
        raise TierForbidden(required_tier="manager")
    return roles
