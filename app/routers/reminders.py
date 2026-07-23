"""Manager-gated FastAPI routes for reminder CRUD, pause/resume, and preview."""

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

import config
from app.deps import require_manager
from core import db
from core.reminder_schedule import (
    is_imminent,
    next_biweekly_fire,
    next_monthly_fire,
    next_oneoff_fire,
    next_weekly_fire,
    parse_date,
    parse_emojis,
    parse_time,
    schedule_summary,
    valid_day_of_month,
    valid_weekday,
)

router = APIRouter()

_APP_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(_APP_DIR / "templates"))

_FREQUENCIES = {"weekly", "biweekly", "monthly", "oneoff"}
_CONFLICT_COPY = (
    "Este recordatorio cambió mientras editabas — recarga la página. · "
    "This reminder changed while you were editing — reload the page."
)


async def _read_json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    return body


def _integer(raw, field: str, errors: dict[str, str]) -> int | None:
    try:
        if isinstance(raw, bool):
            raise ValueError
        return int(raw)
    except (TypeError, ValueError):
        errors[field] = "Debe ser un número entero. · Must be an integer."
        return None


def _compute_next(schedule: dict, now_utc: datetime) -> datetime:
    frequency = schedule["frequency"]
    if frequency == "weekly":
        return next_weekly_fire(
            now_utc,
            schedule["weekday"],
            schedule["hour"],
            schedule["minute"],
            config.REMINDERS_TZ,
        )
    if frequency == "biweekly":
        return next_biweekly_fire(
            now_utc,
            schedule["run_date"],
            schedule["hour"],
            schedule["minute"],
            config.REMINDERS_TZ,
        )
    if frequency == "monthly":
        return next_monthly_fire(
            now_utc,
            schedule["day_of_month"],
            schedule["hour"],
            schedule["minute"],
            config.REMINDERS_TZ,
        )
    return next_oneoff_fire(
        schedule["run_date"],
        schedule["hour"],
        schedule["minute"],
        config.REMINDERS_TZ,
    )


def _validate_schedule(
    body: dict,
    *,
    now_utc: datetime,
    reject_past_oneoff: bool = True,
) -> tuple[dict, dict[str, str]]:
    errors: dict[str, str] = {}
    frequency = str(body.get("frequency", "")).strip().lower()
    if frequency not in _FREQUENCIES:
        errors["frequency"] = (
            "Elige weekly, biweekly, monthly u oneoff. · Choose a valid frequency."
        )

    try:
        hour, minute = parse_time(body.get("time", ""))
    except (TypeError, ValueError):
        errors["time"] = "Usa una hora válida HH:MM. · Use a valid HH:MM time."
        hour = minute = None

    schedule = {
        "frequency": frequency,
        "weekday": None,
        "day_of_month": None,
        "run_date": None,
        "hour": hour,
        "minute": minute,
    }

    if frequency == "weekly":
        weekday = _integer(body.get("weekday"), "weekday", errors)
        if weekday is not None and not valid_weekday(weekday):
            errors["weekday"] = "Debe estar entre 0 y 6. · Must be between 0 and 6."
        schedule["weekday"] = weekday
    elif frequency == "monthly":
        day = _integer(body.get("day_of_month"), "day_of_month", errors)
        if day is not None and not valid_day_of_month(day):
            errors["day_of_month"] = "Debe estar entre 1 y 31. · Must be between 1 and 31."
        schedule["day_of_month"] = day
    elif frequency in {"biweekly", "oneoff"}:
        run_date = str(body.get("run_date", "")).strip()
        try:
            parse_date(run_date)
        except (TypeError, ValueError):
            errors["run_date"] = (
                "Usa una fecha válida YYYY-MM-DD. · Use a valid YYYY-MM-DD date."
            )
        schedule["run_date"] = run_date or None

    if not errors:
        next_fire = _compute_next(schedule, now_utc)
        if (
            frequency == "oneoff"
            and reject_past_oneoff
            and next_fire <= now_utc
        ):
            errors["run_date"] = (
                "La fecha y hora ya pasaron. · The date and time are in the past."
            )
        else:
            schedule["next_fire_utc"] = next_fire.isoformat()

    return schedule, errors


def _validate_record(
    body: dict, *, now_utc: datetime
) -> tuple[dict, dict[str, str]]:
    validated, errors = _validate_schedule(body, now_utc=now_utc)

    name = str(body.get("name", "")).strip()
    if not name:
        errors["name"] = "El nombre es obligatorio. · Name is required."
    elif len(name) > 80:
        errors["name"] = "Máximo 80 caracteres. · Maximum 80 characters."

    channel_id = _integer(body.get("channel_id"), "channel_id", errors)
    if channel_id is not None and channel_id <= 0:
        errors["channel_id"] = "El canal no es válido. · Channel is invalid."

    message = str(body.get("message", "")).strip()
    if not message:
        errors["message"] = "El mensaje es obligatorio. · Message is required."

    mentions = body.get("mentions", "")
    if not isinstance(mentions, str):
        errors["mentions"] = "La mención no es válida. · Mention is invalid."
        mentions = ""

    if body.get("mention_id") not in (None, ""):
        mention_id = _integer(body.get("mention_id"), "mention_id", errors)
        if mention_id is not None and mention_id > 0:
            mentions = f"<@&{mention_id}>"
        elif mention_id is not None:
            errors["mention_id"] = "El rol no es válido. · Role is invalid."

    validated.update(
        {
            "name": name,
            "channel_id": channel_id,
            "message": message,
            "mentions": mentions.strip(),
            "reactions": " ".join(parse_emojis(str(body.get("reactions", "")))),
        }
    )
    return validated, errors


def _expected_version(body: dict) -> tuple[int | None, dict[str, str]]:
    errors: dict[str, str] = {}
    version = _integer(body.get("version"), "version", errors)
    if version is not None and version < 1:
        errors["version"] = "La versión no es válida. · Version is invalid."
    return version, errors


def _conflict() -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": _CONFLICT_COPY})


def _relative_fire(value: str, now_utc: datetime) -> str:
    try:
        target = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return "—"
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    seconds = int((target - now_utc).total_seconds())
    future = seconds >= 0
    span = abs(seconds)
    if span < 3600:
        amount, unit_es, unit_en = max(1, span // 60), "min", "min"
    elif span < 86400:
        amount, unit_es, unit_en = span // 3600, "h", "h"
    else:
        amount, unit_es, unit_en = span // 86400, "d", "d"
    if future:
        return f"en {amount}{unit_es} · in {amount}{unit_en}"
    return f"hace {amount}{unit_es} · {amount}{unit_en} ago"


def _render_rows(rows, cached_names, now_utc: datetime) -> tuple[list[dict], list[dict]]:
    names = [dict(row) for row in cached_names]
    by_key = {(row["kind"], str(row["id"])): row for row in names}
    rendered: list[dict] = []

    for source in rows:
        row = dict(source)
        channel_id = str(row["channel_id"])
        channel = by_key.get(("channel", channel_id))
        mention_match = re.fullmatch(r"<@&(\d+)>", row.get("mentions") or "")
        mention_id = mention_match.group(1) if mention_match else None
        mention = by_key.get(("role", mention_id)) if mention_id else None
        paused = bool(row["paused"])
        try:
            next_fire = datetime.fromisoformat(row["next_fire_utc"])
            if next_fire.tzinfo is None:
                next_fire = next_fire.replace(tzinfo=timezone.utc)
            imminent = is_imminent(next_fire, now_utc)
        except (TypeError, ValueError):
            imminent = False

        row.update(
            {
                "schedule_summary": schedule_summary(row, config.REMINDERS_TZ),
                "channel_name": f"#{channel['name']}" if channel else "#unknown-channel",
                "channel_cache_miss": channel is None,
                "mention_name": f"@{mention['name']}" if mention else (
                    "#deleted" if mention_id else ""
                ),
                "mention_id": mention_id,
                "mention_cache_miss": bool(mention_id and mention is None),
                "next_fire_relative": "—" if paused else _relative_fire(
                    row["next_fire_utc"], now_utc
                ),
                "status": "paused" if paused else "active",
                "imminent": imminent,
                "time": f"{int(row['hour']):02d}:{int(row['minute']):02d}",
            }
        )
        rendered.append(row)

    rendered.sort(key=lambda row: (bool(row["paused"]), row["next_fire_utc"]))
    return rendered, names


@router.get("/reminders", response_class=HTMLResponse)
async def reminders_page(
    request: Request, roles: dict = Depends(require_manager)
):
    rows = await run_in_threadpool(db.list_reminders)
    cached_names = await run_in_threadpool(db.get_discord_names)
    now_utc = datetime.now(timezone.utc)
    rendered_rows, names = _render_rows(rows, cached_names, now_utc)
    try:
        asset_v = int(os.path.getmtime(_APP_DIR / "static" / "dashboard.css"))
    except OSError:
        asset_v = 0
    template_name = (
        "reminders.html"
        if (_APP_DIR / "templates" / "reminders.html").is_file()
        else "module_stub.html"
    )
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "roles": roles,
            "active_section": "reminders",
            "asset_v": asset_v,
            "bot_online": False,
            "rows": rendered_rows,
            "names": names,
            "section_label": "Recordatorios · Reminders",
            "icon": "⏰",
            "accent": "var(--accent-reminders)",
        },
    )


@router.post("/reminders")
async def create_reminder(
    request: Request, roles: dict = Depends(require_manager)
):
    body = await _read_json(request)
    validated, errors = _validate_record(body, now_utc=datetime.now(timezone.utc))
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    reminder_id = await run_in_threadpool(
        db.add_reminder,
        name=validated["name"],
        frequency=validated["frequency"],
        weekday=validated["weekday"],
        day_of_month=validated["day_of_month"],
        run_date=validated["run_date"],
        hour=validated["hour"],
        minute=validated["minute"],
        channel_id=validated["channel_id"],
        message=validated["message"],
        mentions=validated["mentions"],
        reactions=validated["reactions"],
        next_fire_utc=validated["next_fire_utc"],
        created_by=int(roles["discord_id"]),
    )
    return JSONResponse({"ok": True, "id": reminder_id})


@router.post("/reminders/preview")
async def preview_reminder(
    request: Request, roles: dict = Depends(require_manager)
):
    body = await _read_json(request)
    schedule, errors = _validate_schedule(
        body, now_utc=datetime.now(timezone.utc)
    )
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})
    return JSONResponse(
        {
            "next_fire_utc": schedule["next_fire_utc"],
            "summary": schedule_summary(schedule, config.REMINDERS_TZ),
        }
    )


@router.post("/reminders/{reminder_id}")
async def edit_reminder(
    reminder_id: int,
    request: Request,
    roles: dict = Depends(require_manager),
):
    body = await _read_json(request)
    validated, errors = _validate_record(body, now_utc=datetime.now(timezone.utc))
    version, version_errors = _expected_version(body)
    errors.update(version_errors)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    ok = await run_in_threadpool(
        db.update_reminder,
        reminder_id,
        expected_version=version,
        **validated,
    )
    if not ok:
        return _conflict()
    return JSONResponse({"ok": True})


@router.post("/reminders/{reminder_id}/delete")
async def delete_reminder(
    reminder_id: int,
    request: Request,
    roles: dict = Depends(require_manager),
):
    body = await _read_json(request)
    version, errors = _expected_version(body)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})
    ok = await run_in_threadpool(
        db.delete_reminder, reminder_id, expected_version=version
    )
    if not ok:
        return _conflict()
    return JSONResponse({"ok": True})


@router.post("/reminders/{reminder_id}/pause")
async def pause_reminder(
    reminder_id: int,
    request: Request,
    roles: dict = Depends(require_manager),
):
    body = await _read_json(request)
    version, errors = _expected_version(body)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})
    ok = await run_in_threadpool(
        db.update_reminder,
        reminder_id,
        expected_version=version,
        paused=1,
    )
    if not ok:
        return _conflict()
    return JSONResponse({"ok": True})


@router.post("/reminders/{reminder_id}/resume")
async def resume_reminder(
    reminder_id: int,
    request: Request,
    roles: dict = Depends(require_manager),
):
    body = await _read_json(request)
    version, errors = _expected_version(body)
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    row = await run_in_threadpool(db.get_reminder, reminder_id)
    if row is None:
        return _conflict()
    now_utc = datetime.now(timezone.utc)
    schedule = dict(row)
    if schedule["frequency"] == "oneoff":
        scheduled = next_oneoff_fire(
            schedule["run_date"],
            schedule["hour"],
            schedule["minute"],
            config.REMINDERS_TZ,
        )
        next_fire = now_utc if scheduled <= now_utc else scheduled
    else:
        next_fire = _compute_next(schedule, now_utc)

    ok = await run_in_threadpool(
        db.update_reminder,
        reminder_id,
        expected_version=version,
        paused=0,
        next_fire_utc=next_fire.isoformat(),
    )
    if not ok:
        return _conflict()
    return JSONResponse({"ok": True, "next_fire_utc": next_fire.isoformat()})
