"""FastAPI app entry for the editor admin app (Fase 10, 10-08/10-10).

Assembles the authenticated core built in ``app.auth``/``app.deps`` into a runnable ASGI
app: a signed short-TTL session cookie (V3 / Pitfall 2), the OAuth routes, a fail-fast
config guard, and (10-10) the block editor surface itself — the two-pane editor page,
the image-upload endpoint, and the save/publish + self-unpublish endpoints.

Session cookie (Starlette ``SessionMiddleware`` / itsdangerous — never hand-rolled):
  * ``secret_key`` from ``config.SESSION_SECRET`` (32+ random bytes, cinema ``.env`` only,
    never committed) — signs+tamper-protects the cookie.
  * ``https_only=True`` (Secure flag — the app is internet-facing behind Caddy TLS, Pitfall 8).
  * ``same_site="lax"`` (CSRF hardening while still allowing the top-level OAuth redirect back).
    SameSite=Lax + require_editor's session-only identity is the CSRF mitigation for every
    state-changing POST below (T-10-10-04) — no separate CSRF token is hand-rolled.
  * ``max_age=6*3600`` (short TTL — an offboarded editor's cookie expires quickly, Pitfall 2).

Deployment: uvicorn binds to ``127.0.0.1`` behind the Caddy reverse proxy that terminates
HTTPS on ``editors.nocturna-avatars.site`` (Pitfall 8 — never expose uvicorn on ``0.0.0.0``).
Runs as its own systemd unit sharing the bot venv/config/``core`` (D-06); it is NOT loaded by
the discord.py bot process.

Rate limiting (RESEARCH "Don't Hand-Roll" — ``slowapi`` OR proxy-level): this plan chooses
the PROXY-LEVEL option rather than adding a new pip dependency mid-plan (a fresh package
install is deliberately excluded from this executor's auto-fix authority — it would need its
own legitimacy checkpoint, mirroring 10-02's). Caddy's `rate_limit` directive in front of
`/login`, `/auth/callback`, and every `/editor/*` POST is documented in
``deploy/EDITOR_DEPLOY.md`` for the 10-11 deploy — functionally equivalent, zero new Python
dependency, and the plan itself names this as an accepted alternative.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import config
from app import auth
from app.deps import require_editor
from core import github_publish

log = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))

# Short session TTL (seconds) — Pitfall 2: a revoked editor's cookie must not linger.
_SESSION_MAX_AGE = 6 * 3600


async def _fetch_current_entry(discord_id: str) -> dict:
    """Fetch this editor's live ``editors.json`` entry (off the event loop).

    Reuses the same generic array reader ``ensure_draft`` uses, so every read sees the
    identical source of truth every ``sync_editors`` commit merges into (Pitfall 6).
    """
    editors = await run_in_threadpool(
        github_publish._fetch_json,
        config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_EDITORS_JSON)
    target = str(discord_id)
    return next((e for e in editors if str(e.get("discordId")) == target), None)

# Config keys that MUST be present for the app to serve securely. An empty value here means
# the OAuth flow can't complete or the session can't be signed — refuse to start (fail-fast).
_REQUIRED_CONFIG = (
    "SESSION_SECRET",
    "DISCORD_OAUTH_CLIENT_ID",
    "DISCORD_OAUTH_CLIENT_SECRET",
    "DISCORD_OAUTH_REDIRECT_URI",
)


def validate_config() -> None:
    """Raise ``RuntimeError`` if any required secret/OAuth setting is empty (fail-fast).

    Called at startup (via the lifespan handler) and from the ``__main__`` entry so the app
    NEVER boots with an unsigned session or an incomplete OAuth config. Import-time is left
    clean on purpose so ``from app.main import app`` works in tooling/tests without a full
    ``.env`` — the enforcement happens when the server actually starts. The error names only
    the missing KEYS, never their values (no secret leakage).
    """
    missing = [name for name in _REQUIRED_CONFIG if not getattr(config, name, "")]
    if missing:
        raise RuntimeError(
            "editor admin app misconfigured — set these in the cinema .env: "
            + ", ".join(missing))


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_config()  # fail-fast on startup — never serve with empty secrets/OAuth config
    log.info("editor admin app started")
    yield


app = FastAPI(
    title="Nocturna Editor Admin",
    lifespan=lifespan,
    docs_url=None,       # no public API docs surface for an internal auth tool
    redoc_url=None,
    openapi_url=None,
)

# Signed session cookie with secure flags (V3 / Pitfall 2 / Pitfall 8). ``secret_key`` is the
# live ``.env`` value; if empty, ``validate_config`` refuses startup before any request lands.
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    https_only=True,
    same_site="lax",
    max_age=_SESSION_MAX_AGE,
)

@app.exception_handler(StarletteHTTPException)
async def _auth_html_or_json(request: Request, exc: StarletteHTTPException):
    """Render ``login.html`` for a browser navigation hitting a 401/403; JSON otherwise.

    ``require_editor`` raises plain ``HTTPException(401|403)`` — without this handler a
    browser visiting ``/`` unauthenticated (or after role loss) would see a bare JSON
    body instead of the UI-SPEC login/403 page. Every ``fetch()`` call from the editor
    app itself (image/save/unpublish) sends ``Accept: application/json`` and keeps
    getting a JSON error body — this handler only changes NAVIGATION responses.
    """
    if exc.status_code in (401, 403) and "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse(
            request, "login.html",
            {"forbidden": exc.status_code == 403},
            status_code=exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# OAuth routes (identity + session lifecycle).
app.add_route("/login", auth.login, methods=["GET"])
app.add_route("/auth/callback", auth.callback, methods=["GET"])
app.add_route("/logout", auth.logout, methods=["GET", "POST"])

# Vendored front-end libs (Alpine 3.15.12 + SortableJS 1.15.7, NOT CDN) + editor.css.
app.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")


# ── 10-10: the block editor surface ────────────────────────────────────────────────
# Mounted at BOTH "/" (10-08's fixed POST_LOGIN_REDIRECT target — the dashboard root)
# and "/editor" (this plan's own literal artifact contract) — same handler, no
# duplicated logic, reconciling the two plans' route-path expectations.
@app.get("/", response_class=HTMLResponse)
@app.get("/editor", response_class=HTMLResponse)
async def editor_page(request: Request, ident: dict = Depends(require_editor)):
    """The two-pane block editor (D-14), loaded with the SESSION editor's live entry.

    ``require_editor`` is the D-08 IDOR choke point: the entry rendered is always the
    caller's own, resolved from the session — never a client-supplied slug/id.
    """
    entry = await _fetch_current_entry(ident["discord_id"])
    if entry is None:  # defensive — ensure_draft guarantees this exists post-login
        entry = {
            "slug": ident.get("slug", ""), "discordId": ident["discord_id"],
            "published": False, "name": "", "avatar": "",
            "tagline": {"es": "", "en": ""}, "links": [], "blocks": [],
        }
    return templates.TemplateResponse(request, "editor.html", {"entry": entry})


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    validate_config()
    # Bind to loopback ONLY — Caddy fronts it and terminates HTTPS (Pitfall 8).
    uvicorn.run(app, host="127.0.0.1", port=8770)
