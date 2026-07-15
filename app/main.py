"""FastAPI app entry for the editor admin app (Fase 10, 10-08).

Assembles the authenticated core built in ``app.auth``/``app.deps`` into a runnable ASGI
app: a signed short-TTL session cookie (V3 / Pitfall 2), the OAuth routes, and a fail-fast
config guard. No block-editor UI yet (that is 10-09) — this is auth + session + identity only.

Session cookie (Starlette ``SessionMiddleware`` / itsdangerous — never hand-rolled):
  * ``secret_key`` from ``config.SESSION_SECRET`` (32+ random bytes, cinema ``.env`` only,
    never committed) — signs+tamper-protects the cookie.
  * ``https_only=True`` (Secure flag — the app is internet-facing behind Caddy TLS, Pitfall 8).
  * ``same_site="lax"`` (CSRF hardening while still allowing the top-level OAuth redirect back).
  * ``max_age=6*3600`` (short TTL — an offboarded editor's cookie expires quickly, Pitfall 2).

Deployment: uvicorn binds to ``127.0.0.1`` behind the Caddy reverse proxy that terminates
HTTPS on ``editors.nocturna-avatars.site`` (Pitfall 8 — never expose uvicorn on ``0.0.0.0``).
Runs as its own systemd unit sharing the bot venv/config/``core`` (D-06); it is NOT loaded by
the discord.py bot process.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

import config
from app import auth

log = logging.getLogger(__name__)

# Short session TTL (seconds) — Pitfall 2: a revoked editor's cookie must not linger.
_SESSION_MAX_AGE = 6 * 3600

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

# OAuth routes (identity + session lifecycle). No editing routes yet — those arrive in 10-09
# behind ``app.deps.require_editor``.
app.add_route("/login", auth.login, methods=["GET"])
app.add_route("/auth/callback", auth.callback, methods=["GET"])
app.add_route("/logout", auth.logout, methods=["GET", "POST"])


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    validate_config()
    # Bind to loopback ONLY — Caddy fronts it and terminates HTTPS (Pitfall 8).
    uvicorn.run(app, host="127.0.0.1", port=8770)
