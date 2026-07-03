"""Gallery publishing cog (Phase 5) — staff-approved photo auto-publishing.

Watches the public photos channel (``config.PHOTO_CHANNEL_ID``): when a staff-role
member posts image attachments the cog adds a ✅ approve control (BOT-01/D-03); a staff
✅ optimizes every image to WebP and commits it live to the website repo in one
cross-repo commit with the message text as caption (BOT-02/BOT-06). Removal (🌙),
resilience, and startup backfill land in 05-04.

Mirrors the repo's cog conventions (``cogs/forum.py``): a ``commands.Cog`` subclass with
``@commands.Cog.listener()`` handlers, ``import config``, ``log = logging.getLogger(__name__)``
and a module-level ``async def setup(bot)``. The two proven cores are wired here:
``core.image_optimize.optimize_to_webp`` (run off the event loop via ``asyncio.to_thread``)
and ``core.github_publish.publish_message`` (one atomic commit per approved message).
"""

import logging

import discord
from discord.ext import commands

import config
from core import db

log = logging.getLogger(__name__)


class GalleryCog(commands.Cog):
    """Detects staff photo posts and publishes approved images to the live gallery."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_gallery_state()   # backfill-cursor table (05-04 reads/writes it)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Detection + ✅ approve control implemented in Task 2.
        return

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Publish orchestration implemented in Task 3.
        return


async def setup(bot: commands.Bot):
    await bot.add_cog(GalleryCog(bot))
