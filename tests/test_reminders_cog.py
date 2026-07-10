"""Unit tests for the pure schedule-math + validators + staff gate of the reminders cog (08-02).

This suite proves the deterministic, high-risk core of the reminders scheduler BEFORE any
Discord wiring exists (the cog class / scheduler / modal arrive in 08-03/08-04). Every helper
under test is a pure module-level function with no Discord/DB dependency, so the tests are plain
``assert fn(...) == expected`` — matching the repo idiom (SimpleNamespace fakes, no pytest-asyncio).

Coverage: weekly/monthly/one-off next-fire, month-end clamp (incl. leap Feb), a DST-boundary
zone case, catch-up classification (ontime/late/skip), the input validators, the emoji cap, the
schedule summary, and the ``_is_staff`` role gate.
"""

import types
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

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
