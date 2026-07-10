"""Pure building blocks of the reminders cog (Fase 8, plan 08-02).

This module holds ONLY the deterministic, import-safe core of the ``/recordatorio`` scheduler:
the schedule math (next-fire computation, month-end clamp, DST-correct timezone conversion,
catch-up classification), the input validators, the Spanish schedule-summary formatter, and the
staff-role gate. There is deliberately **no** ``RemindersCog`` class, no ``discord.ui.Modal``,
no ``@tasks.loop`` scheduler and no ``async def setup(bot)`` yet — those wire around these
functions in 08-03/08-04. Importing this module has no Discord/DB side effects.

Design note (D-16 / Pitfall 2): a one-off reminder is fired once and then deleted by the
scheduler, so ``compute_next`` never recomputes it — it returns the stored instant unchanged.
Recurring reminders always recompute from the (year, month) + a clamped day (never a +30-day
drift) and build local wall times via ``zoneinfo.ZoneInfo`` (never fixed offsets), so DST zones
stay correct (Pitfall 3).
"""

import calendar
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import db

log = logging.getLogger(__name__)

# Brand red for the reminder embed (matches the reviews/gallery embeds).
_BRAND_RED = 0xC0192C
_NAME_MAX = 80

# Spanish weekday labels (0 = Monday .. 6 = Sunday, matching datetime.weekday()).
_WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ── schedule math ─────────────────────────────────────────────────────────────────
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


# ── validators (T-08-04) ───────────────────────────────────────────────────────────
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


# ── presentation ────────────────────────────────────────────────────────────────────
def schedule_summary(row, tz: str | None = None) -> str:
    """A short Spanish one-line schedule summary (autocomplete label + ``listar`` line)."""
    freq = row["frequency"]
    hhmm = f"{int(row['hour']):02d}:{int(row['minute']):02d}"
    if freq == "weekly":
        return f"Semanal · {_WEEKDAYS_ES[int(row['weekday']) % 7]} {hhmm}"
    if freq == "monthly":
        return f"Mensual · día {row['day_of_month']} {hhmm}"
    if freq == "oneoff":
        return f"Una vez · {row['run_date']} {hhmm}"
    return f"{freq} {hhmm}"


# ── staff gate (D-02 / T-08-01a) ─────────────────────────────────────────────────────
def _is_staff(member) -> bool:
    """True iff ``member`` holds a configured reminders-staff role (trust boundary).

    Reminders reuse the gallery staff roles by default (``REMINDERS_STAFF_ROLE_IDS`` falls back
    to ``GALLERY_STAFF_ROLE_IDS`` when unset in ``config``). A bot or a role-less member is never
    staff (an empty role intersection is falsy).
    """
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(role_ids & set(config.REMINDERS_STAFF_ROLE_IDS))


# ══ Discord layer (08-03) ═══════════════════════════════════════════════════════════
# Everything above is pure/import-safe (08-02). Below is the Discord wiring: the
# multi-line message modal, the ``/recordatorio`` GroupCog with the staff-gated ``crear``
# subcommand, the delivery helper, and the 1-minute background scheduler.


def _next_fire_for(params: dict, now_utc: datetime) -> datetime:
    """Compute the first ``next_fire_utc`` for a freshly-created reminder (dispatch by freq)."""
    freq = params["frequency"]
    tz = config.REMINDERS_TZ
    if freq == "weekly":
        return next_weekly_fire(now_utc, params["weekday"], params["hour"],
                                params["minute"], tz)
    if freq == "monthly":
        return next_monthly_fire(now_utc, params["day_of_month"], params["hour"],
                                 params["minute"], tz)
    if freq == "oneoff":
        return next_oneoff_fire(params["run_date"], params["hour"], params["minute"], tz)
    raise ValueError(f"frecuencia desconocida: {freq!r}")


class MensajeModal(discord.ui.Modal):
    """Multi-line message capture for ``crear`` (and, via ``edit_id``, ``editar`` in 08-04).

    ``crear`` validates every structured param first, then opens this modal as its FIRST
    interaction response (RESEARCH Pattern 2 — no ``defer()`` before ``send_modal``). The
    already-collected params ride in ``params``; ``on_submit`` strips the body and either
    UPDATEs (edit path) or INSERTs a new reminder with a freshly-computed ``next_fire_utc``.
    """

    def __init__(self, *, params: dict, default_body: str = "",
                 title: str = "Mensaje del recordatorio"):
        super().__init__(title=title)
        self.params = params
        self.body = discord.ui.TextInput(
            label="Mensaje",
            style=discord.TextStyle.paragraph,     # multi-line free text
            max_length=4000,                       # Discord TextInput hard cap
            required=True,
            default=default_body,                  # pre-fill for editar (D-15)
        )
        self.add_item(self.body)

    async def on_submit(self, interaction: discord.Interaction):
        body = str(self.body.value).strip()
        params = self.params
        name = params.get("name", "")

        if params.get("edit_id"):
            # 08-04 edit path: change only the message body here; schedule edits land in 08-04.
            db.update_reminder(params["edit_id"], message=body)
            await self._reply(interaction, f"✅ Recordatorio actualizado: **{name}**")
            return

        next_fire = _next_fire_for(params, datetime.now(timezone.utc))
        db.add_reminder(
            name=name,
            frequency=params["frequency"],
            hour=params["hour"],
            minute=params["minute"],
            channel_id=params["channel_id"],
            message=body,
            created_by=params["created_by"],
            weekday=params.get("weekday"),
            day_of_month=params.get("day_of_month"),
            run_date=params.get("run_date"),
            mentions=params.get("mentions", ""),
            reactions=params.get("reactions", ""),
            next_fire_utc=next_fire.isoformat(),
        )
        summary = schedule_summary({
            "frequency": params["frequency"], "weekday": params.get("weekday"),
            "day_of_month": params.get("day_of_month"), "run_date": params.get("run_date"),
            "hour": params["hour"], "minute": params["minute"],
        })
        await self._reply(interaction, f"✅ Recordatorio creado: **{name}** — {summary}")

    @staticmethod
    async def _reply(interaction: discord.Interaction, content: str):
        """Ephemeral confirmation, tolerant of an already-consumed interaction response."""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
        except Exception:
            log.exception("reminders: could not send modal confirmation")


class RemindersCog(
    commands.GroupCog,
    name="Reminders",
    group_name="recordatorio",
    group_description="Recordatorios programados (juntas y más)",
):
    """The ``/recordatorio`` command group + the 1-minute background scheduler.

    ``crear`` (this plan) is staff-gated, validates its schedule params, then opens
    ``MensajeModal`` for the body. ``listar``/``borrar``/``editar`` land in 08-04. The
    scheduler loop (fills in 08-03 Task 2) polls ``db.due_reminders`` every minute.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_reminders()                        # repo idiom: ensure the table exists
        self._scheduler.start()                    # start the tasks.loop cadence

    async def cog_unload(self):
        # Reload safety — mirrors encoding.cog_unload cleanup so a hot reload doesn't leave
        # a second scheduler ticking.
        self._scheduler.cancel()

    # ── /recordatorio crear ──────────────────────────────────────────────────────────
    @app_commands.command(name="crear",
                          description="Crea un recordatorio programado (staff)")
    @app_commands.describe(
        nombre="Nombre corto del recordatorio (p. ej. 'Junta semanal')",
        frecuencia="Cada cuánto se repite",
        canal="Canal donde se enviará el recordatorio",
        hora="Hora en formato 24h HH:MM (zona del equipo)",
        dia_semana="Solo semanal: 0=lunes, 1=martes, 2=miércoles, 3=jueves, 4=viernes, "
                   "5=sábado, 6=domingo",
        dia_mes="Solo mensual: día del mes 1-31 (se ajusta al último día en meses cortos)",
        fecha="Solo una vez: fecha en formato YYYY-MM-DD",
        mencion="Rol opcional a mencionar (se ping-ea en una línea sobre el mensaje)",
        emojis="Reacciones opcionales a sembrar, separadas por espacio (p. ej. '✅ ❌')",
    )
    @app_commands.choices(frecuencia=[
        app_commands.Choice(name="Semanal", value="weekly"),
        app_commands.Choice(name="Mensual", value="monthly"),
        app_commands.Choice(name="Una vez", value="oneoff"),
    ])
    async def crear(self, interaction: discord.Interaction, nombre: str,
                    frecuencia: app_commands.Choice[str], canal: discord.TextChannel,
                    hora: str, dia_semana: int | None = None, dia_mes: int | None = None,
                    fecha: str | None = None, mencion: discord.Role | None = None,
                    emojis: str | None = None):
        # 1. Staff gate FIRST (D-02, T-08-01) — nothing else runs for a non-staff member.
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # 2. Required name (D-05): non-blank after strip, capped length.
        name = (nombre or "").strip()
        if not name:
            await interaction.response.send_message(
                "❌ El nombre es obligatorio.", ephemeral=True)
            return
        if len(name) > _NAME_MAX:
            await interaction.response.send_message(
                f"❌ El nombre es demasiado largo (máx. {_NAME_MAX} caracteres).",
                ephemeral=True)
            return

        # 3. Time (T-08-04): HH:MM 24h.
        try:
            hour, minute = parse_time(hora)
        except ValueError:
            await interaction.response.send_message(
                "❌ Hora inválida. Usa el formato 24h HH:MM (p. ej. 09:30).", ephemeral=True)
            return

        # 4. Frequency-specific schedule field (exactly one applies).
        freq = frecuencia.value
        weekday = day_of_month = run_date = None
        if freq == "weekly":
            if dia_semana is None or not valid_weekday(dia_semana):
                await interaction.response.send_message(
                    "❌ Para un recordatorio semanal indica `dia_semana` (0=lunes .. 6=domingo).",
                    ephemeral=True)
                return
            weekday = dia_semana
        elif freq == "monthly":
            if dia_mes is None or not valid_day_of_month(dia_mes):
                await interaction.response.send_message(
                    "❌ Para un recordatorio mensual indica `dia_mes` (1-31).", ephemeral=True)
                return
            day_of_month = dia_mes
        elif freq == "oneoff":
            if fecha is None:
                await interaction.response.send_message(
                    "❌ Para un recordatorio de una vez indica `fecha` (YYYY-MM-DD).",
                    ephemeral=True)
                return
            try:
                parse_date(fecha)
            except ValueError:
                await interaction.response.send_message(
                    "❌ Fecha inválida. Usa el formato YYYY-MM-DD (p. ej. 2026-12-25).",
                    ephemeral=True)
                return
            # Reject a date+time already in the past for the team timezone.
            if next_oneoff_fire(fecha, hour, minute) <= datetime.now(timezone.utc):
                await interaction.response.send_message(
                    "❌ Esa fecha y hora ya pasaron.", ephemeral=True)
                return
            run_date = fecha

        # 5. Optional mention (typed Role → its .mention string) + seeded emojis.
        mentions = mencion.mention if mencion is not None else ""
        reactions = " ".join(parse_emojis(emojis)) if emojis else ""

        # 6. Open the modal as the FIRST response (RESEARCH Pattern 2 — never defer first).
        params = {
            "name": name, "frequency": freq, "hour": hour, "minute": minute,
            "channel_id": canal.id, "weekday": weekday, "day_of_month": day_of_month,
            "run_date": run_date, "mentions": mentions, "reactions": reactions,
            "created_by": interaction.user.id,
        }
        await interaction.response.send_modal(MensajeModal(params=params))

    # ── shared autocomplete backing (RESEARCH Pattern 3, D-04/D-05) ────────────────────
    @staticmethod
    def _reminder_choices(current: str) -> list[app_commands.Choice[str]]:
        """Live ``db.list_reminders`` → labelled Choices, case-insensitive name filter, ≤25.

        Both ``borrar`` and ``editar`` autocomplete callbacks delegate here so staff pick a
        reminder by its readable ``"{name} — {schedule summary}"`` label (D-04/D-05) instead of
        memorizing ids. ``Choice.value`` carries the id as a string; the label is truncated to
        Discord's 100-char cap and the whole list to the 25-choice cap.
        """
        current_l = (current or "").lower()
        out: list[app_commands.Choice[str]] = []
        for r in db.list_reminders():
            if current_l in r["name"].lower():
                label = f"{r['name']} — {schedule_summary(r, config.REMINDERS_TZ)}"[:100]
                out.append(app_commands.Choice(name=label, value=str(r["id"])))
            if len(out) >= 25:                     # Discord hard cap: max 25 choices
                break
        return out

    # ── /recordatorio listar (D-01/D-05) ──────────────────────────────────────────────
    @app_commands.command(name="listar",
                          description="Lista los recordatorios programados (staff)")
    async def listar(self, interaction: discord.Interaction):
        # Staff gate FIRST (D-02, T-08-01) — no store read for a non-staff member.
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        rows = db.list_reminders()
        if not rows:
            await interaction.response.send_message(
                "No hay recordatorios programados.", ephemeral=True)
            return

        # One readable line per reminder: **name** — schedule summary → #channel.
        lines = [
            f"**{r['name']}** — {schedule_summary(r, config.REMINDERS_TZ)} → <#{r['channel_id']}>"
            for r in rows
        ]
        embed = discord.Embed(title="Recordatorios programados",
                              description="\n".join(lines), color=_BRAND_RED)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /recordatorio borrar (D-01/D-04, T-08-10) ─────────────────────────────────────
    @app_commands.command(name="borrar",
                          description="Borra un recordatorio (staff)")
    @app_commands.describe(recordatorio="Elige el recordatorio")
    async def borrar(self, interaction: discord.Interaction, recordatorio: str):
        # Staff gate FIRST (D-02, T-08-01).
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # The autocomplete VALUE is attacker-choosable free text (T-08-10): parse defensively
        # and confirm existence before deleting; both malformed and unknown → same ❌ ephemeral.
        row = None
        try:
            row = db.get_reminder(int(recordatorio))
        except (TypeError, ValueError):
            row = None
        if row is None:
            await interaction.response.send_message(
                "❌ No encontré ese recordatorio.", ephemeral=True)
            return

        db.delete_reminder(int(recordatorio))
        await interaction.response.send_message(
            f"🗑️ Recordatorio **{row['name']}** borrado.", ephemeral=True)

    @borrar.autocomplete("recordatorio")
    async def borrar_autocomplete(self, interaction: discord.Interaction,
                                  current: str) -> list[app_commands.Choice[str]]:
        return self._reminder_choices(current)

    # ── delivery (D-10/D-11/D-14) ────────────────────────────────────────────────────
    async def _deliver(self, r, atrasado: bool):
        """Send one reminder: mention line + branded embed, @everyone suppressed, seeded reactions.

        Resolves the target channel with the ``get_channel`` → ``fetch_channel`` fallback (the
        encoding idiom); an unresolvable channel logs a Spanish warning and returns WITHOUT
        raising, so the tick keeps going and the reminder's lifecycle still advances.
        """
        channel = self.bot.get_channel(r["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(r["channel_id"])
            except discord.HTTPException:
                channel = None
        if channel is None:
            log.warning(
                "reminders: canal %s no encontrado para el recordatorio '%s' (id=%s) — "
                "¿el bot está en ese servidor y puede ver el canal?",
                r["channel_id"], r["name"], r["id"])
            return

        description = r["message"]
        if atrasado:
            description = "⏰ **atrasado**\n\n" + description
        embed = discord.Embed(title=r["name"], description=description, color=_BRAND_RED)
        embed.timestamp = discord.utils.utcnow()
        embed.set_footer(text="Nocturna · recordatorio")

        # Mentions go on the plain content line (mentions inside an embed never ping, D-10);
        # AllowedMentions is the hard API-level @everyone/@here suppression (D-11) regardless
        # of what the staff-authored text contains.
        content = r["mentions"] or None
        allowed = discord.AllowedMentions(everyone=False, roles=True, users=True)
        sent = await channel.send(content=content, embed=embed, allowed_mentions=allowed)

        # D-14 seed-only: add each reaction, skipping (and logging) a bad emoji rather than
        # letting one invalid token abort the rest.
        for e in parse_emojis(r["reactions"] or ""):
            try:
                await sent.add_reaction(e)
            except discord.HTTPException:
                log.warning("reminders: emoji de reacción inválido %r omitido (id=%s)",
                            e, r["id"])

    # ── background scheduler ─────────────────────────────────────────────────────────
    async def _process_due(self, now: datetime):
        """Fire every due reminder for ``now`` (the testable body of the 1-minute tick).

        LOCKED crash-semantics (RESEARCH Open Q1 / A3): the send happens BEFORE the cursor
        advances (advance-after-send). A crash between the two causes a rare missed advance
        (healed by the next tick's recompute) rather than a double ping; the D-13 grace window
        covers recent misses. Each reminder is wrapped in its own try/except so one bad row
        (deleted channel, bad role, unexpected error) can never sink the rest of the batch
        (Pitfall 1 / T-08-05).
        """
        for r in db.due_reminders(now.isoformat()):
            try:
                cls = classify_fire(now, datetime.fromisoformat(r["next_fire_utc"]),
                                    config.REMINDERS_CATCHUP_GRACE_HOURS)
                if cls != "skip":
                    await self._deliver(r, atrasado=(cls == "late"))
                # Lifecycle AFTER the send (advance-after-send). A one-off is expired the
                # moment it comes due — even a 'skip' one-off is deleted (D-16); a recurring
                # reminder advances its cursor to the next occurrence.
                if r["frequency"] == "oneoff":
                    db.delete_reminder(r["id"])
                else:
                    db.set_next_fire(r["id"], compute_next(r, now).isoformat())
            except Exception:
                log.exception(
                    "reminders: fallo al disparar id=%s (los demás continúan)", r["id"])

    @tasks.loop(minutes=1)
    async def _scheduler(self):
        await self._process_due(datetime.now(timezone.utc))

    @_scheduler.before_loop
    async def _before_scheduler(self):
        # Wait until the gateway is ready so channels resolve. Catch-up needs no separate
        # backfill: rows that came due during downtime are already <= now, so the first tick
        # picks them up and classify_fire decides atrasado vs skip (D-13).
        await self.bot.wait_until_ready()

    @_scheduler.error
    async def _on_scheduler_error(self, exc: Exception):
        # A non-reconnect exception escaping the loop would otherwise kill it silently
        # (Pitfall 1); log it and restart the loop.
        log.exception("reminders: el scheduler se cayó, reiniciando", exc_info=exc)
        self._scheduler.restart()


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindersCog(bot))
