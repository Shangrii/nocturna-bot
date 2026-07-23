"""Framework-agnostic schedule math and validators for reminders."""

import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

log = logging.getLogger(__name__)

# Spanish weekday labels (0 = Monday .. 6 = Sunday, matching datetime.weekday()).
_WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ── schedule math ──────────────────────────────────────────────────────────────
def _clamp_day(year: int, month: int, day: int) -> int:
    """D-08: clamp ``day`` to the last valid day of ``month`` (leap-aware via monthrange).

    So a day-31 monthly reminder fires Feb 28 (or Feb 29 in a leap year), Apr 30, etc. —
    it never silently skips a short month.
    """
    return min(day, calendar.monthrange(year, month)[1])


def next_weekly_fire(now_utc: datetime, weekday: int, hour: int, minute: int,
                     tz: str | None = None) -> datetime:
    """Next occurrence of ``weekday`` (0=Mon..6=Sun) at HH:MM in ``tz``, returned as UTC.

    If the target weekday+time is still ahead today it fires today; if it has already passed
    (or is earlier today) it rolls to the same weekday next week.
    """
    zone = ZoneInfo(tz or config.REMINDERS_TZ)
    local_now = now_utc.astimezone(zone)
    days_ahead = (weekday - local_now.weekday()) % 7
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0) \
        + timedelta(days=days_ahead)
    if candidate <= local_now:
        candidate += timedelta(days=7)
    return candidate.astimezone(timezone.utc)


def next_monthly_fire(now_utc: datetime, day: int, hour: int, minute: int,
                      tz: str | None = None) -> datetime:
    """Next occurrence of day-of-month ``day`` at HH:MM in ``tz``, as UTC (month-end clamped).

    Always recomputed from (year, month) + ``_clamp_day`` — never advanced by a fixed 30/31
    days — so month-ends and leap years stay correct (D-08).
    """
    zone = ZoneInfo(tz or config.REMINDERS_TZ)
    local_now = now_utc.astimezone(zone)
    y, m = local_now.year, local_now.month
    candidate = local_now.replace(day=_clamp_day(y, m, day), hour=hour,
                                  minute=minute, second=0, microsecond=0)
    if candidate <= local_now:                              # this month already passed → next
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        candidate = candidate.replace(year=y, month=m, day=_clamp_day(y, m, day))
    return candidate.astimezone(timezone.utc)


def next_oneoff_fire(run_date: str, hour: int, minute: int,
                     tz: str | None = None) -> datetime:
    """Convert a one-off ``'YYYY-MM-DD'`` + HH:MM local time in ``tz`` to a UTC instant."""
    zone = ZoneInfo(tz or config.REMINDERS_TZ)
    d = parse_date(run_date)
    local = datetime(d.year, d.month, d.day, int(hour), int(minute), tzinfo=zone)
    return local.astimezone(timezone.utc)


def next_biweekly_fire(now_utc: datetime, anchor_date: str, hour: int, minute: int,
                       tz: str | None = None) -> datetime:
    """Next occurrence of a 14-day cadence anchored on ``anchor_date`` (D-06).

    A PAST anchor_date is valid (only parity/cadence matters) — unlike a one-off's run_date,
    which is rejected in the past. Computes anchor + 14*n for the smallest n giving an
    instant >= now, via whole-day arithmetic in the LOCAL zone (never a fixed-offset UTC
    delta) so DST transitions inside the 14-day window stay correct (matches next_weekly_fire/
    next_monthly_fire's existing zoneinfo discipline).
    """
    zone = ZoneInfo(tz or config.REMINDERS_TZ)
    anchor = parse_date(anchor_date)
    anchor_local = datetime(anchor.year, anchor.month, anchor.day, hour, minute, tzinfo=zone)
    local_now = now_utc.astimezone(zone)
    days_since_anchor = (local_now.date() - anchor_local.date()).days
    periods = max(0, -(-days_since_anchor // 14))  # ceil division, never negative
    candidate = anchor_local + timedelta(days=14 * periods)
    if candidate <= local_now:
        candidate += timedelta(days=14)
    return candidate.astimezone(timezone.utc)


def compute_next(row, now_utc: datetime) -> datetime:
    """Dispatch on ``row['frequency']`` to the right next-fire (recurring reminders only).

    'oneoff' is fired once then deleted by the scheduler (D-16), so it is never recomputed —
    the stored ``next_fire_utc`` is returned unchanged for callers that ask defensively.
    """
    freq = row["frequency"]
    tz = config.REMINDERS_TZ
    if freq == "weekly":
        return next_weekly_fire(now_utc, row["weekday"], row["hour"], row["minute"], tz)
    if freq == "monthly":
        return next_monthly_fire(now_utc, row["day_of_month"], row["hour"], row["minute"], tz)
    if freq == "oneoff":
        return datetime.fromisoformat(row["next_fire_utc"])
    raise ValueError(f"frecuencia desconocida: {freq!r}")


def classify_fire(now_utc: datetime, next_fire_utc: datetime, grace_hours: int,
                  jitter_min: int = 5) -> str:
    """'ontime' | 'late' (⏰ atrasado) | 'skip' (too old) against the catch-up window (D-13).

    Within a small jitter of the scheduled instant → on time; overdue but inside the grace
    window → send marked late; overdue beyond grace → skip (advance the cursor, send nothing).
    """
    lateness = now_utc - next_fire_utc
    if lateness < timedelta(minutes=jitter_min):
        return "ontime"
    if lateness <= timedelta(hours=grace_hours):
        return "late"
    return "skip"


def is_imminent(next_fire_utc: datetime, now_utc: datetime,
                threshold_seconds: int = 90) -> bool:
    """True iff ``next_fire_utc`` is within ``threshold_seconds`` of ``now_utc`` (past or
    future) — the D-15/D-16 "may already be mid-send" caveat trigger. Default 90s = 1.5x the
    60s scheduler tick (UI-SPEC's recommended default), covering the case where the row is
    already slightly overdue (scheduler claimed it, hasn't written back yet) as well as the
    case where it's about to become due.
    """
    return abs((next_fire_utc - now_utc).total_seconds()) <= threshold_seconds


# ── validators (T-08-04) ───────────────────────────────────────────────────────
def parse_time(s: str) -> tuple[int, int]:
    """Parse a 24h ``'HH:MM'`` string to ``(hour, minute)``; raise ValueError on malformed input.

    Documented rule: exactly two ``:``-separated integer fields (1- or 2-digit each), with
    ``0 <= hour <= 23`` and ``0 <= minute <= 59``. So ``'9:5'`` is accepted as ``(9, 5)`` but
    ``'24:00'``, ``'09:60'``, ``'9'``, ``'ab:cd'`` and ``'09:05:00'`` all raise.
    """
    parts = str(s).strip().split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        raise ValueError(f"hora inválida: {s!r} (usa HH:MM 24h)")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"hora fuera de rango: {s!r}")
    return hour, minute


def parse_date(s: str) -> date:
    """Parse a ``'YYYY-MM-DD'`` string to a ``date``; raise ValueError on malformed input."""
    return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


def valid_weekday(n: int) -> bool:
    """True iff ``n`` is a valid weekday index 0..6 (Mon..Sun)."""
    return isinstance(n, int) and 0 <= n <= 6


def valid_day_of_month(n: int) -> bool:
    """True iff ``n`` is a valid day-of-month 1..31 (month-end clamping happens at fire time)."""
    return isinstance(n, int) and 1 <= n <= 31


def parse_emojis(s: str, cap: int = 6) -> list[str]:
    """Split a space/comma list into a deduped, order-preserving, capped emoji list (T-08-07).

    The cap (default 6, well under Discord's 20 reactions/message) bounds how many reactions a
    single reminder can seed. Empty/whitespace input yields ``[]``.
    """
    if not s:
        return []
    out: list[str] = []
    for tok in str(s).replace(",", " ").split():
        if tok and tok not in out:
            out.append(tok)
        if len(out) >= cap:
            break
    return out


# ── presentation ───────────────────────────────────────────────────────────────
def schedule_summary(row, tz: str | None = None) -> str:
    """A short Spanish one-line schedule summary (autocomplete label + ``listar`` line)."""
    freq = row["frequency"]
    hhmm = f"{int(row['hour']):02d}:{int(row['minute']):02d}"
    if freq == "weekly":
        return f"Semanal · {_WEEKDAYS_ES[int(row['weekday']) % 7]} {hhmm}"
    if freq == "biweekly":
        weekday = datetime.fromisoformat(row["run_date"]).weekday()
        return f"Cada 2 semanas · {_WEEKDAYS_ES[weekday]} {hhmm}"
    if freq == "monthly":
        return f"Mensual · día {row['day_of_month']} {hhmm}"
    if freq == "oneoff":
        return f"Una vez · {row['run_date']} {hhmm}"
    return f"{freq} {hhmm}"
