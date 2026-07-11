"""JinxxyCog — the Fase 9 store auto-sync controller (STORE-SYNC-01).

Wires the three cores (the ``jinxxy_api`` read client, the pure ``store_sync`` merge, and the
object-aware ``github_publish`` transport) into one Discord cog:

  * a background ``@tasks.loop`` poll (``JINXXY_POLL_HOURS``, D-03 band 6-12h),
  * a staff-gated ``/tienda sync`` command (D-02 manual trigger — added in Task 2),
  * a run-once startup ``on_ready`` reconcile so a restart converges (Task 3),

all funnelled through ONE :meth:`JinxxyCog._run_sync` orchestration: enumerate Jinxxy → map →
three-way merge against the durable snapshot + the live ``store.json`` → commit ONLY on change
→ update the snapshot → return the reconcile result for the announce step.

Hard rules (locked decisions):

  * **D-05 — errors never reach Discord.** Every failure path is ``log.exception`` only; nothing
    operational is ever posted to the announce channel. The single user-facing error is an
    EPHEMERAL reply to the staff invoker of ``/tienda sync`` (USER-CONFIRMED 2026-07-10).
  * **T-09-15 removal-safety.** ``get_me`` / ``list_all_products`` RAISE ``JinxxyAPIError`` on an
    outage (never return ``[]``), and enumeration happens BEFORE any commit/removal, so a
    transient API failure aborts ``_run_sync`` with no ``sync_store`` and no
    ``delete_store_snapshot`` — the storefront can never be mass-removed on an outage.
  * **D-06 — silent on no change.** A reconcile that reports ``changed=False`` commits nothing.
"""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import db, github_publish, jinxxy_api, store_sync

log = logging.getLogger(__name__)

# Brand red for the store announce embed (matches the reviews/reminders/gallery embeds).
_BRAND_RED = 0xC0192C


# ── staff gate (D-02 / T-09-14) ─────────────────────────────────────────────────────
def _is_staff(member) -> bool:
    """True iff ``member`` holds a configured Jinxxy-staff role (trust boundary, T-09-14).

    ``JINXXY_STAFF_ROLE_IDS`` falls back to ``GALLERY_STAFF_ROLE_IDS`` when unset (same idiom as
    reviews/reminders). A bot or a role-less member is never staff (empty intersection is falsy).
    """
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(role_ids & set(config.JINXXY_STAFF_ROLE_IDS))


def _snapshot_from_row(row) -> dict:
    """Rebuild the sync-owned-shaped snapshot dict from a ``store_snapshot`` row (DB, D-12).

    ``three_way_merge`` compares ``live`` (``map_product`` output) against this snapshot per
    sync-owned field, so the reconstruction must reproduce the live SHAPE exactly: ``name`` is a
    ``{"es","en"}`` object (map_product writes the same verbatim name into both locales, so the
    single stored string re-expands losslessly) and ``nsfw`` is a bool (stored 0/1).
    """
    name = row["name"] or ""
    return {
        "checkoutUrl": row["checkout_url"],
        "name": {"es": name, "en": name},
        "price": row["price"],
        "category": row["category"],
        "nsfw": bool(row["nsfw"]),
        "date": row["date"],
    }


class JinxxyCog(
    commands.GroupCog,
    name="Jinxxy",
    group_name="tienda",
    group_description="Sincroniza la tienda con Jinxxy (staff)",
):
    """The ``/tienda`` command group + the background store-sync poll loop.

    The poll loop and the (Task 2) ``/tienda sync`` command both delegate to :meth:`_run_sync`,
    so there is exactly one sync code path — no drift between the scheduled and the manual sync.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._synced_once = False                  # run-once guard for the on_ready reconcile
        db.init_store_state()                      # repo idiom: ensure the snapshot table exists
        self._poll.start()                         # start the tasks.loop cadence

    async def cog_unload(self):
        # Hot-reload safety — mirrors reminders.cog_unload so a reload doesn't leave a second
        # poll loop ticking.
        self._poll.cancel()

    # ── core orchestration ───────────────────────────────────────────────────────────
    async def _run_sync(self) -> dict:
        """Run ONE full store sync: enumerate → map → three-way merge → commit-on-change.

        Ordering IS the removal-safety guarantee (T-09-15): the live enumeration (``get_me`` +
        ``list_all_products`` + per-product ``get_product``) happens FIRST and RAISES
        ``JinxxyAPIError`` on any failure, so an outage aborts here — before ``reconcile_store``,
        before ``sync_store`` and before any ``delete_store_snapshot``. Returns the reconcile
        result (``added``/``updated``/``removed``/``changed``/``products``) for the announce step.
        """
        # 1. /me → the store username (checkoutUrl construction, D-17) + owner display name
        #    (the `editor` default, D-09). Raises on outage.
        me = await asyncio.to_thread(jinxxy_api.get_me)
        store_username = me.get("username") or ""
        owner_name = me.get("display_name") or ""

        # 2. Full enumeration + per-product detail → mapped live entries keyed by checkoutUrl.
        #    Any failure here raises (never a partial/empty list), so removals never run.
        products = await asyncio.to_thread(jinxxy_api.list_all_products)
        live_by_key: dict[str, dict] = {}
        jinxxy_id_by_key: dict[str, str] = {}
        for p in products:
            pid = p.get("id")
            detail = await asyncio.to_thread(jinxxy_api.get_product, pid)
            entry = store_sync.map_product(detail, store_username, owner_name)
            url = entry["checkoutUrl"]
            if not store_sync.is_https_url(url):
                log.warning("jinxxy: checkoutUrl no-https omitido (id=%s): %r", pid, url)
                continue
            live_by_key[url] = entry
            jinxxy_id_by_key[url] = "" if pid is None else str(pid)

        # 3. Durable snapshot (DB) + current store.json (cross-repo read), keyed by checkoutUrl.
        snapshots = {k: _snapshot_from_row(r) for k, r in db.get_store_snapshot().items()}
        current = await asyncio.to_thread(
            github_publish._fetch_store,
            config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_STORE_JSON)
        current_by_key = {
            p["checkoutUrl"]: p
            for p in (current.get("products") or [])
            if isinstance(p, dict) and p.get("checkoutUrl")
        }

        # 4. Whole-store three-way reconcile (pure).
        result = store_sync.reconcile_store(snapshots, live_by_key, current_by_key)

        # 5. Commit ONLY on change (D-06), then make the durable snapshot reflect live truth:
        #    upsert every live product, delete every removed key.
        if result["changed"]:
            await github_publish.sync_store(result["products"])
            for key, entry in live_by_key.items():
                name = entry["name"]["es"] if isinstance(entry.get("name"), dict) \
                    else entry.get("name")
                db.upsert_store_snapshot(
                    checkout_url=key,
                    jinxxy_id=jinxxy_id_by_key.get(key, ""),
                    name=name,
                    price=entry["price"],
                    category=entry["category"],
                    nsfw=1 if entry["nsfw"] else 0,
                    date=entry["date"],
                )
            for key in result["removed"]:
                db.delete_store_snapshot(key)

        return result

    # ── background poll loop (Phase-8 shape, cadence-only change) ──────────────────────
    @tasks.loop(hours=config.JINXXY_POLL_HOURS)
    async def _poll(self):
        result = await self._run_sync()
        await self._announce(result)

    @_poll.before_loop
    async def _before_poll(self):
        # Wait until the gateway is ready so the announce channel resolves (reminders idiom).
        await self.bot.wait_until_ready()

    @_poll.error
    async def _on_poll_error(self, exc: Exception):
        # LOGS ONLY (D-05) — a sync failure never reaches Discord. Restart so the next cadence
        # runs (mirrors reminders._on_scheduler_error).
        log.exception("jinxxy: el poll de la tienda se cayó, reiniciando", exc_info=exc)
        self._poll.restart()

    # ── announce (filled in Task 2) ───────────────────────────────────────────────────
    async def _announce(self, result: dict):
        """Announce store changes (added/updated/removed) — silent on no change (D-06).

        Implemented in Task 2; the no-op guard here keeps the poll loop safe in the interim.
        """
        if not result or not result.get("changed"):
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(JinxxyCog(bot))
