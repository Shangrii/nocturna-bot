"""Unit tests for the framework-agnostic reminder schedule helpers."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
from core.reminder_schedule import is_imminent, next_biweekly_fire


def test_next_biweekly_fire_anchor_equals_now_rolls_forward(monkeypatch):
    monkeypatch.setattr(config, "REMINDERS_TZ", "America/New_York", raising=False)
    zone = ZoneInfo("America/New_York")
    now = datetime(2026, 3, 1, 9, 0, tzinfo=zone).astimezone(timezone.utc)

    result = next_biweekly_fire(now, "2026-03-01", 9, 0)

    result_local = result.astimezone(zone)
    assert result_local == datetime(2026, 3, 15, 9, 0, tzinfo=zone)


def test_next_biweekly_fire_past_anchor_is_valid(monkeypatch):
    monkeypatch.setattr(config, "REMINDERS_TZ", "America/Mexico_City", raising=False)
    zone = ZoneInfo("America/Mexico_City")
    now = datetime(2026, 7, 31, 10, 0, tzinfo=zone).astimezone(timezone.utc)
    anchor = datetime(2026, 7, 1, 9, 0, tzinfo=zone)

    result = next_biweekly_fire(now, "2026-07-01", 9, 0)

    result_local = result.astimezone(zone)
    assert result > now
    assert (result_local.date() - anchor.date()).days % 14 == 0


def test_next_biweekly_fire_across_dst_keeps_wall_time(monkeypatch):
    monkeypatch.setattr(config, "REMINDERS_TZ", "America/New_York", raising=False)
    zone = ZoneInfo("America/New_York")
    anchor_local = datetime(2026, 3, 2, 9, 0, tzinfo=zone)
    now = datetime(2026, 3, 2, 10, 0, tzinfo=zone).astimezone(timezone.utc)

    result = next_biweekly_fire(now, "2026-03-02", 9, 0)

    result_local = result.astimezone(zone)
    assert (result_local.hour, result_local.minute) == (9, 0)
    assert result_local.utcoffset() == timedelta(hours=-4)
    assert anchor_local.utcoffset() == timedelta(hours=-5)


def test_is_imminent_30_seconds_in_future():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    assert is_imminent(now + timedelta(seconds=30), now) is True


def test_is_imminent_30_seconds_in_past():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    assert is_imminent(now - timedelta(seconds=30), now) is True


def test_is_imminent_200_seconds_away():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    assert is_imminent(now + timedelta(seconds=200), now) is False


def test_is_imminent_90_second_boundary():
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    assert is_imminent(now + timedelta(seconds=90), now) is True
