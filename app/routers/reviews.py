"""Manager-gated reviews cache and approval queue routes."""

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
    pending = await run_in_threadpool(db.get_reviews_queue, "pending")
    published = await run_in_threadpool(db.get_reviews_queue, "published")
    return pending, published


@router.get("/reviews", response_class=HTMLResponse)
async def reviews_page(
    request: Request, roles: dict = Depends(require_manager)
):
    pending, published = await _queue_rows()
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        asset_v = 0
    template_name = (
        "reviews.html"
        if (_APP_DIR / "templates" / "reviews.html").is_file()
        else "module_stub.html"
    )
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "roles": roles,
            "active_section": "reviews",
            "asset_v": asset_v,
            "bot_online": False,
            "pending_rows": pending,
            "published_rows": published,
            "section_label": "Reseñas · Reviews",
            "icon": "★",
            "accent": "var(--accent-reviews)",
        },
    )


@router.get("/reviews/queue", response_class=JSONResponse)
async def reviews_queue(roles: dict = Depends(require_manager)):
    pending, published = await _queue_rows()
    return JSONResponse(
        {
            "pending": [dict(row) for row in pending],
            "published": [dict(row) for row in published],
        }
    )


async def _enqueue_review_action(
    message_id: int, kind: str, roles: dict
) -> JSONResponse:
    row = await run_in_threadpool(db.get_reviews_queue_row, message_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="reseña no encontrada · review not found",
        )
    action_id = await run_in_threadpool(
        action_queue.enqueue,
        kind,
        {"message_id": message_id},
        str(roles["discord_id"]),
    )
    return JSONResponse({"id": action_id})


@router.post("/reviews/{message_id}/approve")
async def approve_review(
    message_id: int, roles: dict = Depends(require_manager)
):
    return await _enqueue_review_action(message_id, "review_publish", roles)


@router.post("/reviews/{message_id}/remove")
async def remove_review(
    message_id: int, roles: dict = Depends(require_manager)
):
    return await _enqueue_review_action(message_id, "review_remove", roles)
