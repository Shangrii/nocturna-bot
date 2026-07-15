"""Ownership-scoped request dependency for the editor admin app (Fase 10, 10-08).

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
"""

from fastapi import HTTPException

from app.auth import _FORBIDDEN_COPY, has_editor_role


async def require_editor(request) -> dict:
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
