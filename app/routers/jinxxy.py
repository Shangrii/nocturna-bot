"""Manager-gated Jinxxy catalog status and deduped manual-sync routes."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.deps import bot_online, require_manager
from core import action_queue, db

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))


def _sync_payload(sync_row, online: bool) -> dict:
    """Build the Manager-safe running and last-result status contract."""
    never_synced = (
        sync_row is None
        or sync_row["last_run_utc"] is None
    )
    ok = (
        bool(sync_row["ok"])
        if sync_row is not None and sync_row["ok"] is not None
        else None
    )
    return {
        "bot_online": online,
        "never_synced": never_synced,
        "running": bool(sync_row and sync_row["running"]) and online,
        "started_at": sync_row["started_at"] if sync_row else None,
        "source": sync_row["source"] if sync_row else None,
        "actor_name": sync_row["actor_name"] if sync_row else None,
        "last_run_utc": sync_row["last_run_utc"] if sync_row else None,
        "ok": ok,
        "product_count": sync_row["product_count"] if sync_row else None,
        "added": sync_row["added_count"] if sync_row else None,
        "updated": sync_row["updated_count"] if sync_row else None,
        "removed": sync_row["removed_count"] if sync_row else None,
    }


async def _products() -> list[dict]:
    """Return the public catalog projection, sorted by name without case bias."""
    snapshot = await run_in_threadpool(db.get_store_snapshot)
    products = [
        {
            "name": row["name"],
            "price": row["price"],
            "category": row["category"],
            "nsfw": bool(row["nsfw"]),
            "date": row["date"],
            "checkout_url": row["checkout_url"],
        }
        for row in snapshot.values()
    ]
    return sorted(
        products,
        key=lambda product: str(product["name"] or "").casefold(),
    )


async def _status() -> tuple[dict, bool]:
    """Read the sync mirror and heartbeat-derived liveness off the event loop."""
    sync_row = await run_in_threadpool(db.get_jinxxy_sync_status)
    online = await bot_online()
    return _sync_payload(sync_row, online), online


@router.get("/jinxxy", response_class=HTMLResponse)
async def jinxxy_page(
    request: Request,
    roles: dict = Depends(require_manager),
):
    sync, online = await _status()
    products = await _products()
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        asset_v = 0
    template_name = (
        "jinxxy.html"
        if (_APP_DIR / "templates" / "jinxxy.html").is_file()
        else "module_stub.html"
    )
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "roles": roles,
            "active_section": "jinxxy",
            "asset_v": asset_v,
            "bot_online": online,
            "section_label": "Tienda Jinxxy · Jinxxy Store",
            "icon": "🛍",
            "accent": "var(--accent-jinxxy)",
            "sync": sync,
            "products": products,
        },
    )


@router.get("/jinxxy/status", response_class=JSONResponse)
async def jinxxy_status(roles: dict = Depends(require_manager)):
    sync, _ = await _status()
    return JSONResponse(sync)


@router.post("/jinxxy/sync")
async def trigger_jinxxy_sync(
    roles: dict = Depends(require_manager),
):
    actor_name = roles.get("username") or str(roles["discord_id"])
    action_id = await run_in_threadpool(
        action_queue.enqueue_deduped,
        "jinxxy_sync",
        {"actor_name": actor_name},
        str(roles["discord_id"]),
    )
    return JSONResponse({"id": action_id})
