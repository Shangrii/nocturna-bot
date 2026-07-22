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

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

import config
from app import auth
from app.deps import require_editor, require_manager, require_owner, TierForbidden
from core import db, github_publish, settings
from core.editors_model import EditorPage, resolve_slug, SlugRejected
from core.image_optimize import optimize_to_webp

log = logging.getLogger(__name__)

_APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))

# Short session TTL (seconds) — Pitfall 2: a revoked editor's cookie must not linger.
_SESSION_MAX_AGE = 6 * 3600

# ── image upload limits (D-17 / Pitfall 3 / T-10-10-01) ────────────────────────────
# Byte-size cap enforced BEFORE the body is read in full (streamed chunk-by-chunk).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — same cap as background video
_UPLOAD_CHUNK = 256 * 1024
# SVG is rejected outright (raster only) — never trust Content-Type alone; also gate
# on filename extension since a client can lie about content_type.
_REJECTED_EXTS = (".svg",)
_REJECTED_CONTENT_TYPES = ("image/svg+xml",)

# UI-SPEC copy (bilingual, single string carrying both locales like the 403 copy).
_IMAGE_ERROR_COPY = (
    "Esa imagen no se pudo subir (formato o tamaño). Usa PNG/JPG/WebP de menos de 10 MB. — "
    "That image couldn't be uploaded (format or size). Use PNG/JPG/WebP under 10 MB."
)
_SAVE_FAILED_COPY = (
    "No se pudo publicar. Inténtalo de nuevo en un momento. — "
    "Couldn't publish. Try again in a moment."
)
_PUBLISH_SUCCESS_COPY = (
    "Publicado — la web tarda un par de minutos en actualizarse. — "
    "Published — the site takes a couple of minutes to update."
)
_UNPUBLISH_FAILED_COPY = (
    "No se pudo despublicar. Inténtalo de nuevo. — Couldn't unpublish. Try again."
)
_UNPUBLISH_SUCCESS_COPY = "Página despublicada — Page unpublished"

# Owner settings panel copy (Phase 2, D-13 bilingual house style).
_SETTINGS_SAVED_COPY = "Ajustes guardados. — Settings saved."
_SETTINGS_ERROR_COPY = (
    "Revisa los campos marcados. — Check the highlighted fields."
)

# Fallback ``roles`` dict for the dashboard-shell sidebar when rendering forbidden.html
# from the exception handler (Phase 3, 03-07) — no tier is resolved for a denied caller
# at this layer, so every section renders locked (see _auth_html_or_json docstring).
_NO_TIER_ROLES = {"is_owner": False, "is_manager": False, "is_editor": False}

# Slug-rejection copy, keyed by SlugRejected.reason → (HTTP status, bilingual message).
_SLUG_REJECT = {
    "invalid": (422, "Elige un nombre de link válido (letras, números y guiones). · "
                     "Choose a valid link name (letters, numbers, hyphens)."),
    "reserved": (422, "Ese nombre de link está reservado, elige otro. · "
                      "That link name is reserved — choose another."),
    "taken": (409, "Ese nombre de link ya está en uso. · That link name is already taken."),
}

# ── background media + audio upload limits (D-18 / D-06 / D-19 / T-10.1-11-01) ───────
# Per-kind byte caps enforced BEFORE the body is buffered in full (streamed chunk read,
# Pitfall 3). Moderate caps keep the GitHub-Pages repo budget in check (D-19).
_MEDIA_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # raster image ≤ 10 MB (same as video)
_MEDIA_VIDEO_MAX_BYTES = 10 * 1024 * 1024  # background video / GIF ≤ 10 MB
_AUDIO_MAX_BYTES = 5 * 1024 * 1024         # background audio ≤ 5 MB

# Human-facing cap strings interpolated into the too-large copy.
_MEDIA_IMAGE_CAP_HUMAN = "10 MB"
_MEDIA_VIDEO_CAP_HUMAN = "10 MB"
_AUDIO_CAP_HUMAN = "5 MB"

# Media allowlists — content-type AND extension are both checked (a client can lie about
# either). SVG and every non-media type are rejected before any decode/transcode.
_MEDIA_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_MEDIA_IMAGE_CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp")
_MEDIA_GIF_EXTS = (".gif",)
_MEDIA_GIF_CONTENT_TYPES = ("image/gif",)
_MEDIA_VIDEO_EXTS = (".mp4", ".webm")
_MEDIA_VIDEO_CONTENT_TYPES = ("video/mp4", "video/webm")

_AUDIO_EXTS = (".mp3", ".ogg", ".m4a", ".webm", ".wav")
_AUDIO_CONTENT_TYPES = (
    "audio/mpeg", "audio/mp3", "audio/ogg", "audio/mp4", "audio/m4a",
    "audio/x-m4a", "audio/webm", "audio/wav", "audio/wave", "audio/x-wav",
)

_MEDIA_ERROR_COPY = (
    "Ese archivo no se pudo procesar (formato o compresión). Usa una imagen, GIF o vídeo "
    "compatible. — That file couldn't be processed (format or compression). Use a supported "
    "image, GIF or video."
)
_AUDIO_ERROR_COPY = (
    "Ese audio no se pudo subir (formato o tamaño). Usa MP3/OGG/M4A de menos de 5 MB. — "
    "That audio couldn't be uploaded (format or size). Use MP3/OGG/M4A under 5 MB."
)


class MediaProcessingError(Exception):
    """Raised when ffmpeg is unavailable or transcoding fails (fail-closed, T-10.1-11-03)."""


def _too_large_copy(cap_human: str) -> str:
    """Bilingual over-cap copy (D-19) interpolating the human-readable size limit."""
    return (
        f"El archivo supera el límite ({cap_human}). Comprime o elige otro. — "
        f"File exceeds the limit ({cap_human}). Compress or choose another."
    )


def _classify_media(content_type: str, filename: str):
    """Return the media kind for an upload, or ``None`` if it is not accepted media.

    Accepts when EITHER the extension OR the content-type matches an allowlist — browsers
    frequently send an empty/odd content-type for a perfectly valid file (and vice-versa),
    so requiring BOTH to agree wrongly rejected real uploads. SVG is rejected on either
    signal. This is safe because the endpoint RE-ENCODES every accepted file (Pillow for
    images, ffmpeg for gif/video), which fails closed on anything that isn't real media —
    the re-encode, not the header, is the type-confusion guard (T-10.1-11-03).
    """
    if filename.endswith(_REJECTED_EXTS) or content_type in _REJECTED_CONTENT_TYPES:
        return None
    if filename.endswith(_MEDIA_VIDEO_EXTS) or content_type in _MEDIA_VIDEO_CONTENT_TYPES:
        return "video"
    if filename.endswith(_MEDIA_GIF_EXTS) or content_type in _MEDIA_GIF_CONTENT_TYPES:
        return "gif"
    if filename.endswith(_MEDIA_IMAGE_EXTS) or content_type in _MEDIA_IMAGE_CONTENT_TYPES:
        return "image"
    return None


def _is_allowed_audio(content_type: str, filename: str) -> bool:
    """True only if BOTH content-type and extension match the audio allowlist."""
    ext_ok = filename.endswith(_AUDIO_EXTS)
    ct_ok = content_type in _AUDIO_CONTENT_TYPES or content_type.startswith("audio/")
    return ext_ok and ct_ok


def _ffmpeg_transcode_video(raw: bytes) -> bytes:
    """Transcode an uploaded GIF/video to a web-optimized MUTED looping-friendly MP4.

    Runs the system ``ffmpeg`` binary (a distro package on cinema, T-10.1-11-SC — NOT a
    pip dependency) on a temp file. Strips any audio track (``-an`` — background video is
    muted, D-20), normalizes to H.264/yuv420p with ``+faststart`` for fast web start, and
    returns ONLY the re-encoded bytes (the raw upload is never persisted, T-10.1-11-03).

    Raises ``MediaProcessingError`` when ffmpeg is absent, exits non-zero, or produces no
    output — the caller MUST fail closed (never commit an un-optimized file).
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaProcessingError("ffmpeg binary not available")
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "in")
        out_path = os.path.join(tmp, "out.mp4")
        with open(in_path, "wb") as fh:
            fh.write(raw)
        try:
            proc = subprocess.run(
                [
                    ffmpeg, "-y", "-i", in_path,
                    "-an",                       # strip audio — bg video is muted (D-20)
                    "-c:v", "libx264", "-preset", "medium", "-crf", "28",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    out_path,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise MediaProcessingError("ffmpeg invocation failed") from exc
        if proc.returncode != 0 or not os.path.exists(out_path):
            raise MediaProcessingError("ffmpeg transcode failed")
        with open(out_path, "rb") as fh:
            out = fh.read()
    if not out:
        raise MediaProcessingError("ffmpeg produced empty output")
    return out


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
    # Ensure the presence/dashboard tables exist so their read endpoints never 500 if the
    # bot (which normally creates them) hasn't started yet. CREATE TABLE IF NOT EXISTS is
    # idempotent (dual-process defensive init, Pitfall 6) — the three Phase 3 Overview
    # tables (bot_heartbeat/jinxxy_sync_status/activity_log) join the SAME try/except path
    # as the pre-existing presence/view_counts init, not a second init path.
    try:
        db.init_presence()
        db.init_view_counts()  # view_counts/view_dedup — the counter API is served here too
        db.init_heartbeat()
        db.init_jinxxy_sync_status()
        db.init_activity_log()
        db.init_discord_names()
    except Exception:
        log.exception("no pude inicializar las tablas de presencia/vistas/dashboard")
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

# CORS — the ONLY cross-origin consumer is the public site (nocturna-avatars.site)
# fetching the read-only /api/presence/<id> endpoint from this editors-domain app.
# Restrict to that origin + GET; everything else here is same-origin browser navigation.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.WEBSITE_BASE_URL],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.exception_handler(StarletteHTTPException)
async def _auth_html_or_json(request: Request, exc: StarletteHTTPException):
    """Render the right in-shell error page for a browser navigation 401/403; JSON otherwise.

    Three branches, checked in order (Pitfall 2 — extend, never replace/collapse):

    1. A ``TierForbidden`` (raised by ``require_manager``) renders ``forbidden.html``
       parametrized on ``exc.required_tier`` — the dashboard-shell tier-403 page (D-16).
    2. A plain 403 landing on the owner-only Settings route (``require_owner`` itself is
       UNCHANGED — this only unifies its HTML rendering, D-16 / Open Q4) ALSO renders
       ``forbidden.html``, hardcoded to ``required_tier="owner"`` — so a Manager clicking
       the locked Settings nav item sees the bilingual "needs owner access" dead end, not
       ``login.html``'s wrong-audience editor-only copy.
    3. Every other 401/403 navigation (the plain editor-only login gate, and 403s outside
       the dashboard shell) falls back to the original ``login.html`` branch, unchanged.

    Every ``fetch()`` call from the editor/settings/dashboard app itself sends
    ``Accept: application/json`` and keeps getting a JSON error body — this handler only
    changes NAVIGATION (``text/html``) responses.

    ``forbidden.html`` extends ``_dashboard_base.html``, which ``{% include %}``s
    ``_sidebar.html`` — that partial unconditionally reads ``roles.is_owner`` /
    ``.is_manager`` to compute lock icons (D-14). Neither ``TierForbidden`` nor a bare
    ``require_owner`` 403 hands this exception handler a resolved roles dict (re-deriving
    one here would mean a SECOND live Discord role read just to render an error page), so
    both ``forbidden.html`` branches below pass an all-locked ``_NO_TIER_ROLES`` default —
    correct in spirit (a denied caller is shown every section as locked) and, more
    importantly, prevents a ``jinja2.UndefinedError`` from turning this already-denied
    request into an unhandled 500.
    """
    accept_html = "text/html" in request.headers.get("accept", "")

    if isinstance(exc, TierForbidden) and accept_html:
        return templates.TemplateResponse(
            request, "forbidden.html",
            {"required_tier": exc.required_tier, "roles": _NO_TIER_ROLES},
            status_code=exc.status_code)

    if (exc.status_code == 403 and request.url.path == "/admin/settings" and accept_html
            and request.session.get("discord_id")):
        # In-shell owner-tier dead end for an AUTHENTICATED non-owner (e.g. a Manager who
        # clicked the locked Settings nav item). An anonymous visitor (no session) has no
        # dashboard context and must fall through to the login.html branch instead of being
        # shown the shell chrome (WR-02): require_owner returns 403 for a missing session too,
        # so the session-presence guard distinguishes "logged in but not owner" from "not
        # logged in at all".
        return templates.TemplateResponse(
            request, "forbidden.html",
            {"required_tier": "owner", "roles": _NO_TIER_ROLES},
            status_code=403)

    if exc.status_code in (401, 403) and accept_html:
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


# ── Public: live Discord presence for editor pages (no auth) ───────────────────
@app.get("/api/presence/{discord_id}")
async def api_presence(discord_id: str):
    """Read-only live status for one editor, written by the bot's PresenceCog.

    PUBLIC (no ``require_editor``): the public site polls this per page owner. Returns
    ``{"status": "online"|"idle"|"dnd"|"offline"}`` for a tracked editor, or
    ``{"status": null}`` for anyone we don't monitor / a malformed id. Only editors are
    ever in the table (the cog filters on the role), so this never leaks arbitrary users.
    """
    if not discord_id.isdigit() or len(discord_id) > 20:
        return JSONResponse({"status": None})
    row = await run_in_threadpool(db.get_presence, discord_id)
    return JSONResponse({"status": row["status"] if row else None})


# ── Public: per-slug view counter (no auth) ────────────────────────────────────
# Lives HERE (not only counter_app.py) because the Cloudflare tunnel fronts THIS app
# at editors.nocturna-avatars.site — the public site polls /api/views/<slug>?hit=1.
_VIEWS_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _client_ip_hash(request: Request) -> str:
    """SHA-256 of the client IP (never the raw IP) for the dedup window, or "" if none."""
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    return hashlib.sha256(ip.encode("utf-8")).hexdigest() if ip else ""


@app.get("/api/views/{slug}")
async def api_views(slug: str, request: Request, hit: str | None = None):
    """Return (and with ``hit=1`` increment) the per-slug view count. Public, CORS-allowed.

    ``hit=1`` increments once per slug+ip_hash dedup window; without it, a read-only fetch.
    An unknown/malformed slug returns ``{"count": 0}`` — the client always gets an int.
    """
    if not _VIEWS_SLUG_RE.match(slug) or len(slug) > 64:
        return JSONResponse({"count": 0})
    if hit == "1":
        count = await run_in_threadpool(db.increment_view, slug, _client_ip_hash(request))
    else:
        count = await run_in_threadpool(db.get_view_count, slug)
    return JSONResponse({"count": count})


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
            "tagline": "", "links": [], "blocks": [],
        }
    # Cache-buster for /static/editor.css: the file's mtime. Cloudflare caches
    # /static with a long max-age, so a bare href serves stale CSS after a deploy;
    # a ?v=<mtime> query changes the URL on every edit → guaranteed fresh, no manual
    # dashboard purge. The HTML itself carries auth cookies so it is never edge-cached.
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "editor.css"))
    except OSError:
        asset_v = 0
    # D-12: surface whether the SESSION identity is the configured owner, so the
    # template can conditionally render the owner-only settings link. Same fail-closed
    # 0/unset guard as require_owner (a misconfigured owner id must never show the link).
    owner_id = config.DISCORD_USER_ID
    is_owner = bool(owner_id) and str(ident["discord_id"]) == str(owner_id)
    return templates.TemplateResponse(
        request, "editor.html",
        {"entry": entry, "website_base": config.WEBSITE_BASE_URL, "asset_v": asset_v,
         "is_owner": is_owner},
    )


# ── Dashboard shell: 6 operational modules (require_manager) + Overview status ──────
# Section metadata (label/icon/accent) mirrors _sidebar.html's fixed 7-section data
# exactly (Overview is handled separately below since it renders overview.html, not
# module_stub.html). Owner and Manager both satisfy require_manager; Settings itself
# stays on the UNCHANGED require_owner dependency below (D-04/T-03-12).
_MODULE_SECTIONS = {
    "gallery": {"label": "Galería · Gallery", "icon": "🖼", "accent": "var(--accent-gallery)"},
    "reviews": {"label": "Reseñas · Reviews", "icon": "★", "accent": "var(--accent-reviews)"},
    "reminders": {
        "label": "Recordatorios · Reminders", "icon": "⏰", "accent": "var(--accent-reminders)",
    },
    "jinxxy": {"label": "Tienda Jinxxy · Jinxxy Store", "icon": "🛍", "accent": "var(--accent-jinxxy)"},
    "meetings": {"label": "Reuniones · Meetings", "icon": "🎙", "accent": "var(--accent-meetings)"},
}

# The bot is considered "Online" iff its last heartbeat is within 2x the ~45s write
# cadence (Claude's Discretion A2, per 03-07-PLAN.md's <interfaces> block) — a single
# missed beat doesn't flap the status, but two in a row reads as offline.
_HEARTBEAT_STALE_SECONDS = 90
_NAMES_STALE_SECONDS = 15 * 60


def _dashboard_asset_v() -> int:
    """Cache-buster for /static/dashboard.css, same mtime-based idiom as editor.css."""
    try:
        return int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        return 0


def _compute_online(heartbeat_row) -> bool:
    """True iff a heartbeat row exists and its last beat is within the staleness window."""
    if heartbeat_row is None:
        return False
    try:
        last_beat = datetime.fromisoformat(heartbeat_row["last_beat_utc"])
    except (TypeError, ValueError):
        return False
    if last_beat.tzinfo is None:
        last_beat = last_beat.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - last_beat).total_seconds()
    return 0 <= age_seconds <= _HEARTBEAT_STALE_SECONDS


def _compute_uptime(started_at_utc: str | None) -> str | None:
    """Human ``"{h}h {m}m"`` (or ``"{m}m"``) uptime string derived from ``started_at_utc``."""
    if not started_at_utc:
        return None
    try:
        started = datetime.fromisoformat(started_at_utc)
    except (TypeError, ValueError):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    total_seconds = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _build_overview_status(heartbeat, sync, activity_rows) -> dict:
    """Assemble the exact JSON shape ``overview.html``'s Alpine poll consumes (Plan 07
    <interfaces>) from the three raw ``core.db`` rows — gracefully degrading to
    null/empty fields when a table has no rows yet (Pitfall 6: never 500 on a cold DB).
    """
    last_sync = (
        {
            "when": sync["last_run_utc"],
            "ok": bool(sync["ok"]) if sync["ok"] is not None else None,
            "products": sync["product_count"],
        }
        if sync is not None
        else {"when": None, "ok": None, "products": None}
    )
    activity = [
        {"event_type": row["event_type"], "message": row["message"], "when": row["created_at"]}
        for row in activity_rows
    ]
    return {
        "online": _compute_online(heartbeat),
        "latency_ms": heartbeat["latency_ms"] if heartbeat is not None else None,
        "uptime": _compute_uptime(heartbeat["started_at_utc"]) if heartbeat is not None else None,
        "member_count": heartbeat["guild_member_count"] if heartbeat is not None else None,
        "last_sync": last_sync,
        "activity": activity,
    }


async def _read_overview_status() -> dict:
    """Read the three Overview tables off the event loop and assemble the status JSON."""
    heartbeat = await run_in_threadpool(db.get_heartbeat)
    sync = await run_in_threadpool(db.get_jinxxy_sync_status)
    activity_rows = await run_in_threadpool(db.get_recent_activity, 10)
    return _build_overview_status(heartbeat, sync, activity_rows)


async def _bot_online() -> bool:
    """Lightweight online check for the sidebar footer chip on the 5 module-stub pages
    (which don't otherwise need the full status payload the Overview page reads)."""
    heartbeat = await run_in_threadpool(db.get_heartbeat)
    return _compute_online(heartbeat)


async def _read_name_cache() -> tuple[dict, bool]:
    """Return the cached Discord names and whether the newest snapshot is fresh."""
    rows = await run_in_threadpool(db.get_discord_names)
    names = {
        row["id"]: {
            "name": row["name"],
            "kind": row["kind"],
            "subtype": row["subtype"],
            "color": row["color"],
        }
        for row in rows
    }
    if not rows:
        return names, False

    try:
        newest = datetime.fromisoformat(max(row["synced_at"] for row in rows))
    except (TypeError, ValueError):
        return names, False
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - newest).total_seconds()
    return names, 0 <= age_seconds <= _NAMES_STALE_SECONDS


@app.get("/overview", response_class=HTMLResponse)
async def overview_page(request: Request, roles: dict = Depends(require_manager)):
    """Overview module (SHELL-02): status-first stat tiles + recent-activity table.

    ``require_manager`` admits the owner or a Manager (ACCESS-02); the ``roles`` dict is
    passed straight into the render so ``_sidebar.html`` computes lock icons server-side
    (D-14). The initial paint is seeded with the SAME status shape ``/api/overview/status``
    returns (Alpine then polls that endpoint every 30s, D-12) — first paint is populated,
    not a placeholder flash.
    """
    status = await _read_overview_status()
    return templates.TemplateResponse(
        request, "overview.html",
        {
            "roles": roles, "active_section": "overview",
            "asset_v": _dashboard_asset_v(), "bot_online": status["online"],
            **status,
        },
    )


async def _module_stub_page(request: Request, section_id: str, roles: dict):
    """Shared GET handler body for the 5 "coming soon" module routes (D-13)."""
    info = _MODULE_SECTIONS[section_id]
    return templates.TemplateResponse(
        request, "module_stub.html",
        {
            "roles": roles, "active_section": section_id,
            "asset_v": _dashboard_asset_v(), "bot_online": await _bot_online(),
            "section_label": info["label"], "icon": info["icon"], "accent": info["accent"],
        },
    )


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "gallery", roles)


@app.get("/reviews", response_class=HTMLResponse)
async def reviews_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "reviews", roles)


@app.get("/reminders", response_class=HTMLResponse)
async def reminders_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "reminders", roles)


@app.get("/jinxxy", response_class=HTMLResponse)
async def jinxxy_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "jinxxy", roles)


@app.get("/meetings", response_class=HTMLResponse)
async def meetings_page(request: Request, roles: dict = Depends(require_manager)):
    return await _module_stub_page(request, "meetings", roles)


@app.get("/api/overview/status")
async def api_overview_status(roles: dict = Depends(require_manager)):
    """Overview's 30s poll target (D-12) — live bot heartbeat + last Jinxxy sync + recent
    activity, gated by ``require_manager`` (T-03-23: NOT public, unlike ``api_presence``).

    Reads all three tables via ``run_in_threadpool`` and degrades gracefully on an empty
    database (bot never ran): ``online=False``, null fields, ``activity=[]`` — never a 500
    (T-03-24 / Pitfall 6). The returned shape is byte-identical to the seed the
    ``/overview`` route embeds so Alpine's poll can just overwrite ``data`` wholesale.
    """
    return JSONResponse(await _read_overview_status())


@app.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request, ident: dict = Depends(require_owner)):
    """Owner-only settings panel (PANEL-01/02): server-render the grouped, typed tunables.

    ``require_owner`` is the D-10 fail-closed choke point — only the configured
    ``DISCORD_USER_ID`` ever reaches this handler. The rendered payload is exactly
    ``settings.all_for_ui()``, which is built from the ``_SCHEMA`` allowlist — a secret
    (BOT_TOKEN, GITHUB_PAT, JINXXY_API_KEY, SESSION_SECRET) or structural value (DB_PATH)
    can never appear in the body because it is never in that allowlist (PANEL-02).
    """
    names, names_fresh = await _read_name_cache()
    return templates.TemplateResponse(
        request, "settings.html",
        {
            "roles": {"is_owner": True, "is_manager": False, "is_editor": False},
            "active_section": "settings",
            "asset_v": _dashboard_asset_v(),
            "bot_online": await _bot_online(),
            "groups": settings.all_for_ui(),
            "names": names,
            "names_fresh": names_fresh,
        },
    )


@app.post("/admin/settings")
async def save_settings(request: Request, ident: dict = Depends(require_owner)):
    """Atomic two-pass validate-then-write for the owner settings panel (PANEL-03/D-03/D-04/D-05).

    Parses the body with the same 400-on-bad-JSON guard as ``/editor/save``. Then a TWO-PASS
    write: first ``settings.validate_only`` every submitted key into a ``validated`` dict,
    collecting any ``SettingRejected.reason`` into an ``errors`` map keyed by setting key. If
    ANY field is invalid, return 422 with the error map WITHOUT calling ``settings.set`` on
    ANY key — this is the load-bearing atomicity guarantee (D-04): a mixed valid/invalid POST
    must write nothing, not just skip the invalid field. Only when every field validates does
    the second pass call ``settings.set`` for each. Every write is routed through
    ``settings.set`` (never raw SQL), whose ``_SCHEMA`` allowlist is the only way a key can
    reach the database (T-02-10). Identity is ``ident`` from ``require_owner`` (session-only,
    D-08 discipline) — the body supplies only WHAT changes, never WHO asks (T-02-11). CSRF is
    covered by the existing SameSite=Lax session cookie, same as ``/editor/save`` — no
    hand-rolled token (T-02-12).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    errors: dict[str, str] = {}
    validated: dict[str, object] = {}
    for key, raw_value in body.items():
        try:
            validated[key] = settings.validate_only(key, raw_value)  # dry-run, no write
        except settings.SettingRejected as exc:
            errors[key] = exc.reason

    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    for key, value in validated.items():
        settings.set(key, value)

    return {"ok": True, "message": _SETTINGS_SAVED_COPY}


@app.post("/editor/image")
async def upload_image(request: Request, file: UploadFile,
                        ident: dict = Depends(require_editor)):
    """Validate + re-encode an uploaded image, commit it under the entry's media dir.

    Order (Pitfall 3 / T-10-10-01): (1) reject SVG outright by content-type/extension —
    never trusted enough to even attempt a Pillow decode; (2) enforce the byte-size cap
    by streaming in chunks and aborting BEFORE the full body is buffered; (3) decode +
    re-encode via ``optimize_to_webp`` (Pillow's own bomb guard + metadata strip); only
    the RE-ENCODED bytes are ever committed — the raw upload is never persisted.

    The commit path is built from the entry's ``mediaId`` (falling back to its ``slug``
    if unset), fetched fresh SERVER-SIDE from the published entry — ONLY — never a
    client-supplied path segment (T-10-10-06 path traversal / D-08 IDOR).
    """
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type in _REJECTED_CONTENT_TYPES or filename.endswith(_REJECTED_EXTS):
        return JSONResponse(status_code=400, content={"error": _IMAGE_ERROR_COPY})

    # Stream-read with an early abort — never buffer past the cap (size cap BEFORE
    # a full read, Pitfall 3).
    chunks = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_UPLOAD_BYTES:
            return JSONResponse(status_code=400, content={"error": _IMAGE_ERROR_COPY})
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        return JSONResponse(status_code=400, content={"error": _IMAGE_ERROR_COPY})

    try:
        webp_bytes, _w, _h = await run_in_threadpool(optimize_to_webp, raw)
    except Exception:
        # Non-image / decompression-bomb / corrupt input → Pillow decode failure.
        # Never leak the exception internals; nothing has been committed.
        return JSONResponse(status_code=400, content={"error": _IMAGE_ERROR_COPY})

    out_name = f"{uuid.uuid4().hex}.webp"
    current = await _fetch_current_entry(ident["discord_id"])
    if current is None:
        return JSONResponse(status_code=400, content={"error": _IMAGE_ERROR_COPY})
    media_key = current.get("mediaId") or current["slug"]

    try:
        result = await github_publish.sync_editors(
            current, images=[(out_name, webp_bytes)])
    except github_publish.GitHubPublishError:
        log.exception("editor image upload commit failed")
        return JSONResponse(status_code=502, content={"error": _SAVE_FAILED_COPY})

    image_dir = config.WEBSITE_EDITORS_IMAGE_DIR.rstrip("/")
    # Astro serves the public/ dir at the site ROOT, so the public URL must drop a
    # leading "public/" — the committed repo path keeps it, the URL does not.
    url_dir = image_dir[len("public/"):] if image_dir.startswith("public/") else image_dir
    path = f"/{url_dir.lstrip('/')}/{media_key}/{out_name}"
    return {"path": path, "committed": result.get("committed", True)}


@app.post("/editor/media")
async def upload_media(request: Request, file: UploadFile,
                       ident: dict = Depends(require_editor)):
    """Validate + optimize an uploaded BACKGROUND media file (image/GIF/video), then
    commit only the optimized bytes under the entry's media dir (D-18/D-19).

    Order (Pitfall 3 / T-10.1-11-01/03): (1) classify by content-type AND extension —
    SVG + any non-media type is rejected before any decode; (2) stream-read with an early
    abort at the KIND-SPECIFIC cap (image 10 MB · GIF/video 10 MB, D-19) — never buffer
    past the cap; (3) optimize server-side: raster → ``optimize_to_webp`` (Pillow bomb
    guard + metadata strip); GIF/video → ffmpeg transcode to a muted web MP4 (D-20), which
    FAILS CLOSED when ffmpeg is missing/errors (never commit an un-optimized file); (4)
    commit ONLY the re-encoded bytes under the entry's ``mediaId`` (falling back to its
    ``slug`` if unset), fetched fresh SERVER-SIDE — never a client path (T-10.1-11-02 /
    10-D-08). Returns the site-relative path the theme panel writes into
    ``page.theme.bgMedia``.
    """
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    kind = _classify_media(content_type, filename)
    if kind is None:
        log.warning("editor/media rejected (unknown kind): content_type=%r filename=%r",
                    content_type, filename)
        return JSONResponse(status_code=400, content={"error": _MEDIA_ERROR_COPY})

    if kind == "image":
        cap, cap_human = _MEDIA_IMAGE_MAX_BYTES, _MEDIA_IMAGE_CAP_HUMAN
    else:  # gif / video share the 10 MB cap (D-19)
        cap, cap_human = _MEDIA_VIDEO_MAX_BYTES, _MEDIA_VIDEO_CAP_HUMAN

    # Stream-read with an early abort — never buffer past the per-kind cap (Pitfall 3).
    chunks = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            return JSONResponse(status_code=400, content={"error": _too_large_copy(cap_human)})
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        return JSONResponse(status_code=400, content={"error": _MEDIA_ERROR_COPY})

    try:
        if kind == "image":
            out_bytes, _w, _h = await run_in_threadpool(optimize_to_webp, raw)
            out_ext = "webp"
        else:  # gif / video → ffmpeg transcode; fail closed if unavailable/failing
            out_bytes = await run_in_threadpool(_ffmpeg_transcode_video, raw)
            out_ext = "mp4"
    except Exception:
        # Non-media / decompression-bomb / ffmpeg-missing/failure → nothing committed.
        log.exception("editor/media processing failed (kind=%s, content_type=%r, filename=%r)",
                      kind, content_type, filename)
        return JSONResponse(status_code=400, content={"error": _MEDIA_ERROR_COPY})

    out_name = f"{uuid.uuid4().hex}.{out_ext}"
    current = await _fetch_current_entry(ident["discord_id"])
    if current is None:
        return JSONResponse(status_code=400, content={"error": _MEDIA_ERROR_COPY})
    media_key = current.get("mediaId") or current["slug"]

    try:
        result = await github_publish.sync_editors(
            current, images=[(out_name, out_bytes)])
    except github_publish.GitHubPublishError:
        log.exception("editor media upload commit failed")
        return JSONResponse(status_code=502, content={"error": _SAVE_FAILED_COPY})

    image_dir = config.WEBSITE_EDITORS_IMAGE_DIR.rstrip("/")
    # Astro serves the public/ dir at the site ROOT, so the public URL must drop a
    # leading "public/" — the committed repo path keeps it, the URL does not.
    url_dir = image_dir[len("public/"):] if image_dir.startswith("public/") else image_dir
    path = f"/{url_dir.lstrip('/')}/{media_key}/{out_name}"
    return {"path": path, "committed": result.get("committed", True)}


@app.post("/editor/audio")
async def upload_audio(request: Request, file: UploadFile,
                       ident: dict = Depends(require_editor)):
    """Validate + commit an uploaded BACKGROUND audio track under the entry's media dir (D-06).

    (1) Accept only audio by content-type AND extension (MP3/OGG/M4A/WEBM/WAV) — any other
    type is rejected before commit; (2) stream-read with an early abort at the 5 MB cap
    (D-19) — never buffer past the cap; (3) commit the bytes under the entry's ``mediaId``
    (falling back to its ``slug`` if unset), fetched fresh SERVER-SIDE — never a client
    path (T-10.1-11-02 / 10-D-08). Audio is committed as-is within the cap (no transcode
    required); the theme panel (plan 10) writes the returned path into
    ``page.theme.audio``.
    """
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not _is_allowed_audio(content_type, filename):
        return JSONResponse(status_code=400, content={"error": _AUDIO_ERROR_COPY})

    # Stream-read with an early abort — never buffer past the 5 MB cap (Pitfall 3, D-19).
    chunks = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > _AUDIO_MAX_BYTES:
            return JSONResponse(
                status_code=400, content={"error": _too_large_copy(_AUDIO_CAP_HUMAN)})
        chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw:
        return JSONResponse(status_code=400, content={"error": _AUDIO_ERROR_COPY})

    out_ext = next((e for e in _AUDIO_EXTS if filename.endswith(e)), ".mp3").lstrip(".")
    out_name = f"{uuid.uuid4().hex}.{out_ext}"
    current = await _fetch_current_entry(ident["discord_id"])
    if current is None:
        return JSONResponse(status_code=400, content={"error": _AUDIO_ERROR_COPY})
    media_key = current.get("mediaId") or current["slug"]

    try:
        result = await github_publish.sync_editors(
            current, images=[(out_name, raw)])
    except github_publish.GitHubPublishError:
        log.exception("editor audio upload commit failed")
        return JSONResponse(status_code=502, content={"error": _SAVE_FAILED_COPY})

    image_dir = config.WEBSITE_EDITORS_IMAGE_DIR.rstrip("/")
    # Astro serves the public/ dir at the site ROOT, so the public URL must drop a
    # leading "public/" — the committed repo path keeps it, the URL does not.
    url_dir = image_dir[len("public/"):] if image_dir.startswith("public/") else image_dir
    path = f"/{url_dir.lstrip('/')}/{media_key}/{out_name}"
    return {"path": path, "committed": result.get("committed", True)}


def _apply_session_identity(payload: dict, ident: dict, *, slug: str,
                            media_id: str, published: bool) -> dict:
    """Merge a client save payload with SERVER-controlled identity fields (never the body's).

    ``discordId`` is forced from the trusted session (D-08 IDOR guard). ``slug`` is the
    ALREADY-VALIDATED editor-chosen value from ``resolve_slug`` (not the session's stale
    copy). ``mediaId`` is the server-side stable media key. A body attempting to smuggle any
    of these is silently overridden, not merely rejected (Pitfall 1).
    """
    merged = dict(payload)
    merged["discordId"] = str(ident["discord_id"])
    merged["slug"] = slug
    merged["mediaId"] = media_id
    merged["published"] = published
    return merged


@app.post("/editor/save")
async def save_editor(request: Request, ident: dict = Depends(require_editor)):
    """Validate the submitted page via ``EditorPage``, then publish immediately (D-13).

    ``discordId`` is ALWAYS overridden from the session — any body value is discarded
    before validation, never merely rejected (Pitfall 1 / D-08). ``slug`` is now the
    editor's own choice, validated server-side via ``resolve_slug`` (normalized, not
    reserved, not owned by another editor). ``published`` is forced ``True`` — this
    project has no separate draft/publish state (D-13: save publishes immediately).
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Fetch the full array ONCE: it feeds both the uniqueness check and the current entry.
    editors = await run_in_threadpool(
        github_publish._fetch_json,
        config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_EDITORS_JSON)
    current = next(
        (e for e in editors if str(e.get("discordId")) == str(ident["discord_id"])), None)

    # The slug is now editor-chosen — validate it server-side (normalize + reserved + unique).
    try:
        slug = resolve_slug(
            body.get("slug", ""), self_discord_id=ident["discord_id"], editors=editors)
    except SlugRejected as exc:
        status, copy = _SLUG_REJECT[exc.reason]
        return JSONResponse(status_code=status, content={"error": copy})

    # mediaId is stable: reuse the entry's; backfill a pre-feature entry to its CURRENT slug
    # (where its media already lives); brand-new-with-no-draft falls back to the new slug.
    media_id = (current or {}).get("mediaId") or (current or {}).get("slug") or slug

    merged = _apply_session_identity(body, ident, slug=slug, media_id=media_id, published=True)

    try:
        entry = EditorPage(**merged).model_dump()
    except ValidationError as exc:
        # Validation errors are safe to surface (input feedback, not infra internals).
        return JSONResponse(status_code=422, content={"error": str(exc)})

    try:
        # prune=True: at Save the entry is the complete source of truth, so orphaned
        # media in this editor's mediaId dir is cleaned up (never on the upload commits).
        await github_publish.sync_editors(entry, prune=True)
    except github_publish.GitHubPublishError:
        log.exception("editor save commit failed")
        return JSONResponse(status_code=502, content={"error": _SAVE_FAILED_COPY})

    # Keep the session slug consistent after a rename (used by the editor GET fallback).
    request.session["slug"] = slug
    return {"message": _PUBLISH_SUCCESS_COPY, "published": True}


@app.post("/editor/unpublish")
async def unpublish_self(ident: dict = Depends(require_editor)):
    """Self-unpublish (D-16): flip the SESSION editor's page to ``published=false``.

    Delegates to ``unpublish_editor`` keyed by the session's ``discord_id`` only — no
    other editor's page can ever be targeted (D-08).
    """
    try:
        result = await github_publish.unpublish_editor(ident["discord_id"])
    except github_publish.GitHubPublishError:
        log.exception("editor unpublish commit failed")
        return JSONResponse(status_code=502, content={"error": _UNPUBLISH_FAILED_COPY})

    return {"message": _UNPUBLISH_SUCCESS_COPY, "committed": result.get("committed", False)}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    validate_config()
    # Bind to loopback ONLY — Caddy fronts it and terminates HTTPS (Pitfall 8).
    uvicorn.run(app, host="127.0.0.1", port=8770)
