"""EditorsCog — role-loss auto-unpublish + optional ``/mi-pagina`` (Fase 10, plan 10-09).

Closes EDIT-07's role-loss half (D-10). When a Nocturna editor loses the editor role, their
public profile page is auto-unpublished. Detection runs on TWO paths, both funnelled through the
same 10-05 ``github_publish.unpublish_editor`` transport (no new commit path is invented):

  * **PRIMARY — real time.** ``on_member_update(before, after)``: if the editor role was in
    ``before.roles`` and not in ``after.roles``, unpublish that editor immediately. This requires
    the ``members`` privileged gateway intent, confirmed ENABLED in the Developer Portal per 10-03
    (and enabled in code in ``bot.py`` alongside this cog).
  * **BACKSTOP — periodic sweep.** A ``@tasks.loop`` (hourly) reconciles the published
    ``editors.json`` entries against live guild membership and unpublishes only those whose
    ``discordId`` no longer holds the editor role. It exists so a role change missed while the bot
    was down (or an event the gateway never delivered) is still eventually healed.

HARD mass-removal guard (T-10-09-02): the sweep ENUMERATES every published editor's membership
FIRST and unpublishes NOTHING if any membership check raises a transient API/gateway error —
mirroring the Phase-9 JinxxyCog enumerate-before-remove abort (T-09-15). A transient outage can
never mass-unpublish the whole directory. A member who has genuinely LEFT the guild
(``discord.NotFound``) is a CONFIRMED loss, not a transient error, so they are unpublished.

D-05: every failure path is ``log`` only — nothing operational is ever posted to a channel. The
optional ``/mi-pagina`` command is the bot's one remaining editor-facing role (D-05): it DMs the
invoking editor their admin-app link. It is staff-gated on the editor role (T-10-09-04).
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import github_publish

log = logging.getLogger(__name__)

# Cadence of the backstop sweep. The real-time ``on_member_update`` path is what normally does the
# unpublishing; this only heals changes the gateway missed (downtime), so hourly is ample.
_SWEEP_HOURS = 1


# ── staff gate (D-15 / T-10-09-04) ───────────────────────────────────────────────────
def _is_staff(member) -> bool:
    """True iff ``member`` holds the editor role (``ROLE_MODERATOR_ID``, reused per D-15).

    The editor role is the same moderator/staff role that gates every other staff feature (D-15),
    so a page owner is by definition someone holding it. A bot or a role-less member is never an
    editor (the id is simply absent from their role set).
    """
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return config.ROLE_MODERATOR_ID in role_ids


def _has_role(member, role_id: int) -> bool:
    """True iff ``member`` currently holds ``role_id``."""
    return any(r.id == role_id for r in getattr(member, "roles", []))


class EditorsCog(commands.Cog):
    """Auto-unpublish editor pages on role loss (event + sweep) + the ``/mi-pagina`` DM command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sweep.start()                        # start the backstop tasks.loop cadence

    async def cog_unload(self):
        # Hot-reload safety — mirrors reminders/jinxxy cog_unload so a reload doesn't leave a
        # second sweep loop ticking.
        self._sweep.cancel()

    # ── shared unpublish (both paths funnel here) ──────────────────────────────────────
    async def _unpublish_one(self, discord_id) -> None:
        """Unpublish one editor by ``discordId`` via the 10-05 transport; errors go to logs (D-05).

        Idempotent: ``unpublish_editor`` no-ops (``committed: False``) on an unknown or
        already-unpublished editor, so a redundant call is harmless and never an empty commit. A
        ``GitHubPublishError`` is swallowed to logs — a transport hiccup must never escape the
        event handler or the sweep.
        """
        try:
            result = await github_publish.unpublish_editor(str(discord_id))
        except github_publish.GitHubPublishError:
            log.exception("editors: no pude despublicar al editor (id=%s)", discord_id)
            return
        if result.get("committed"):
            log.info("editors: página despublicada por pérdida de rol (id=%s, slug=%s)",
                     discord_id, result.get("slug"))

    # ── PRIMARY: real-time role-loss detection (D-10) ──────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Unpublish immediately when the editor role is removed from a member (D-10 PRIMARY).

        Fires only on the exact edge — the role was present in ``before`` and is absent in
        ``after``. Any other member update (nickname, other roles added/removed, still holding the
        editor role) is ignored. Requires the ``members`` intent (enabled per 10-03).
        """
        role_id = config.ROLE_MODERATOR_ID
        if _has_role(before, role_id) and not _has_role(after, role_id):
            await self._unpublish_one(after.id)

    # ── BACKSTOP: periodic reconcile sweep with the mass-removal guard ─────────────────
    async def _has_lost_role(self, guild, discord_id) -> bool:
        """True iff the editor no longer holds the editor role in ``guild``.

        Resolves the member from cache, falling back to a REST ``fetch_member`` on a cache miss.
        A ``discord.NotFound`` (the member left the guild entirely) propagates to the caller, which
        treats it as a CONFIRMED loss. Any other ``discord.HTTPException`` (a transient
        API/gateway error) also propagates — the caller aborts the whole sweep on it (never a mass
        removal on an outage).
        """
        member = guild.get_member(int(discord_id))
        if member is None:
            member = await guild.fetch_member(int(discord_id))   # raises NotFound if truly gone
        return not _has_role(member, config.ROLE_MODERATOR_ID)

    async def _process_role_losses(self) -> None:
        """The testable body of the sweep tick: reconcile published editors vs. live membership.

        ORDER IS THE GUARANTEE (T-10-09-02, mirrors JinxxyCog._run_sync's T-09-15 abort): every
        published editor's membership is checked and the confirmed losers ENUMERATED before a
        single unpublish runs. If any membership check raises a transient ``HTTPException`` the
        whole sweep aborts with ZERO unpublishes — a transient outage can never mass-unpublish the
        directory. Only entries that are currently ``published`` are candidates (idempotency: an
        already-unpublished page/draft is never re-considered, D-13/D-16).
        """
        editors = await asyncio.to_thread(
            github_publish._fetch_json,
            config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_EDITORS_JSON)
        candidates = [e for e in editors
                      if e.get("published") is True and e.get("discordId") is not None]
        if not candidates:
            return

        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            # Can't verify membership without the guild → abort with zero unpublishes (never guess
            # a role loss). A cold/unresolved guild is treated exactly like a transient error.
            log.warning("editors: guild %s no resuelto — omito el sweep (cero bajas)",
                        config.GUILD_ID)
            return

        # Enumerate FIRST. A transient membership-check error aborts the ENTIRE sweep before any
        # unpublish; a NotFound (left the guild) is a confirmed loss; a malformed id is skipped.
        losers: list = []
        for e in candidates:
            discord_id = e["discordId"]
            try:
                lost = await self._has_lost_role(guild, discord_id)
            except discord.NotFound:
                lost = True                        # left the guild → confirmed role loss
            except discord.HTTPException:
                log.exception(
                    "editors: fallo al verificar membresía (id=%s) — abortando el sweep sin "
                    "bajas (guarda anti-remoción masiva)", discord_id)
                return                             # ABORT: zero unpublishes on a transient error
            except (ValueError, TypeError):
                log.warning("editors: discordId inválido %r — omitido en el sweep", discord_id)
                continue
            if lost:
                losers.append(discord_id)

        # Only after a fully successful enumeration do we unpublish the confirmed losers.
        for discord_id in losers:
            await self._unpublish_one(discord_id)

    @tasks.loop(hours=_SWEEP_HOURS)
    async def _sweep(self):
        await self._process_role_losses()

    @_sweep.before_loop
    async def _before_sweep(self):
        # Wait until the gateway is ready so ``get_guild`` resolves from cache (reminders idiom).
        await self.bot.wait_until_ready()

    @_sweep.error
    async def _on_sweep_error(self, exc: Exception):
        # A non-reconnect exception escaping the loop would otherwise kill it silently; log it
        # (D-05, never to a channel) and restart the loop so the next cadence runs.
        log.exception("editors: el sweep de roles se cayó, reiniciando", exc_info=exc)
        self._sweep.restart()

    # ── optional /mi-pagina — DM the editor their admin-app link (D-05) ────────────────
    @app_commands.command(
        name="mi-pagina",
        description="Te envío por DM el enlace a tu panel de edición de perfil (editores)")
    async def mi_pagina(self, interaction: discord.Interaction):
        """DM the invoking editor their admin-app link — the bot's one remaining role (D-05).

        Staff-gated on the editor role FIRST (T-10-09-04): a non-editor gets "Sin permisos." and no
        DM. On success the admin-app link (``EDITOR_APP_BASE_URL``) is DM'd and the invoker gets an
        ephemeral confirmation. If the editor has DMs closed (``discord.Forbidden``, a subclass of
        ``HTTPException``) the command falls back to telling them so — ephemerally, never leaking
        the link to a channel. Copy is Spanish-first (staff-facing).
        """
        # 1. Staff gate FIRST — only an editor may fetch their own admin link.
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # 2. DM the admin-app link (never posted to a channel).
        link = config.EDITOR_APP_BASE_URL
        try:
            await interaction.user.send(
                "👋 ¡Hola! Aquí tienes el enlace a tu panel de edición de perfil de Nocturna:\n"
                f"{link}\n\n"
                "Inicia sesión con Discord para editar y publicar tu página.")
        except discord.HTTPException:
            # Almost always discord.Forbidden (the editor has DMs closed). Tell them how to fix it
            # without ever printing the link publicly.
            await interaction.response.send_message(
                "No pude enviarte un DM — abre tus mensajes directos del servidor e inténtalo de "
                "nuevo.", ephemeral=True)
            return

        await interaction.response.send_message(
            "📬 Te envié por DM el enlace a tu panel de edición.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EditorsCog(bot))
