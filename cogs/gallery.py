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
from datetime import timezone

import discord
from discord.ext import commands

import config
from core import db

log = logging.getLogger(__name__)

# D-13: only static images are published; gif/video/other attachments are skipped.
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


# ── pure helpers (import without a running bot; unit-proven in test_gallery_cog) ──
def _image_attachments(message):
    """Static-image attachments only (D-13): png/jpeg/webp; gif/video/other skipped."""
    return [a for a in message.attachments if (a.content_type or "") in IMAGE_TYPES]


def _is_staff(member) -> bool:
    """True iff the member holds a configured staff role (D-01 trust boundary).

    Self-approval is allowed (D-02): the poster is staff, so their own reaction counts.
    """
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(role_ids & set(config.GALLERY_STAFF_ROLE_IDS))


def _build_filename(message_id, created_at, index) -> str:
    """``{YYYYMMDD}-{message_id}-{index}.webp`` — numerics only (D-14).

    The date segment is the message's UTC creation day. The name carries no user text,
    so removal stays derivable from the middle ``{message_id}`` segment and no caption
    character can ever reach a filesystem path (path-traversal guard, T-05-09).
    """
    day = created_at.astimezone(timezone.utc).strftime("%Y%m%d")
    return f"{day}-{message_id}-{index}.webp"


def _caption(message_content) -> str:
    """Trimmed caption text (BOT-06); empty string for whitespace-only/None so the
    published entry omits the ``caption`` key entirely (Phase 4 contract)."""
    return (message_content or "").strip()


class GalleryCog(commands.Cog):
    """Detects staff photo posts and publishes approved images to the live gallery."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_gallery_state()   # backfill-cursor table (05-04 reads/writes it)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Detection + ✅ approve control (BOT-01/D-03): only staff image posts in the
        # photo channel are marked; community + non-image posts are ignored entirely.
        if message.channel.id != config.PHOTO_CHANNEL_ID or message.author.bot:
            return
        if not _is_staff(message.author):
            return
        if _image_attachments(message):
            await message.add_reaction("✅")   # the approve control (BOT-01)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # Publish orchestration implemented in Task 3.
        return


async def setup(bot: commands.Bot):
    await bot.add_cog(GalleryCog(bot))
