"""Ownership-scoped request dependencies for the editor admin app (Fase 10, 10-08; Phase 2, 02-02).

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
"""

from fastapi import HTTPException, Request

import config
from app.auth import _FORBIDDEN_COPY, has_editor_role

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
