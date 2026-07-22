"""Bot-side Discord channel and role name cache for the admin app."""

import asyncio
import logging

import discord
from discord.ext import commands, tasks

import config
from core import db

log = logging.getLogger(__name__)


def _map_channel_kind(channel_type: discord.ChannelType) -> str:
    """Map Discord channel types to the display cues used by the settings UI."""
    return {
        discord.ChannelType.text: "text",
        discord.ChannelType.forum: "forum",
        discord.ChannelType.voice: "voice",
        discord.ChannelType.news: "text",
        discord.ChannelType.stage_voice: "voice",
    }.get(channel_type, "other")


def _role_hex(colour: discord.Colour) -> str | None:
    """Return a role's custom colour as lowercase hex, or None when unset."""
    return f"#{colour.value:06x}" if colour.value else None


def _snapshot_rows(guild: discord.Guild) -> list[tuple]:
    """Build database rows from a guild's in-memory channel and role caches."""
    rows = [
        (channel.id, "channel", channel.name, _map_channel_kind(channel.type), None)
        for channel in guild.channels
    ]
    rows.extend(
        (role.id, "role", role.name, None, _role_hex(role.colour))
        for role in guild.roles
        if not role.is_default()
    )
    return rows


class DiscordNamesCog(commands.Cog):
    """Periodically writes the guild's cached channel and role names to sqlite."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_discord_names()
        self._push.start()

    async def cog_unload(self):
        self._push.cancel()

    @tasks.loop(minutes=5)
    async def _push(self):
        guild = self.bot.get_guild(config.GUILD_ID)
        if guild is None:
            return

        rows = _snapshot_rows(guild)
        try:
            await asyncio.to_thread(db.replace_discord_names, rows)
        except Exception:
            log.exception("discord_names: no pude escribir la caché de nombres")

    @_push.before_loop
    async def _before_push(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(DiscordNamesCog(bot))
