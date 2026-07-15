"""Standalone view-counter app for the editor profile pages (Fase 10.1, plan 10.1-12, D-25).

A MINIMAL FastAPI app — deliberately SEPARATE from ``app.main`` (the editor admin app) so it
never touches ``main.py``, its OAuth/session machinery, or its config guard. It serves exactly
one contract that ``ViewCounter.astro`` (plan 04) calls on splash dismiss:

    GET /api/views/<slug>?hit=1  → 200 {"count": <int>}   (increment then return)
    GET /api/views/<slug>        → 200 {"count": <int>}   (read-only, no increment)

Design (D-25 "tiny counter", no third party):
  * No auth — a public read/increment view counter. The increment is low-value and rate-limited
    at the proxy (Caddy) plus an app-level per-slug+ip_hash dedup window in the DB so a reload
    can't inflate the count (T-10.1-12-01).
  * Privacy: only a HASH of the client IP is ever stored, never the raw address (T-10.1-12-02).
  * Injection-safe: the slug is validated against ``[a-z0-9-]+`` before use AND every DB access
    uses ``?``-placeholders (T-10.1-12-03).
  * Never 500 on a missing slug — an unknown (but well-formed) slug returns ``{"count": 0}`` so
    the client always gets a clean number; a MALFORMED slug is rejected 404.
  * CORS: the caller is the PUBLIC site (``config.WEBSITE_BASE_URL``), a DIFFERENT origin from
    ``editors.nocturna-avatars.site`` that fronts this app — so its origin (and its www/non-www
    variant) is allowed for GET only.

Deployment: uvicorn binds loopback ``127.0.0.1:8771`` behind Caddy, which terminates HTTPS on
``editors.nocturna-avatars.site`` and routes ``/api/views/*`` here (deploy/Caddyfile.snippet +
deploy/nocturna-view-counter.service — a sibling systemd unit mirroring the editor-admin app).
Never expose uvicorn on ``0.0.0.0``.
"""

import hashlib
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import config
from core import db

log = logging.getLogger(__name__)

# Slug charset — matches the editor slug idiom and blunts SQL/path injection at the edge
# (defence in depth: DB access is also fully parameterised). Reject anything else 404.
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _allowed_origins() -> list[str]:
    """The public site origin (from ``config.WEBSITE_BASE_URL``) plus its www/non-www variant.

    The counter is called cross-origin from the public site — a DIFFERENT origin from the
    ``editors.`` subdomain that fronts this app — so CORS must name that origin explicitly.
    """
    base = config.WEBSITE_BASE_URL.rstrip("/")
    origins = {base}
    if "://www." in base:
        origins.add(base.replace("://www.", "://", 1))
    else:
        origins.add(base.replace("://", "://www.", 1))
    return sorted(origins)


def _client_ip_hash(request: Request) -> str:
    """Return a SHA-256 hash of the client IP (never the raw IP), or "" if none is available.

    Behind Caddy the real client IP is the first entry of ``X-Forwarded-For``; fall back to the
    direct peer for local/dev calls. Only the hash is ever passed to the DB (T-10.1-12-02).
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        ip = xff.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else ""
    if not ip:
        return ""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_view_counts()  # ensure the view_counts/view_dedup tables exist before serving
    log.info("view counter app started")
    yield


app = FastAPI(
    title="Nocturna View Counter",
    lifespan=lifespan,
    docs_url=None,       # no public API-docs surface for a tiny internal endpoint
    redoc_url=None,
    openapi_url=None,
)

# CORS for the PUBLIC site origin only (GET) — the browser fetch from nocturna-avatars.site.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/views/{slug}")
async def views(slug: str, request: Request, hit: str | None = None):
    """Return (and optionally increment) the per-slug view count.

    Malformed slug → 404 (never used in SQL — it's parameterised anyway, but reject early).
    ``hit=1`` increments once (subject to the per-slug+ip_hash dedup window) then returns the
    fresh count; without ``hit`` it's a read-only fetch. An unknown but well-formed slug
    returns ``{"count": 0}`` — the client always gets a clean integer, never a 500.
    """
    if not _SLUG_RE.match(slug):
        return JSONResponse(status_code=404, content={"count": 0})

    if hit == "1":
        ip_hash = _client_ip_hash(request)
        # Off the event loop — the sqlite write is blocking.
        count = await run_in_threadpool(db.increment_view, slug, ip_hash)
    else:
        count = await run_in_threadpool(db.get_view_count, slug)

    return {"count": count}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    # Bind to loopback ONLY — Caddy fronts it and terminates HTTPS. NEVER --host 0.0.0.0.
    uvicorn.run(app, host="127.0.0.1", port=8771)
