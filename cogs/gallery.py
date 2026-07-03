"""Gallery publishing cog (Phase 5) — staff-approved photo auto-publishing.

Watches the public photos channel (``config.PHOTO_CHANNEL_ID``): when a staff-role
member posts image attachments the cog adds a ✅ approve control (BOT-01/D-03); a staff
✅ optimizes every image to WebP and commits it live to the website repo in one
cross-repo commit with the message text as caption (BOT-02/BOT-06). A staff 🌙 unpublishes
a live message's photos or dismisses a pending one (BOT-05/D-06..D-09), and deleting a
published message auto-unpublishes it (D-10). Persistent-error UX (D-19) and startup
backfill (D-20) complete the cog.

Mirrors the repo's cog conventions (``cogs/forum.py``): a ``commands.Cog`` subclass with
``@commands.Cog.listener()`` handlers, ``import config``, ``log = logging.getLogger(__name__)``
and a module-level ``async def setup(bot)``. The two proven cores are wired here:
``core.image_optimize.optimize_to_webp`` (run off the event loop via ``asyncio.to_thread``)
and ``core.github_publish.publish_message`` (one atomic commit per approved message).
"""

import asyncio
import logging
from datetime import timezone

import discord
from discord.ext import commands

import config
from core import db, github_publish
from core.image_optimize import optimize_to_webp

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


def _is_published(message, entries=None) -> bool:
    """True iff the message is already published — Discord-native derived state (D-05/D-14).

    A message counts as published when it carries the bot's own 🟢 marker reaction, OR
    (during startup reconcile, where the supplied ``entries`` are the live gallery.json)
    when an entry's filename has the EXACT ``{msgID}`` middle segment of ``message.id``.
    The match splits ``{YYYYMMDD}-{msgID}-{index}.webp`` on ``-`` and compares the middle
    segment exactly — never a substring — so a snowflake sharing a prefix cannot collide
    (D-14). No per-message DB row is needed: published-state is always derivable.
    """
    if any(str(r.emoji) == "🟢" and getattr(r, "me", False)
           for r in getattr(message, "reactions", [])):
        return True
    if entries:
        target = str(message.id)
        for entry in entries:
            parts = (entry.get("file", "") or "").split("-")
            if len(parts) >= 3 and parts[1] == target:
                return True
    return False


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
        # RAW event (Pattern 1): works even when the message isn't cached (post-restart /
        # backfill). The role gate on payload.member is the trust boundary in the public
        # channel — a non-staff or bot reaction can never trigger a publish (D-01/D-08).
        if payload.channel_id != config.PHOTO_CHANNEL_ID:
            return
        if payload.member is None or payload.member.bot:   # member present for guild reactions
            return
        if not _is_staff(payload.member):                  # D-01/D-08 (self-approval OK, D-02)
            return
        emoji = str(payload.emoji)
        if emoji not in ("✅", "🌙"):                       # ✅ publishes; 🌙 unpublishes/dismisses
            return                                          # (🌙 shares the SAME staff gate, D-08)

        channel = self.bot.get_channel(payload.channel_id) or \
            await self.bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)  # fetch: not guaranteed cached
        if emoji == "✅":
            await self._publish(message)
        else:                                               # 🌙 removal / dismiss (D-06/D-07/D-09)
            await self._unpublish(message)

    async def _publish(self, message: discord.Message):
        """Optimize every image attachment and commit it live in ONE commit (BOT-02/D-16).

        Idempotent (D-05): a message already carrying the bot's 🟢 marker is skipped, so a
        second ✅ never double-publishes. The message text becomes the caption (BOT-06).
        """
        if any(str(r.emoji) == "🟢" and r.me for r in message.reactions):
            return                                          # already published (D-05)

        images = _image_attachments(message)                # D-13: non-images skipped silently
        if not images:
            return

        # Match the shipped gallery.json date shape exactly: ISO 8601, millisecond
        # precision, 'Z' suffix (e.g. 2026-07-03T14:05:09.000Z).
        date = message.created_at.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        date = date.replace("+00:00", "Z")
        caption = _caption(message.content)                 # BOT-06/D-06 (omitted when empty)

        entries = []
        for index, attachment in enumerate(images, start=1):
            raw = await attachment.read()
            # Keep Pillow's CPU re-encode off the event loop (Anti-Pattern otherwise).
            webp, width, height = await asyncio.to_thread(optimize_to_webp, raw)
            filename = _build_filename(message.id, message.created_at, index)  # D-14
            entries.append((webp, width, height, filename, caption))

        try:
            result = await github_publish.publish_message(message.id, entries, date=date)
        except Exception:
            # Persistent-error UX (D-19) lands in 05-04; here just log + propagate so the
            # 05-04 handler can wrap it. Do NOT add the 🟢 marker on failure.
            log.exception("gallery publish failed for discord msg %s", message.id)
            raise

        count = result.get("count", len(entries)) if isinstance(result, dict) else len(entries)
        await message.add_reaction("🟢")                    # persistent published marker (D-05)
        await message.reply(                                # auto-deleting confirmation (D-04)
            f"📸 Publiqué {count} foto{'s' if count != 1 else ''} en la galería — "
            "la web tarda un par de minutos en actualizarse.",
            delete_after=60,
        )

    async def _unpublish(self, message: discord.Message):
        """🌙 removal (published) or dismiss (pending) — the safe, judgment-free counterpart
        to publish (BOT-05).

        Published (has the bot's 🟢 marker): remove the message's photos + gallery.json
        entries in ONE commit (D-07 via ``github_publish.remove_message``), clear the 🟢
        marker so the message returns to pending — a later ✅ republishes it (D-09) — and
        send a Spanish-first ``delete_after`` reply that mirrors the publish feedback.
        Pending (never published — no 🟢): dismiss by clearing the bot's own ✅ prompt so
        it can't be published, and commit NOTHING (D-07).
        """
        if _is_published(message):
            result = await github_publish.remove_message(message.id)  # photos + entries, 1 commit
            count = result.get("count", 0) if isinstance(result, dict) else 0
            await message.remove_reaction("🟢", self.bot.user)  # back to pending (D-09)
            await message.reply(                            # mirrored auto-deleting feedback (D-09)
                f"🌙 Quité {count} foto{'s' if count != 1 else ''} de la galería — "
                "la web tarda un par de minutos en actualizarse.",
                delete_after=60,
            )
        else:
            # Pending: clear the ✅ prompt so it won't be published; no commit (D-07).
            await message.remove_reaction("✅", self.bot.user)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Deleting a published message auto-unpublishes its photos (D-10).

        The channel is the source of truth: a deleted photo message drops its gallery
        entries. ``remove_message`` derives the files statelessly from the message id
        (D-14) and is a safe no-op when nothing was published (text/non-photo deletes),
        so this never creates an empty commit. Accepted risk (T-05-11): an accidental
        delete removes the live photos — documented for the human-verification plan.
        """
        if payload.channel_id != config.PHOTO_CHANNEL_ID:
            return
        await github_publish.remove_message(payload.message_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(GalleryCog(bot))
