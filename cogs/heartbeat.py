"""HeartbeatCog — bot liveness writer for the dashboard's Overview page (D-09, SHELL-02).

An always-loaded, minimal cog: every ~45s it writes a fresh row to the shared sqlite's
``bot_heartbeat`` table (gateway latency, uptime anchor, guild member count, loaded cogs).
The FastAPI admin app (a separate process, same DB file) reads this read-only to compute
"Online" iff the last beat is recent — no IPC/HTTP, the shared sqlite is the channel
(locked project decision). No heavy dependencies, so unlike ``cogs.meeting`` this is NOT
wrapped in the optional-deps try/except in ``bot.py`` — it must always load.
"""

import asyncio
import logging
from datetime import datetime, timezone

from discord.ext import commands, tasks

import config
from core import db

log = logging.getLogger(__name__)


class HeartbeatCog(commands.Cog):
    """Writes a ``bot_heartbeat`` row on a fixed cadence (Claude's Discretion, A2)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._started_at = datetime.now(timezone.utc).isoformat()
        db.init_heartbeat()                         # dual-process defensive init (Pitfall 6)
        self._beat.start()

    async def cog_unload(self):
        # Hot-reload safety — mirrors jinxxy/reminders cog_unload so a reload doesn't leave
        # a second beat loop ticking.
        self._beat.cancel()

    @tasks.loop(seconds=45)  # cadence is Claude's Discretion (A2); staleness threshold ~90s
    async def _beat(self):
        # A4: fall back to None gracefully if the guild/member cache isn't ready yet —
        # Overview shows "—" rather than crash the loop on a cold-start race.
        guild = self.bot.get_guild(config.GUILD_ID)
        member_count = guild.member_count if guild is not None else None
        try:
            await asyncio.to_thread(
                db.set_heartbeat,
                latency_ms=round(self.bot.latency * 1000, 1),
                started_at_utc=self._started_at,
                guild_member_count=member_count,
                loaded_cogs=list(self.bot.cogs.keys()),
            )
        except Exception:
            log.exception("heartbeat: no pude escribir el latido")

    @_beat.before_loop
    async def _before_beat(self):
        # Wait until the gateway is ready so latency/member-count/loaded-cogs are meaningful.
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(HeartbeatCog(bot))
