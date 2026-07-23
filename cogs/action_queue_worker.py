"""Bot-side dispatcher for the shared sqlite action queue (INFRA-01)."""

import asyncio
import json
import logging

from discord.ext import commands, tasks

from core import action_queue, db

log = logging.getLogger(__name__)


class ActionQueueCog(commands.Cog):
    """Claims and dispatches one queued action at a time on a near-instant cadence."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_action_queue()
        self._dispatch = {"noop": self._handle_noop}  # Phases 6-9 add kinds here.
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


async def setup(bot: commands.Bot):
    await bot.add_cog(ActionQueueCog(bot))
