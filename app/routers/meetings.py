"""Manager-gated meeting history and deduped re-publish routes."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

from app.deps import bot_online, require_manager
from core import action_queue, db

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parents[1]
_SUMMARY_MAX_LENGTH = 4096
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))


def _asset_version() -> int:
    try:
        return int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        return 0


@router.get("/meetings", response_class=HTMLResponse)
async def meetings_page(
    request: Request,
    roles: dict = Depends(require_manager),
):
    rows = await run_in_threadpool(db.list_meetings)
    return templates.TemplateResponse(
        request,
        "meetings.html",
        {
            "roles": roles,
            "active_section": "meetings",
            "asset_v": _asset_version(),
            "bot_online": await bot_online(),
            "rows": rows,
            "section_label": "Reuniones",
            "icon": "🎙",
            "accent": "var(--accent-meetings)",
        },
    )


@router.get("/meetings/{meeting_id}", response_class=HTMLResponse)
async def meeting_detail_page(
    meeting_id: int,
    request: Request,
    roles: dict = Depends(require_manager),
):
    row = await run_in_threadpool(db.get_meeting, meeting_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="reunión no encontrada",
        )
    return templates.TemplateResponse(
        request,
        "meeting_detail.html",
        {
            "roles": roles,
            "active_section": "meetings",
            "asset_v": _asset_version(),
            "bot_online": await bot_online(),
            "meeting": row,
        },
    )


@router.post("/meetings/{meeting_id}/republish")
async def republish_meeting(
    meeting_id: int,
    request: Request,
    roles: dict = Depends(require_manager),
):
    body = await request.json()
    new_summary = (body.get("summary") or "").strip()[:_SUMMARY_MAX_LENGTH]
    await run_in_threadpool(
        db.update_meeting_summary,
        meeting_id,
        new_summary,
    )

    actor_name = roles.get("username") or str(roles["discord_id"])
    action_id = await run_in_threadpool(
        action_queue.enqueue_deduped,
        "meeting_republish",
        {"meeting_id": meeting_id, "actor_name": actor_name},
        str(roles["discord_id"]),
        dedupe_key=f"meeting_republish:{meeting_id}",
    )
    return JSONResponse({"id": action_id})
