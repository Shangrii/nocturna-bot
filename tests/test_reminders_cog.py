"""Unit tests for the pure schedule-math + validators + staff gate of the reminders cog (08-02).

This suite proves the deterministic, high-risk core of the reminders scheduler BEFORE any
Discord wiring exists (the cog class / scheduler / modal arrive in 08-03/08-04). Every helper
under test is a pure module-level function with no Discord/DB dependency, so the tests are plain
``assert fn(...) == expected`` — matching the repo idiom (SimpleNamespace fakes, no pytest-asyncio).

Coverage: weekly/monthly/one-off next-fire, month-end clamp (incl. leap Feb), a DST-boundary
zone case, catch-up classification (ontime/late/skip), the input validators, the emoji cap, the
schedule summary, and the ``_is_staff`` role gate.
"""

import asyncio
import types
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
import pytest
from discord import app_commands

import config
from cogs import reminders

MX = ZoneInfo("America/Mexico_City")
NY = ZoneInfo("America/New_York")

STAFF_ROLE_ID = 111
OTHER_ROLE_ID = 222


def _member(role_ids, is_bot=False):
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids],
        bot=is_bot,
    )


def _local(y, m, d, h, mi, zone=MX):
    """A UTC ``now`` built from a local wall time in ``zone`` (the scheduler input shape)."""
    return datetime(y, m, d, h, mi, tzinfo=zone).astimezone(timezone.utc)


# ── _clamp_day (D-08 month-end + leap year) ───────────────────────────────────────
def test_clamp_day_short_month_and_leap():
    assert reminders._clamp_day(2027, 2, 31) == 28      # non-leap February
    assert reminders._clamp_day(2028, 2, 31) == 29      # leap February
    assert reminders._clamp_day(2027, 4, 31) == 30      # 30-day April
    assert reminders._clamp_day(2027, 1, 15) == 15      # in-range day untouched


# ── next_weekly_fire (D-06/D-09) ──────────────────────────────────────────────────
def test_weekly_wednesday_to_next_monday():
    now = _local(2026, 7, 8, 10, 0)                     # a Wednesday 10:00 local
    res = reminders.next_weekly_fire(now, 0, 9, 0, "America/Mexico_City")   # Monday 09:00
    assert res.tzinfo == timezone.utc
    res_local = res.astimezone(MX)
    assert res_local.weekday() == 0                     # Monday
    assert (res_local.hour, res_local.minute) == (9, 0)
    assert now.astimezone(MX) < res_local
    assert (res_local.date() - now.astimezone(MX).date()).days <= 7


def test_weekly_same_day_later_today_is_today():
    now = _local(2026, 7, 8, 10, 0)                     # Wednesday 10:00
    res = reminders.next_weekly_fire(now, 2, 14, 0, "America/Mexico_City")  # Wed 14:00 today
    res_local = res.astimezone(MX)
    assert (res_local.month, res_local.day) == (7, 8)   # still today
    assert (res_local.hour, res_local.minute) == (14, 0)


def test_weekly_same_day_already_passed_rolls_a_week():
    now = _local(2026, 7, 8, 10, 0)                     # Wednesday 10:00
    res = reminders.next_weekly_fire(now, 2, 8, 0, "America/Mexico_City")   # Wed 08:00 (passed)
    res_local = res.astimezone(MX)
    assert res_local.weekday() == 2                     # still a Wednesday
    assert (res_local.date() - now.astimezone(MX).date()).days == 7


# ── next_monthly_fire (D-06/D-08) ─────────────────────────────────────────────────
def test_monthly_day15_from_the_20th_rolls_to_next_month():
    now = _local(2027, 1, 20, 12, 0)
    res = reminders.next_monthly_fire(now, 15, 9, 0, "America/Mexico_City").astimezone(MX)
    assert (res.year, res.month, res.day) == (2027, 2, 15)
    assert (res.hour, res.minute) == (9, 0)


def test_monthly_day15_from_the_10th_is_this_month():
    now = _local(2027, 1, 10, 12, 0)
    res = reminders.next_monthly_fire(now, 15, 9, 0, "America/Mexico_City").astimezone(MX)
    assert (res.year, res.month, res.day) == (2027, 1, 15)


def test_monthly_day31_clamps_to_last_february_day():
    now = _local(2027, 1, 31, 12, 0)                    # Jan 31 12:00, 09:00 already passed
    res = reminders.next_monthly_fire(now, 31, 9, 0, "America/Mexico_City").astimezone(MX)
    assert (res.year, res.month, res.day) == (2027, 2, 28)   # clamped to Feb 28 (non-leap)


# ── DST boundary (Pitfall 3) — wall time preserved, UTC offset changes ─────────────
def test_weekly_across_spring_forward_keeps_wall_time():
    now = _local(2026, 3, 6, 10, 0, zone=NY)            # Fri before US spring-forward (Mar 8)
    res = reminders.next_weekly_fire(now, 1, 9, 0, "America/New_York")      # next Tue 09:00
    res_local = res.astimezone(NY)
    assert res_local.weekday() == 1                     # Tuesday, AFTER the DST boundary
    assert (res_local.hour, res_local.minute) == (9, 0)   # 09:00 wall time preserved
    assert res_local.utcoffset() == timedelta(hours=-4)   # now EDT, not EST


# ── next_oneoff_fire (D-06) ───────────────────────────────────────────────────────
def test_oneoff_fire_local_to_utc():
    res = reminders.next_oneoff_fire("2026-12-25", "18", "30")   # default tz Mexico City
    res_local = res.astimezone(MX)
    assert (res_local.year, res_local.month, res_local.day) == (2026, 12, 25)
    assert (res_local.hour, res_local.minute) == (18, 30)
    assert res.tzinfo == timezone.utc


# ── compute_next dispatch (weekly/monthly recompute; oneoff unchanged) ─────────────
def test_compute_next_dispatches_weekly():
    now = _local(2026, 7, 8, 10, 0)
    row = {"frequency": "weekly", "weekday": 0, "day_of_month": None,
           "run_date": None, "hour": 9, "minute": 0, "next_fire_utc": ""}
    expected = reminders.next_weekly_fire(now, 0, 9, 0, config.REMINDERS_TZ)
    assert reminders.compute_next(row, now) == expected


def test_compute_next_dispatches_monthly():
    now = _local(2027, 1, 20, 12, 0)
    row = {"frequency": "monthly", "weekday": None, "day_of_month": 15,
           "run_date": None, "hour": 9, "minute": 0, "next_fire_utc": ""}
    expected = reminders.next_monthly_fire(now, 15, 9, 0, config.REMINDERS_TZ)
    assert reminders.compute_next(row, now) == expected


def test_compute_next_oneoff_is_not_recomputed():
    now = _local(2026, 7, 8, 10, 0)
    stored = _local(2026, 12, 25, 18, 30)
    row = {"frequency": "oneoff", "weekday": None, "day_of_month": None,
           "run_date": "2026-12-25", "hour": 18, "minute": 30,
           "next_fire_utc": stored.isoformat()}
    # oneoff is fired once then deleted by the scheduler → compute_next returns it unchanged.
    assert reminders.compute_next(row, now) == stored


# ── classify_fire (D-13 catch-up window) ──────────────────────────────────────────
def test_classify_fire_ontime_late_skip():
    nf = datetime(2026, 7, 8, 15, 0, tzinfo=timezone.utc)
    assert reminders.classify_fire(nf, nf, 6) == "ontime"
    assert reminders.classify_fire(nf + timedelta(minutes=2), nf, 6) == "ontime"
    assert reminders.classify_fire(nf + timedelta(hours=2), nf, 6) == "late"
    assert reminders.classify_fire(nf + timedelta(hours=7), nf, 6) == "skip"


# ── validators (T-08-04) ──────────────────────────────────────────────────────────
def test_parse_time_accepts_valid_and_rejects_malformed():
    assert reminders.parse_time("09:05") == (9, 5)
    assert reminders.parse_time("9:5") == (9, 5)        # documented: 1- or 2-digit fields OK
    for bad in ("24:00", "9", "ab:cd", "09:60", "", "09:05:00"):
        with pytest.raises(ValueError):
            reminders.parse_time(bad)


def test_parse_date_accepts_valid_and_rejects_malformed():
    assert reminders.parse_date("2026-12-25") == date(2026, 12, 25)
    for bad in ("2026-13-01", "nope", "2026/12/25", "2026-12-32"):
        with pytest.raises(ValueError):
            reminders.parse_date(bad)


def test_valid_weekday_bounds():
    assert reminders.valid_weekday(0) is True
    assert reminders.valid_weekday(6) is True
    assert reminders.valid_weekday(7) is False
    assert reminders.valid_weekday(-1) is False


def test_valid_day_of_month_bounds():
    assert reminders.valid_day_of_month(1) is True
    assert reminders.valid_day_of_month(31) is True
    assert reminders.valid_day_of_month(0) is False
    assert reminders.valid_day_of_month(32) is False


# ── parse_emojis (T-08-07 seeded-reaction cap) ────────────────────────────────────
def test_parse_emojis_splits_dedupes_and_caps():
    assert reminders.parse_emojis("✅ ❌") == ["✅", "❌"]
    assert reminders.parse_emojis("✅, ❌") == ["✅", "❌"]        # comma separated
    assert reminders.parse_emojis("✅ ✅ ❌") == ["✅", "❌"]       # dedupe, order preserved
    assert reminders.parse_emojis("") == []
    assert reminders.parse_emojis("   ") == []
    capped = reminders.parse_emojis("a b c d e f g h", cap=6)
    assert len(capped) <= 6


# ── schedule_summary (autocomplete label / listar line) ───────────────────────────
def test_schedule_summary_distinguishes_frequencies():
    weekly = reminders.schedule_summary(
        {"name": "Junta", "frequency": "weekly", "weekday": 0,
         "day_of_month": None, "run_date": None, "hour": 9, "minute": 0}, "America/Mexico_City")
    monthly = reminders.schedule_summary(
        {"name": "Pago", "frequency": "monthly", "weekday": None,
         "day_of_month": 15, "run_date": None, "hour": 9, "minute": 0}, "America/Mexico_City")
    oneoff = reminders.schedule_summary(
        {"name": "Evento", "frequency": "oneoff", "weekday": None,
         "day_of_month": None, "run_date": "2026-12-25", "hour": 18, "minute": 30},
        "America/Mexico_City")
    for s in (weekly, monthly, oneoff):
        assert isinstance(s, str) and s.strip()
    assert weekly != monthly != oneoff and weekly != oneoff


# ── _is_staff (D-02 / T-08-01a role gate) ─────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reminders_config(monkeypatch):
    monkeypatch.setattr(config, "REMINDERS_STAFF_ROLE_IDS", [STAFF_ROLE_ID], raising=False)


def test_is_staff_true_when_role_intersects():
    assert reminders._is_staff(_member([OTHER_ROLE_ID, STAFF_ROLE_ID])) is True


def test_is_staff_false_without_matching_role():
    assert reminders._is_staff(_member([OTHER_ROLE_ID])) is False


def test_is_staff_false_for_roleless_member():
    assert reminders._is_staff(_member([])) is False


# ══ 08-03 Task 1: Discord layer — cog shell + staff-gated crear + MensajeModal ══════
#
# These drive the app-command callback and the modal directly with SimpleNamespace /
# AsyncMock fakes + asyncio.run (repo idiom, no pytest-asyncio). The scheduler loop and
# db table are neutralized in the fixture so instantiating the cog has no side effects.

STAFF_UID = 5


def _user(role_ids, uid=STAFF_UID):
    """A guild member fake carrying roles + an id (crear reads interaction.user.id)."""
    return types.SimpleNamespace(
        roles=[types.SimpleNamespace(id=r) for r in role_ids],
        bot=False,
        id=uid,
    )


def _crear_interaction(user):
    return types.SimpleNamespace(
        user=user,
        response=types.SimpleNamespace(
            send_message=AsyncMock(),
            send_modal=AsyncMock(),
            is_done=lambda: False,
        ),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


def _choice(value):
    label = {"weekly": "Semanal", "monthly": "Mensual", "oneoff": "Una vez"}[value]
    return app_commands.Choice(name=label, value=value)


def _channel(cid=42):
    return types.SimpleNamespace(id=cid, mention=f"<#{cid}>")


def _role(mention="<@&123>"):
    return types.SimpleNamespace(mention=mention)


@pytest.fixture
def cog(monkeypatch):
    """A RemindersCog with the db table init + scheduler start neutralized."""
    monkeypatch.setattr(reminders.db, "init_reminders", lambda: None)
    monkeypatch.setattr(reminders.tasks.Loop, "start", lambda self, *a, **k: None)
    return reminders.RemindersCog(bot=types.SimpleNamespace())


async def _run_crear(cog, interaction, **kwargs):
    defaults = dict(nombre="Junta", frecuencia=_choice("weekly"), canal=_channel(),
                    hora="09:00", dia_semana=0, dia_mes=None, fecha=None,
                    mencion=None, emojis=None)
    defaults.update(kwargs)
    await reminders.RemindersCog.crear.callback(cog, interaction, **defaults)


# ── staff gate (D-02 / T-08-01) ────────────────────────────────────────────────────
def test_crear_non_staff_rejected_no_persist(cog):
    inter = _crear_interaction(_user([OTHER_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter))
    inter.response.send_message.assert_awaited_once()
    assert inter.response.send_message.await_args.args[0] == "Sin permisos."
    assert inter.response.send_message.await_args.kwargs.get("ephemeral") is True
    inter.response.send_modal.assert_not_awaited()          # nothing persisted / no modal


# ── required name (D-05) ────────────────────────────────────────────────────────────
def test_crear_blank_name_rejected_before_modal(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, nombre="   "))
    inter.response.send_modal.assert_not_awaited()
    msg = inter.response.send_message.await_args.args[0]
    assert msg.startswith("❌")


def test_crear_overlong_name_rejected_before_modal(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, nombre="x" * 81))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


# ── schedule validation (T-08-04) ──────────────────────────────────────────────────
def test_crear_weekly_missing_weekday_rejected(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, frecuencia=_choice("weekly"), dia_semana=None))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


def test_crear_weekly_invalid_weekday_rejected(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, frecuencia=_choice("weekly"), dia_semana=9))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


def test_crear_monthly_missing_day_rejected(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, frecuencia=_choice("monthly"),
                           dia_semana=None, dia_mes=None))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


def test_crear_malformed_time_rejected(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, hora="25:99"))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


def test_crear_oneoff_past_date_rejected(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, frecuencia=_choice("oneoff"),
                           dia_semana=None, fecha="2020-01-01"))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


def test_crear_oneoff_malformed_date_rejected(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, frecuencia=_choice("oneoff"),
                           dia_semana=None, fecha="nope"))
    inter.response.send_modal.assert_not_awaited()
    assert inter.response.send_message.await_args.args[0].startswith("❌")


# ── success path opens the modal as the FIRST response (no defer) ───────────────────
def test_crear_valid_weekly_opens_modal_with_params(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, frecuencia=_choice("weekly"), dia_semana=2,
                           hora="14:30", canal=_channel(77), mencion=_role("<@&99>")))
    inter.response.send_modal.assert_awaited_once()
    inter.response.send_message.assert_not_awaited()        # send_modal was the FIRST response
    modal = inter.response.send_modal.await_args.args[0]
    assert isinstance(modal, reminders.MensajeModal)
    p = modal.params
    assert p["frequency"] == "weekly" and p["weekday"] == 2
    assert (p["hour"], p["minute"]) == (14, 30)
    assert p["channel_id"] == 77
    assert p["mentions"] == "<@&99>"
    assert p["created_by"] == STAFF_UID


def test_crear_emojis_routed_through_parse_emojis(cog):
    inter = _crear_interaction(_user([STAFF_ROLE_ID]))
    asyncio.run(_run_crear(cog, inter, emojis="✅ ✅ ❌"))    # dupes collapse via parse_emojis
    modal = inter.response.send_modal.await_args.args[0]
    assert modal.params["reactions"] == "✅ ❌"


# ── MensajeModal.on_submit persists via db.add_reminder with a computed next_fire ────
def _modal_interaction():
    return types.SimpleNamespace(
        response=types.SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
        followup=types.SimpleNamespace(send=AsyncMock()),
    )


def test_modal_submit_persists_reminder(monkeypatch):
    add = MagicMock(return_value=1)
    monkeypatch.setattr(reminders.db, "add_reminder", add)
    params = {"name": "Junta", "frequency": "weekly", "hour": 9, "minute": 0,
              "channel_id": 42, "weekday": 0, "day_of_month": None, "run_date": None,
              "mentions": "<@&123>", "reactions": "✅ ❌", "created_by": STAFF_UID}
    inter = _modal_interaction()

    async def _run():
        modal = reminders.MensajeModal(params=params)
        modal.body._value = "  Recuerden la junta  "
        await modal.on_submit(inter)

    asyncio.run(_run())
    add.assert_called_once()
    kw = add.call_args.kwargs
    assert kw["name"] == "Junta"
    assert kw["frequency"] == "weekly"
    assert kw["message"] == "Recuerden la junta"           # stripped body
    assert kw["reactions"] == "✅ ❌"
    assert kw["channel_id"] == 42
    nf = datetime.fromisoformat(kw["next_fire_utc"])
    assert nf > datetime.now(timezone.utc) - timedelta(minutes=1)   # a future cursor
    inter.response.send_message.assert_awaited_once()      # ephemeral confirmation


def test_modal_submit_edit_branch_updates(monkeypatch):
    update = MagicMock()
    add = MagicMock()
    monkeypatch.setattr(reminders.db, "update_reminder", update)
    monkeypatch.setattr(reminders.db, "add_reminder", add)
    params = {"edit_id": 7, "name": "Junta", "frequency": "weekly", "hour": 9,
              "minute": 0, "channel_id": 42, "weekday": 0, "day_of_month": None,
              "run_date": None, "mentions": "", "reactions": "", "created_by": STAFF_UID}
    inter = _modal_interaction()

    async def _run():
        modal = reminders.MensajeModal(params=params)
        modal.body._value = "Nuevo cuerpo"
        await modal.on_submit(inter)

    asyncio.run(_run())
    update.assert_called_once()                            # edit path routes to update_reminder
    add.assert_not_called()


# ══ 08-03 Task 2: scheduler tick + delivery + catch-up + D-16 lifecycle ═════════════

NOW = datetime(2026, 7, 8, 15, 0, tzinfo=timezone.utc)


def _row(**over):
    base = dict(id=1, name="Junta", frequency="weekly", weekday=0, day_of_month=None,
                run_date=None, hour=9, minute=0, channel_id=42,
                message="Recuerden la junta", mentions="", reactions="",
                next_fire_utc=NOW.isoformat(), created_by=STAFF_UID, created_at="")
    base.update(over)
    return base


def _http_error(status=404, reason="nf"):
    return discord.HTTPException(types.SimpleNamespace(status=status, reason=reason), "boom")


def _sending_channel():
    """A channel whose ``send`` returns a message we can assert reactions on."""
    sent = types.SimpleNamespace(add_reaction=AsyncMock())
    channel = types.SimpleNamespace(send=AsyncMock(return_value=sent))
    return channel, sent


def _patch_db(monkeypatch, rows):
    setnf, delete = MagicMock(), MagicMock()
    monkeypatch.setattr(reminders.db, "due_reminders", lambda iso: list(rows))
    monkeypatch.setattr(reminders.db, "set_next_fire", setnf)
    monkeypatch.setattr(reminders.db, "delete_reminder", delete)
    return setnf, delete


# ── lifecycle: advance-after-send (recurring) vs auto-delete (one-off, D-16) ────────
def test_due_weekly_ontime_delivers_and_advances(cog, monkeypatch):
    setnf, delete = _patch_db(monkeypatch, [_row(frequency="weekly")])
    cog._deliver = AsyncMock()
    asyncio.run(cog._process_due(NOW))
    cog._deliver.assert_awaited_once()
    assert cog._deliver.await_args.kwargs.get("atrasado") is False
    setnf.assert_called_once()                             # recurring cursor advanced
    delete.assert_not_called()


def test_due_oneoff_delivers_once_then_deletes(cog, monkeypatch):
    setnf, delete = _patch_db(
        monkeypatch, [_row(frequency="oneoff", run_date="2026-07-08", weekday=None)])
    cog._deliver = AsyncMock()
    asyncio.run(cog._process_due(NOW))
    cog._deliver.assert_awaited_once()
    delete.assert_called_once_with(1)                      # D-16 auto-delete
    setnf.assert_not_called()                              # never advanced


def test_due_late_within_grace_marks_atrasado(cog, monkeypatch):
    _patch_db(monkeypatch, [_row(next_fire_utc=(NOW - timedelta(hours=2)).isoformat())])
    cog._deliver = AsyncMock()
    asyncio.run(cog._process_due(NOW))
    assert cog._deliver.await_args.kwargs.get("atrasado") is True   # 'late' → atrasado


def test_due_skip_beyond_grace_sends_nothing_but_advances(cog, monkeypatch):
    setnf, delete = _patch_db(
        monkeypatch, [_row(next_fire_utc=(NOW - timedelta(hours=7)).isoformat())])
    cog._deliver = AsyncMock()
    asyncio.run(cog._process_due(NOW))
    cog._deliver.assert_not_awaited()                      # skipped — nothing sent
    setnf.assert_called_once()                             # …but the cursor still advances


def test_due_skip_oneoff_beyond_grace_is_deleted(cog, monkeypatch):
    setnf, delete = _patch_db(monkeypatch, [_row(
        frequency="oneoff", run_date="2026-07-08", weekday=None,
        next_fire_utc=(NOW - timedelta(hours=7)).isoformat())])
    cog._deliver = AsyncMock()
    asyncio.run(cog._process_due(NOW))
    cog._deliver.assert_not_awaited()
    delete.assert_called_once_with(1)                      # a skipped one-off is expired


# ── per-reminder isolation (T-08-05 / Pitfall 1) ───────────────────────────────────
def test_one_bad_reminder_does_not_stop_others(cog, monkeypatch):
    _patch_db(monkeypatch, [_row(id=1), _row(id=2)])

    async def _deliver(r, atrasado):
        if r["id"] == 1:
            raise RuntimeError("boom")
    cog._deliver = AsyncMock(side_effect=_deliver)
    asyncio.run(cog._process_due(NOW))                     # must not raise
    assert cog._deliver.await_count == 2                   # reminder 2 still fired


# ── _deliver contract (D-10/D-11/D-14) ─────────────────────────────────────────────
def test_deliver_sends_content_embed_and_allowed_mentions(cog):
    channel, sent = _sending_channel()
    cog.bot.get_channel = lambda cid: channel
    asyncio.run(cog._deliver(_row(name="Junta", message="cuerpo", mentions="<@&123>"),
                             atrasado=False))
    kw = channel.send.await_args.kwargs
    assert kw["content"] == "<@&123>"
    embed = kw["embed"]
    assert embed.title == "Junta"
    assert embed.description == "cuerpo"
    assert embed.color.value == 0xC0192C
    am = kw["allowed_mentions"]
    assert am.everyone is False and am.roles is True and am.users is True


def test_deliver_content_none_when_no_mentions(cog):
    channel, sent = _sending_channel()
    cog.bot.get_channel = lambda cid: channel
    asyncio.run(cog._deliver(_row(mentions=""), atrasado=False))
    assert channel.send.await_args.kwargs["content"] is None


def test_deliver_late_prefixes_atrasado_in_description(cog):
    channel, sent = _sending_channel()
    cog.bot.get_channel = lambda cid: channel
    asyncio.run(cog._deliver(_row(message="cuerpo"), atrasado=True))
    assert channel.send.await_args.kwargs["embed"].description.startswith("⏰ **atrasado**")


def test_deliver_seeds_reactions_tolerating_a_bad_emoji(cog):
    calls = []

    async def _add(e):
        calls.append(e)
        if e == "❌":
            raise _http_error(400, "bad emoji")
    channel = types.SimpleNamespace(
        send=AsyncMock(return_value=types.SimpleNamespace(add_reaction=AsyncMock(side_effect=_add))))
    cog.bot.get_channel = lambda cid: channel
    asyncio.run(cog._deliver(_row(reactions="✅ ❌ 🎉"), atrasado=False))
    assert calls == ["✅", "❌", "🎉"]                      # bad emoji skipped, rest still seeded


def test_deliver_unresolvable_channel_logs_and_returns(cog):
    cog.bot.get_channel = lambda cid: None
    cog.bot.fetch_channel = AsyncMock(side_effect=_http_error())
    asyncio.run(cog._deliver(_row(), atrasado=False))      # must not raise, sends nothing


def test_unresolvable_channel_tick_continues_reminder_not_deleted(cog, monkeypatch):
    setnf, delete = _patch_db(monkeypatch, [_row(frequency="weekly")])
    cog.bot.get_channel = lambda cid: None
    cog.bot.fetch_channel = AsyncMock(side_effect=_http_error())
    asyncio.run(cog._process_due(NOW))                     # must not raise
    delete.assert_not_called()                             # recurring reminder never deleted
    setnf.assert_called_once()                             # advances past the missed occurrence


# ── scheduler lifecycle hooks ──────────────────────────────────────────────────────
def test_before_loop_waits_until_ready(cog):
    cog.bot.wait_until_ready = AsyncMock()
    asyncio.run(cog._before_scheduler())
    cog.bot.wait_until_ready.assert_awaited_once()
