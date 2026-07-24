"""Manager-gated gallery cache and approval queue routes."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.deps import require_manager
from core import action_queue, db

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))


async def _queue_rows() -> tuple[list, list]:
    pending = await run_in_threadpool(db.get_gallery_queue, "pending")
    published = await run_in_threadpool(db.get_gallery_queue, "published")
    return pending, published


@router.get("/gallery", response_class=HTMLResponse)
async def gallery_page(
    request: Request, roles: dict = Depends(require_manager)
):
    pending, published = await _queue_rows()
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        asset_v = 0
    template_name = (
        "gallery.html"
        if (_APP_DIR / "templates" / "gallery.html").is_file()
        else "module_stub.html"
    )
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "roles": roles,
            "active_section": "gallery",
            "asset_v": asset_v,
            "bot_online": False,
            "pending_rows": pending,
            "published_rows": published,
            "section_label": "Galería · Gallery",
            "icon": "🖼",
            "accent": "var(--accent-gallery)",
        },
    )


@router.get("/gallery/queue", response_class=JSONResponse)
async def gallery_queue(roles: dict = Depends(require_manager)):
    pending, published = await _queue_rows()
    return JSONResponse(
        {
            "pending": [dict(row) for row in pending],
            "published": [dict(row) for row in published],
        }
    )


async def _enqueue_gallery_action(
    message_id: int, kind: str, roles: dict
) -> JSONResponse:
    row = await run_in_threadpool(db.get_gallery_queue_row, message_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="foto no encontrada · photo not found",
        )
    action_id = await run_in_threadpool(
        action_queue.enqueue,
        kind,
        {"message_id": message_id},
        str(roles["discord_id"]),
    )
    return JSONResponse({"id": action_id})


@router.post("/gallery/{message_id}/approve")
async def approve_gallery_item(
    message_id: int, roles: dict = Depends(require_manager)
):
    return await _enqueue_gallery_action(message_id, "gallery_publish", roles)


@router.post("/gallery/{message_id}/remove")
async def remove_gallery_item(
    message_id: int, roles: dict = Depends(require_manager)
):
    return await _enqueue_gallery_action(message_id, "gallery_remove", roles)
