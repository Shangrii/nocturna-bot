"""Bot-side gallery/reviews queue cache for the credential-less admin app."""

import asyncio
import logging

from discord.ext import commands, tasks

import config
from cogs.gallery import (
    _entry_message_id as gallery_entry_message_id,
    _image_attachments,
    _is_published as gallery_is_published,
)
from cogs.reviews import (
    REVIEW_ANON_LABEL,
    _is_own_review_embed,
    _is_published as reviews_is_published,
    _review_author_and_text,
)
from core import db, github_publish

log = logging.getLogger(__name__)

_SCAN_LIMIT = 300


class GalleryReviewsCacheCog(commands.Cog):
    """Periodically pushes Discord-native moderation state into shared sqlite."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_gallery_queue()
        db.init_reviews_queue()
        self._push.start()

    async def cog_unload(self):
        self._push.cancel()

    @tasks.loop(seconds=45)
    async def _push(self):
        try:
            await self._push_gallery()
        except Exception:
            log.exception("gallery cache: no pude actualizar la cola")

        try:
            await self._push_reviews()
        except Exception:
            log.exception("reviews cache: no pude actualizar la cola")

    async def _push_gallery(self):
        channel = self.bot.get_channel(config.PHOTO_CHANNEL_ID) or (
            await self.bot.fetch_channel(config.PHOTO_CHANNEL_ID)
        )
        if channel is None:
            return

        entries = await asyncio.to_thread(
            github_publish._fetch_gallery,
            config.WEBSITE_REPO,
            config.WEBSITE_BRANCH,
        )
        seen_ids: set[int] = set()
        async for message in channel.history(
            limit=_SCAN_LIMIT,
            oldest_first=False,
        ):
            if getattr(message.author, "bot", False):
                continue
            images = _image_attachments(message)
            if not images:
                continue

            message_id = int(message.id)
            seen_ids.add(message_id)
            state = (
                "published"
                if gallery_is_published(message, entries)
                else "pending"
            )
            await asyncio.to_thread(
                db.upsert_gallery_queue_row,
                message_id,
                state,
                message.author.display_name,
                message.content,
                str(images[0].url),
                message.created_at.isoformat(),
                (
                    "https://discord.com/channels/"
                    f"{config.GUILD_ID}/{config.PHOTO_CHANNEL_ID}/{message_id}"
                ),
            )

        published_ids = {
            message_id
            for entry in entries or []
            if (message_id := gallery_entry_message_id(entry)) is not None
        }
        cached_rows = [
            *await asyncio.to_thread(db.get_gallery_queue, "pending"),
            *await asyncio.to_thread(db.get_gallery_queue, "published"),
        ]
        for row in cached_rows:
            message_id = int(row["message_id"])
            if message_id not in seen_ids and message_id not in published_ids:
                await asyncio.to_thread(
                    db.delete_gallery_queue_row,
                    message_id,
                )

    async def _push_reviews(self):
        channel = self.bot.get_channel(config.REVIEWS_CHANNEL_ID) or (
            await self.bot.fetch_channel(config.REVIEWS_CHANNEL_ID)
        )
        if channel is None:
            return

        entries = await asyncio.to_thread(
            github_publish._fetch_json,
            config.WEBSITE_REPO,
            config.WEBSITE_BRANCH,
            config.WEBSITE_REVIEWS_JSON,
        )
        seen_ids: set[int] = set()
        async for message in channel.history(
            limit=_SCAN_LIMIT,
            oldest_first=False,
        ):
            if (
                getattr(message.author, "bot", False)
                and not _is_own_review_embed(message)
            ):
                continue

            author, text = _review_author_and_text(message)
            if not text:
                continue

            message_id = int(message.id)
            seen_ids.add(message_id)
            is_anonymous = author is None
            author_value = None if is_anonymous else author
            state = (
                "published"
                if reviews_is_published(message, entries)
                else "pending"
            )
            await asyncio.to_thread(
                db.upsert_reviews_queue_row,
                message_id,
                state,
                author_value,
                int(is_anonymous),
                text,
                message.created_at.isoformat(),
                (
                    "https://discord.com/channels/"
                    f"{config.GUILD_ID}/{config.REVIEWS_CHANNEL_ID}/{message_id}"
                ),
            )

        published_ids = set()
        for entry in entries or []:
            raw_id = entry.get("id") if isinstance(entry, dict) else None
            try:
                published_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue

        cached_rows = [
            *await asyncio.to_thread(db.get_reviews_queue, "pending"),
            *await asyncio.to_thread(db.get_reviews_queue, "published"),
        ]
        for row in cached_rows:
            message_id = int(row["message_id"])
            if message_id not in seen_ids and message_id not in published_ids:
                await asyncio.to_thread(
                    db.delete_reviews_queue_row,
                    message_id,
                )

    @_push.before_loop
    async def _before_push(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(GalleryReviewsCacheCog(bot))
