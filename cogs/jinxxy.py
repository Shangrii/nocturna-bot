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
import hashlib
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import db, github_publish, image_optimize, jinxxy_api, store_sync

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


# ── /tienda medios helpers (D-14/D-15 staff-supplied images + description) ────────────
def _slug_from_url(checkout_url: str) -> str:
    """A filesystem-safe base slug for image filenames — numerics/letters/hyphens only.

    Derived from the checkoutUrl's last path segment (the Jinxxy product slug) and re-sanitised
    so NO raw user text can ever reach a committed path (T-09-19). Falls back to a short hash of
    the URL when the tail sanitises to empty, so a filename base is ALWAYS bot-generated.
    """
    tail = (checkout_url or "").rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"[^a-z0-9-]", "", tail.lower())
    if not slug:
        slug = hashlib.md5((checkout_url or "").encode("utf-8")).hexdigest()[:10]
    return slug


def _optimize_attachments(raws, slug="store"):
    """Optimize each raw attachment to WebP + a bot-generated ``{slug}-{index}.webp`` name.

    Pure/synchronous (the cog runs it off the event loop via ``asyncio.to_thread``): reuses the
    gallery ``optimize_to_webp`` pipeline (downscale-only 1920px, EXIF/GPS stripped, re-encoded so
    arbitrary upload bytes never land verbatim — T-09-19). Filenames carry NO raw user text: the
    ``slug`` is a sanitised base (see :func:`_slug_from_url`) and the suffix is a numeric index.
    """
    base = slug or "store"
    media = []
    for index, raw in enumerate(raws, start=1):
        webp, _width, _height = image_optimize.optimize_to_webp(raw)
        media.append((webp, f"{base}-{index}.webp"))
    return media


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

    # ── startup reconcile (converge on restart, run-once) ─────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        """Run ONE startup sync so a restart converges (``on_ready`` can re-fire on reconnects).

        Reuses the SAME :meth:`_run_sync` path (no separate reconcile code to drift): it
        reconciles the durable snapshot vs the live ``store.json`` vs Jinxxy — importing missed
        products (D-13 first-run linking by checkoutUrl), propagating changes, removing delistings.
        The removal-safety in ``_run_sync`` (an API failure raises before any removal) already
        protects a cold-start outage; here that raise is caught and logged (D-05), never crashing.
        """
        if self._synced_once:
            return
        self._synced_once = True
        try:
            result = await self._run_sync()
            await self._announce(result)
        except Exception:
            log.exception("jinxxy: la reconciliación de arranque falló (se reintenta en el poll)")

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

    # ── /tienda sync (D-02 manual trigger) ────────────────────────────────────────────
    @app_commands.command(
        name="sync",
        description="Fuerza una sincronización de la tienda con Jinxxy (staff)")
    async def sync(self, interaction: discord.Interaction):
        """Staff-forced full sync. Staff gate FIRST (T-09-14), then the shared ``_run_sync``.

        On success the store changes are announced (public, store-news only) and the invoker gets
        an ephemeral summary. On failure NOTHING is announced (D-05): the error is logged and the
        invoking STAFF member gets an EPHEMERAL "revisa los logs" reply — a direct command reply
        to the caller, never a public error post (USER-CONFIRMED 2026-07-10).
        """
        # 1. Staff gate FIRST — before defer or any sync work (Phase-8 CR-01 lesson, T-09-14).
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # 2. Defer (a full sync can exceed Discord's 3s ack window).
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self._run_sync()
        except (github_publish.GitHubPublishError, jinxxy_api.JinxxyAPIError):
            # D-05: errors go to logs ONLY. The one user-facing signal is this EPHEMERAL reply
            # to the invoker — the public announce channel stays store-news-only.
            log.exception("jinxxy: /tienda sync falló")
            await interaction.followup.send(
                "No pude sincronizar ahora; revisa los logs.", ephemeral=True)
            return

        # 3. Announce (silent on no change, D-06) then confirm to the invoker.
        await self._announce(result)
        if result["changed"]:
            summary = (f"Sincronización lista: {len(result['added'])} nuevos, "
                       f"{len(result['updated'])} actualizados, "
                       f"{len(result['removed'])} quitados.")
        else:
            summary = "Sin cambios."
        await interaction.followup.send(summary, ephemeral=True)

    # ── /tienda medios (D-14/D-15 staff-supplied images + bilingual description) ────────
    @app_commands.command(
        name="medios",
        description="Adjunta imágenes y descripción a un producto de la tienda (staff)")
    @app_commands.describe(
        producto="Producto de la tienda (usa el autocompletar)",
        imagen1="Imagen principal (se optimiza a WebP)",
        imagen2="Imagen adicional (opcional)",
        imagen3="Imagen adicional (opcional)",
        imagen4="Imagen adicional (opcional)",
        descripcion_es="Descripción en español (opcional)",
        descripcion_en="Descripción en inglés (opcional)")
    async def medios(
        self,
        interaction: discord.Interaction,
        producto: str,
        imagen1: discord.Attachment,
        imagen2: discord.Attachment | None = None,
        imagen3: discord.Attachment | None = None,
        imagen4: discord.Attachment | None = None,
        descripcion_es: str | None = None,
        descripcion_en: str | None = None,
    ):
        """Attach up to 4 optimized images + a bilingual description to a synced product.

        The Creator API exposes no images/description (D-14 live probe), so staff supply them here
        (STORE-SYNC-02). Only IMAGES + DESCRIPTION are ever written — never a sync-owned field
        (this flow and the merge are disjoint, D-12/D-15). Staff gate FIRST (T-09-18): a non-staff
        invoker gets "Sin permisos." before any attachment byte is read. Attachments are re-encoded
        to WebP with bot-generated numeric filenames (T-09-19), then committed via
        ``attach_store_media`` (09-04) matched by ``checkoutUrl``. On a transport failure NOTHING is
        posted publicly (D-05): the error is logged and the STAFF invoker gets an ephemeral reply.
        """
        # 1. Staff gate FIRST — before defer or any attachment read (T-09-18).
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # 2. Defer (reading attachments + optimizing + a cross-repo commit exceeds the 3s ack).
        await interaction.response.defer(ephemeral=True)

        # 3. Read every provided attachment's bytes, then optimize to WebP off the event loop.
        attachments = [a for a in (imagen1, imagen2, imagen3, imagen4) if a is not None]
        try:
            raws = [await att.read() for att in attachments]
        except discord.HTTPException:
            log.exception("jinxxy: no pude descargar los adjuntos de /tienda medios")
            await interaction.followup.send(
                "No pude descargar las imágenes; inténtalo de nuevo.", ephemeral=True)
            return
        media = await asyncio.to_thread(
            _optimize_attachments, raws, _slug_from_url(producto))

        # 4. Build the description dict ONLY from the provided locale params. Omit a key when its
        #    param is None so a partial edit doesn't wipe the other locale (09-04's None-skip).
        description = {}
        if descripcion_es is not None:
            description["es"] = descripcion_es
        if descripcion_en is not None:
            description["en"] = descripcion_en
        description = description or None

        # 5. Commit images + description into the matched product (one atomic commit, 09-04).
        try:
            await github_publish.attach_store_media(producto, media, description)
        except github_publish.GitHubPublishError:
            # D-05: errors go to logs ONLY; the one user-facing signal is this ephemeral reply
            # to the STAFF invoker — never a public post.
            log.exception("jinxxy: /tienda medios falló")
            await interaction.followup.send(
                "No pude adjuntar los medios; revisa los logs.", ephemeral=True)
            return

        await interaction.followup.send(
            f"Adjunté {len(media)} imagen(es) y la descripción al producto — "
            "la web tarda un par de minutos.", ephemeral=True)

    @medios.autocomplete("producto")
    async def _medios_producto_autocomplete(
            self, interaction: discord.Interaction, current: str):
        # Delegates to a plainly-testable coroutine (the registered callback is awkward to reach
        # in unit tests). Staff gate + snapshot read live in _producto_choices.
        return await self._producto_choices(interaction, current)

    async def _producto_choices(
            self, interaction: discord.Interaction,
            current: str) -> list[app_commands.Choice[str]]:
        """Autocomplete Choices from the synced products — ``[]`` for a non-staff caller (T-09-18).

        The staff gate returns an empty Choice list for a non-staff member BEFORE any store read
        (an autocomplete callback cannot send an ephemeral reply — CR-01). For staff, reads the
        durable snapshot (local SQLite, fast per keystroke) and offers ``label = product name`` /
        ``value = checkoutUrl``, substring-filtered by ``current``, capped at Discord's 25.
        """
        if not _is_staff(interaction.user):
            return []
        rows = await asyncio.to_thread(db.get_store_snapshot)
        needle = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []
        for key, row in rows.items():
            name = row["name"] or key
            if needle and needle not in str(name).lower() and needle not in str(key).lower():
                continue
            choices.append(app_commands.Choice(name=str(name)[:100], value=str(key)[:100]))
            if len(choices) >= 25:
                break
        return choices

    # ── announce (D-05 / D-06) ────────────────────────────────────────────────────────
    async def _announce(self, result: dict):
        """Post a branded store-news embed (added/updated/removed) — silent on no change.

        Reached ONLY after a successful sync (the caller returns on any error), so this method
        never carries an error (D-05). A no-change result is silent (D-06). An unresolvable
        announce channel is logged and skipped — never raised — so a bad channel id can't crash
        the poll loop.
        """
        if not result or not result.get("changed"):
            return

        channel = self.bot.get_channel(config.JINXXY_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(config.JINXXY_ANNOUNCE_CHANNEL_ID)
            except discord.HTTPException:
                channel = None
        if channel is None:
            log.warning(
                "jinxxy: canal de anuncios %s no encontrado — omito el anuncio de la tienda",
                config.JINXXY_ANNOUNCE_CHANNEL_ID)
            return

        await channel.send(embed=self._build_announce_embed(result))

    @staticmethod
    def _build_announce_embed(result: dict) -> discord.Embed:
        """Spanish-first, brand-red store-news embed listing added/updated/removed product names."""
        by_key = {
            p.get("checkoutUrl"): p
            for p in (result.get("products") or []) if isinstance(p, dict)
        }

        def _names(keys):
            out = []
            for k in keys:
                p = by_key.get(k)
                name = None
                if isinstance(p, dict):
                    n = p.get("name")
                    name = n.get("es") if isinstance(n, dict) else n
                out.append(str(name or k))         # removed keys aren't in products → show the key
            return out

        embed = discord.Embed(title="Tienda actualizada", color=_BRAND_RED)
        buckets = (("🆕 Nuevos", result.get("added") or []),
                   ("✏️ Actualizados", result.get("updated") or []),
                   ("🗑️ Quitados", result.get("removed") or []))
        for label, keys in buckets:
            if keys:
                names = _names(keys)
                embed.add_field(
                    name=f"{label} ({len(keys)})",
                    value="\n".join(f"• {n}" for n in names)[:1024], inline=False)
        embed.set_footer(text="Nocturna · tienda")
        embed.timestamp = discord.utils.utcnow()
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(JinxxyCog(bot))
