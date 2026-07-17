"""PresenceCog — native live Discord status for editor pages.

The editor pages show a Discord-style status dot on the avatar. Instead of the
public Lanyard API (which requires each editor to join an external server), the
Nocturna bot — already in the guild with the ``GUILD_PRESENCES`` intent — reads
each editor's status straight from the gateway and writes it to the shared
sqlite DB. The editor app (a separate process, same DB file) serves it read-only
at ``/api/presence/<id>``, which the public page polls.

Only members holding the editor role (``ROLE_MODERATOR_ID``, the same staff
boundary used everywhere per D-15) are ever stored — this is not a general
presence lookup for arbitrary users. Every failure is ``log`` only (D-05).
"""

import asyncio
import logging

import discord
from discord.ext import commands

import config
from core import db

log = logging.getLogger(__name__)


def _is_editor(member: discord.Member) -> bool:
    """True iff ``member`` holds the editor role (same gate as EditorsCog)."""
    return any(r.id == config.ROLE_MODERATOR_ID for r in getattr(member, "roles", []))


class PresenceCog(commands.Cog):
    """Mirror editor members' live Discord status into the DB for the editor app."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_presence()

    async def _store(self, member: discord.Member) -> None:
        # discord.Status → 'online' | 'idle' | 'dnd' | 'offline' (str of the enum).
        status = str(getattr(member, "status", "offline"))
        try:
            await asyncio.to_thread(db.set_presence, member.id, status)
        except Exception:
            log.exception("presence: no pude guardar el estado (id=%s)", getattr(member, "id", "?"))

    @commands.Cog.listener()
    async def on_ready(self):
        """Snapshot every editor's current status once the gateway is ready."""
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            log.warning("presence: guild %s no resuelto — omito el snapshot inicial", config.GUILD_ID)
            return
        stored = 0
        for member in guild.members:
            if _is_editor(member):
                await self._store(member)
                stored += 1
        log.info("presence: snapshot inicial de %d editor(es)", stored)

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """Persist a status change for any member currently holding the editor role."""
        if _is_editor(after):
            await self._store(after)


async def setup(bot: commands.Bot):
    await bot.add_cog(PresenceCog(bot))
