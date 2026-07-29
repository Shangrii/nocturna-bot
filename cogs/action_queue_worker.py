"""Bot-side dispatcher for the shared sqlite action queue (INFRA-01)."""

import asyncio
import json
import logging

import discord
from discord.ext import commands, tasks

import config
from cogs.gallery import _is_published as gallery_is_published
from cogs.jinxxy import sync_error_category
from cogs.reviews import _is_published as reviews_is_published
from core import action_queue, db

log = logging.getLogger(__name__)


class ActionQueueCog(commands.Cog):
    """Claims and dispatches one queued action at a time on a near-instant cadence."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_action_queue()
        self._dispatch = {
            "noop": self._handle_noop,
            "gallery_publish": self._handle_gallery_publish,
            "gallery_remove": self._handle_gallery_remove,
            "review_publish": self._handle_review_publish,
            "review_remove": self._handle_review_remove,
            "jinxxy_sync": self._handle_jinxxy_sync,
            "meeting_republish": self._handle_meeting_republish,
        }
        self._tick.start()

    async def cog_unload(self):
        self._tick.cancel()

    @tasks.loop(seconds=1.5)  # D-04: near-instant, not the 45s heartbeat cadence.
    async def _tick(self):
        await self._run_once()

    async def _run_once(self):
        """Recover, claim, and dispatch at most one action without starting the scheduler."""
        try:
            await asyncio.to_thread(action_queue.recover_stale_claims)
            row = await asyncio.to_thread(action_queue.claim_next)
        except Exception:
            log.exception("action_queue: no pude reclamar/recuperar filas")
            return
        if row is None:
            return

        try:
            handler = self._dispatch.get(row["kind"])
            if handler is None:
                raise ValueError(f"unknown action kind: {row['kind']!r}")
            payload = json.loads(row["payload_json"])
            result = await handler(payload)
            await asyncio.to_thread(action_queue.complete, row["id"], result)
        except Exception as exc:
            log.exception("action_queue: acción %s falló", row["id"])
            await asyncio.to_thread(action_queue.fail, row["id"], str(exc))

    @_tick.before_loop
    async def _before_tick(self):
        await self.bot.wait_until_ready()

    async def _handle_noop(self, payload: dict) -> dict:
        """Exercise the queue end to end without performing any real business action."""
        if payload.get("force_fail"):
            raise RuntimeError("noop: forced failure (test payload)")
        return {"echo": payload.get("echo")}

    async def _resolve_channel(self, channel_id: int):
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)
        if channel is None:
            raise RuntimeError(
                "el canal no está disponible · channel is not available"
            )
        return channel

    @staticmethod
    async def _fetch_message(channel, message_id: int):
        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound as exc:
            raise RuntimeError(
                "el mensaje ya no existe · message no longer exists"
            ) from exc

    async def _handle_gallery_publish(self, payload: dict) -> dict:
        message_id = int(payload["message_id"])
        channel = await self._resolve_channel(config.PHOTO_CHANNEL_ID)
        message = await self._fetch_message(channel, message_id)
        was_published = gallery_is_published(message)

        gallery_cog = self.bot.get_cog("GalleryCog")
        if gallery_cog is None:
            raise RuntimeError(
                "GalleryCog no está cargado · GalleryCog is not loaded"
            )
        await gallery_cog._publish(message)

        message = await self._fetch_message(channel, message_id)
        is_published = gallery_is_published(message)
        if is_published:
            return {"already": was_published}
        raise RuntimeError(
            "no se pudo publicar · publish did not complete "
            "(see ⚠️ on the Discord message)"
        )

    async def _handle_gallery_remove(self, payload: dict) -> dict:
        message_id = int(payload["message_id"])
        channel = await self._resolve_channel(config.PHOTO_CHANNEL_ID)
        message = await self._fetch_message(channel, message_id)
        was_published = gallery_is_published(message)

        gallery_cog = self.bot.get_cog("GalleryCog")
        if gallery_cog is None:
            raise RuntimeError(
                "GalleryCog no está cargado · GalleryCog is not loaded"
            )
        await gallery_cog._unpublish(message)

        message = await self._fetch_message(channel, message_id)
        is_published = gallery_is_published(message)
        if not is_published:
            return {"already": not was_published}
        raise RuntimeError(
            "no se pudo quitar · remove did not complete "
            "(see ⚠️ on the Discord message)"
        )

    async def _handle_review_publish(self, payload: dict) -> dict:
        message_id = int(payload["message_id"])
        channel = await self._resolve_channel(config.REVIEWS_CHANNEL_ID)
        message = await self._fetch_message(channel, message_id)
        was_published = reviews_is_published(message)

        reviews_cog = self.bot.get_cog("ReviewsCog")
        if reviews_cog is None:
            raise RuntimeError(
                "ReviewsCog no está cargado · ReviewsCog is not loaded"
            )
        await reviews_cog._publish(message)

        message = await self._fetch_message(channel, message_id)
        is_published = reviews_is_published(message)
        if is_published:
            return {"already": was_published}
        raise RuntimeError(
            "no se pudo publicar · publish did not complete "
            "(see ⚠️ on the Discord message)"
        )

    async def _handle_review_remove(self, payload: dict) -> dict:
        message_id = int(payload["message_id"])
        channel = await self._resolve_channel(config.REVIEWS_CHANNEL_ID)
        message = await self._fetch_message(channel, message_id)
        was_published = reviews_is_published(message)

        reviews_cog = self.bot.get_cog("ReviewsCog")
        if reviews_cog is None:
            raise RuntimeError(
                "ReviewsCog no está cargado · ReviewsCog is not loaded"
            )
        await reviews_cog._unpublish(message)

        message = await self._fetch_message(channel, message_id)
        is_published = reviews_is_published(message)
        if not is_published:
            return {"already": not was_published}
        raise RuntimeError(
            "no se pudo quitar · remove did not complete "
            "(see ⚠️ on the Discord message)"
        )

    async def _handle_jinxxy_sync(self, payload: dict) -> dict:
        # The payload carries no `source`: the trigger is inferred as "panel" by
        # construction, since /tienda sync and the scheduled poll never touch action_queue.
        actor_name = payload.get("actor_name") or None
        try:
            # Lookup key is "Jinxxy" — the `name=` kwarg on JinxxyCog's `GroupCog`
            # declaration, NOT the class name (unlike GalleryCog/ReviewsCog, which have
            # no `name=` override). A missing cog is mapped to a fixed D-10 category
            # below too, so the panel never sees this internal wording.
            jinxxy_cog = self.bot.get_cog("Jinxxy")
            if jinxxy_cog is None:
                raise RuntimeError(
                    "JinxxyCog no está cargado · JinxxyCog is not loaded"
                )
            result = await jinxxy_cog._run_sync_guarded(source="panel", actor_name=actor_name)
        except Exception as exc:
            log.exception("action_queue: jinxxy_sync falló")
            raise RuntimeError(sync_error_category(exc)) from exc

        if result.get("already"):
            return {"already": True}
        return {
            "already": False,
            "changed": bool(result.get("changed")),
            "added": len(result.get("added") or []),
            "updated": len(result.get("updated") or []),
            "removed": len(result.get("removed") or []),
            "products": len(result.get("products") or []),
        }

    async def _handle_meeting_republish(self, payload: dict) -> dict:
        meeting_id = int(payload["meeting_id"])
        actor_name = payload.get("actor_name") or None
        meeting_cog = self.bot.get_cog("Meeting")
        if meeting_cog is None:
            raise RuntimeError(
                "MeetingCog no está cargado · MeetingCog is not loaded"
            )
        return await meeting_cog._republish(
            meeting_id, actor_name=actor_name
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ActionQueueCog(bot))
