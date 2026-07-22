"""JinxxyCog — the Fase 9 store auto-sync controller (STORE-SYNC-01).

Wires the three cores (the ``jinxxy_api`` read client, the pure ``store_sync`` merge, and the
object-aware ``github_publish`` transport) into one Discord cog:

  * a background ``@tasks.loop`` poll (``JINXXY_POLL_HOURS``, D-03 band 6-12h) whose OWN immediate
    first tick (``tasks.loop`` runs it right after ``before_loop``'s ``wait_until_ready``) IS the
    single startup reconcile so a restart converges — there is no separate ``on_ready`` entry
    point (CR-01: a duplicate ``on_ready`` reconcile double-announced on boot),
  * a staff-gated ``/tienda sync`` command (D-02 manual trigger),

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
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from core import db, github_publish, image_optimize, jinxxy_api, store_sync

log = logging.getLogger(__name__)

# Brand red for the store announce embed (matches the reviews/reminders/gallery embeds).
_BRAND_RED = 0xC0192C

# WR-02: bounded cool-down before a poll restart. A persistent Jinxxy/GitHub outage must NOT turn
# the 6-12h cadence into a zero-delay retry hammer against both APIs — wait 15 min, then restart.
_POLL_RETRY_COOLDOWN_S = 900


# ── editor-string hardening (IN-01 / T-09-21) ───────────────────────────────────────
def _has_control_or_format_char(s: str) -> bool:
    """True iff ``s`` holds any Unicode control (``Cc``) or format (``Cf``) code point.

    A superset of the old ``[\\x00-\\x1f\\x7f]`` regex: ``Cc`` still covers the ASCII C0
    controls + DEL + newlines (T-09-21), while ``Cf`` additionally rejects zero-width and
    BIDI embedding/override/isolate characters that could visually spoof the credited editor
    name rendered verbatim on the public site. Category names are used rather than literal
    invisible/BIDI code points so none are embedded in this file.
    """
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in s)


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
        db.init_store_state()                      # repo idiom: ensure the snapshot table exists
        self._poll.start()                         # start the tasks.loop cadence — its immediate
                                                   # first tick is the sole startup reconcile (CR-01)

    async def cog_unload(self):
        # Hot-reload safety — mirrors reminders.cog_unload so a reload doesn't leave a second
        # poll loop ticking.
        self._poll.cancel()

    # ── D-10/D-11 sync-status + activity instrumentation ────────────────────────────
    async def _record_sync_status(
            self, *, ok: bool, product_count: int | None, error: str | None) -> None:
        """Record this run's outcome for the Overview dashboard (D-10 status tile + D-11
        "sync ran" activity row) — the single instrumentation point shared by both the
        success and failure paths of :meth:`_run_sync`, covering both the scheduled poll
        and the manual ``/tienda sync`` command (D-10/D-11).

        A status/activity-log write failure must never change the sync outcome or raise
        past this point (mirrors ``cogs/presence.py::_store``'s try/except idiom).
        """
        try:
            await asyncio.to_thread(
                db.set_jinxxy_sync_status, ok=ok, product_count=product_count, error=error)
            message = ("Sync de Jinxxy ejecutado / Jinxxy sync ran" if ok else
                       "Sync de Jinxxy falló / Jinxxy sync failed")
            await asyncio.to_thread(db.log_activity, "jinxxy_sync", message)
        except Exception:
            log.exception("jinxxy: no pude registrar el estado de sync")

    # ── core orchestration ───────────────────────────────────────────────────────────
    async def _run_sync(self) -> dict:
        """Run ONE full store sync: enumerate → map → three-way merge → commit-on-change.

        Ordering IS the removal-safety guarantee (T-09-15): the live enumeration (``get_me`` +
        ``list_all_products`` + per-product ``get_product``) happens FIRST and RAISES
        ``JinxxyAPIError`` on any failure, so an outage aborts here — before ``reconcile_store``,
        before ``sync_store`` and before any ``delete_store_snapshot``. Returns the reconcile
        result (``added``/``updated``/``removed``/``changed``/``products``) for the announce step.

        D-10/D-11: every run (success or failure) records its outcome via
        :meth:`_record_sync_status` — wrapped around the whole body so a failure anywhere in
        the sequence below still leaves a status/activity row, then re-raises unchanged so the
        existing D-05 error handling in ``_poll``/``_on_poll_error`` and ``/tienda sync``
        is untouched.
        """
        try:
            # 1. /me → the store username (checkoutUrl construction, D-17) + owner display name
            #    (the `editor` default, D-09). Raises on outage.
            me = await asyncio.to_thread(jinxxy_api.get_me)
            # WR-04: the username is load-bearing for EVERY checkoutUrl key. A malformed-but-2xx
            # /me with no username would build `jinxxy.com//slug` keys and mass-rewrite the whole
            # store, so hard-fail here — BEFORE enumeration/reconcile/commit. The raise routes
            # through the same removal-safety abort (T-09-15): no sync_store, no snapshot delete
            # on a bad /me.
            store_username = me.get("username")
            if not store_username:
                raise jinxxy_api.JinxxyAPIError("GET /me failed: response carried no username")
            # A missing display_name is a benign default (only the username keys the store).
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

            # 3. Durable snapshot (DB) + current store.json (cross-repo read), keyed by
            #    checkoutUrl. WR-06: an entry that is a non-dict, has no/falsy checkoutUrl, or
            #    duplicates a key we already keyed is UNKEYABLE — it can't take part in the
            #    checkoutUrl reconcile, but it is staff work and must never be dropped. Collect
            #    those into `unkeyed` and re-graft them onto the written products verbatim after
            #    the reconcile.
            snapshots = {k: _snapshot_from_row(r) for k, r in db.get_store_snapshot().items()}
            current = await asyncio.to_thread(
                github_publish._fetch_store,
                config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_STORE_JSON)
            current_by_key: dict[str, dict] = {}
            unkeyed: list = []
            for p in (current.get("products") or []):
                if (isinstance(p, dict) and p.get("checkoutUrl")
                        and p["checkoutUrl"] not in current_by_key):
                    current_by_key[p["checkoutUrl"]] = p
                else:
                    unkeyed.append(p)              # non-dict / no key / duplicate → carry through

            # 4. Whole-store three-way reconcile (pure), then re-append the unkeyable staff
            #    entries so a hand-added or malformed product is preserved on the next write
            #    (WR-06).
            result = store_sync.reconcile_store(snapshots, live_by_key, current_by_key)
            result["products"].extend(unkeyed)

            # 5. Commit FIRST, gated on change (D-06). This MUST precede the snapshot upsert
            #    loop: if sync_store raises (transient GitHub transport failure), execution
            #    never reaches the upsert below, so the durable snapshot stays behind the
            #    un-written store.json and the change is naturally re-detected + retried on the
            #    next cycle — instead of advancing the snapshot past a state store.json never
            #    reached and permanently masking the update as a "Jinxxy unchanged, staff edit
            #    wins" no-op (CR-01, 09-VERIFICATION truth #5, T-09-11-01).
            if result["changed"]:
                await github_publish.sync_store(result["products"])

            # 6. WR-03: advance the durable snapshot to live truth on EVERY successful sync —
            #    NOT only inside the changed branch. A no-change cycle where Jinxxy already
            #    matches a staff value still leaves a stale snapshot; if the snapshot isn't
            #    refreshed, a LATER staff edit on that field is misread as a both-changed
            #    conflict and reverted (breaks D-12). Runs AFTER the commit so a failed commit
            #    never advances it (see step 5).
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

            # 7. Snapshot removals ONLY on change (D-06), after a successful commit. `removed`
            #    is empty on a no-change cycle, and a removal only makes sense once the commit
            #    that dropped the product actually landed (removal-safety, T-09-11-03).
            if result["changed"]:
                for key in result["removed"]:
                    db.delete_store_snapshot(key)
        except Exception as exc:
            await self._record_sync_status(ok=False, product_count=None, error=str(exc))
            raise

        await self._record_sync_status(
            ok=True, product_count=len(result.get("products") or []), error=None)
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
        # LOGS ONLY (D-05) — a sync failure never reaches Discord. WR-02: wait a bounded cool-down
        # BEFORE restarting so a persistent outage doesn't tight-loop the restart, hammering both
        # the Jinxxy and GitHub APIs; then restart so the next cadence runs.
        log.exception("jinxxy: el poll de la tienda se cayó, reiniciando", exc_info=exc)
        await asyncio.sleep(_POLL_RETRY_COOLDOWN_S)
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
        except Exception:
            # WR-08: broadened from `(GitHubPublishError, JinxxyAPIError)` to `Exception` so ANY
            # sync failure — including a KeyError/TypeError from `map_product` on a malformed 2xx
            # detail (detail["name"]/["url"]/["base_price"]/["created_at"]) — follows the D-05 path
            # instead of escaping the handler and hanging the deferred interaction.
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
        # WR-07: Discord's attachment picker doesn't restrict content types, so `raws` can hold a
        # PDF/video/corrupt file (PIL raises UnidentifiedImageError) or a decompression bomb (PIL
        # raises DecompressionBombError) — neither a discord.HTTPException nor a GitHubPublishError.
        # Guard BROADLY (also OSError from a truncated file): without this the exception propagates
        # out of asyncio.to_thread, the deferred interaction hangs on "thinking…" and the D-05
        # one-ephemeral-signal contract breaks (T-09-10-01 DoS mitigation).
        try:
            media = await asyncio.to_thread(
                _optimize_attachments, raws, _slug_from_url(producto))
        except Exception:
            log.exception("jinxxy: no pude optimizar los adjuntos de /tienda medios")
            await interaction.followup.send(
                "Alguna imagen no se pudo procesar (¿es una imagen válida?).", ephemeral=True)
            return

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

    # ── /tienda editar (D-09 staff-owned `editor` credit) ───────────────────────────────
    # The one staff-owned metadata field /tienda medios never exposed. `editor` is seeded from
    # /me at creation and thereafter staff-owned (never re-sourced from live by the merge), so
    # this command is its authoritative WRITE path — finishing the "staff never edit store.json
    # by hand" contract (STORE-SYNC-02, GAP-1).
    _EDITOR_MAX_LEN = 100                              # the schema's plain-text `editor` cap

    @app_commands.command(
        name="editar",
        description="Asigna el editor (creador acreditado) de un producto de la tienda (staff)")
    @app_commands.describe(
        producto="Producto de la tienda (usa el autocompletar)",
        editor="Nombre del editor/creador a acreditar")
    async def editar(
        self,
        interaction: discord.Interaction,
        producto: str,
        editor: str,
    ):
        """Set a product's staff-owned ``editor`` (credited creator) from Discord (GAP-1).

        Order mirrors ``/tienda medios``: (1) staff gate FIRST (T-09-20) — a non-staff invoker
        gets "Sin permisos." before any work; (2) VALIDATE the editor string BEFORE defer or any
        transport (T-09-21) — strip it, reject empty-after-strip / over the 100-char cap / any
        control-or-newline char with an ephemeral message and NO commit; (3) defer; (4) commit via
        ``set_store_editor`` matched by ``checkoutUrl``; (5) confirm. A ``GitHubPublishError`` is
        logged and answered with a single ephemeral reply — never a public post (D-05/T-09-23).
        """
        # 1. Staff gate FIRST — before defer or any transport work (T-09-20).
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # 2. Validate the editor string BEFORE defer/transport (T-09-21). The raw value never
        #    reaches the commit message (T-09-22 lives in the transport); here we ensure it can't
        #    break the store.json structure or carry hidden control bytes.
        cleaned = (editor or "").strip()
        if (not cleaned or len(cleaned) > self._EDITOR_MAX_LEN
                or _has_control_or_format_char(cleaned)):
            await interaction.response.send_message(
                "Nombre de editor inválido (vacío, demasiado largo o con caracteres no permitidos).",
                ephemeral=True)
            return

        # 3. Defer (a cross-repo commit can exceed Discord's 3s ack window).
        await interaction.response.defer(ephemeral=True)

        # 4. Commit the editor-only change into the matched product (one atomic commit, 09-12).
        try:
            result = await github_publish.set_store_editor(producto, cleaned)
        except github_publish.GitHubPublishError:
            # D-05: errors go to logs ONLY; the one user-facing signal is this ephemeral reply
            # to the STAFF invoker — never a public post (T-09-23).
            log.exception("jinxxy: /tienda editar falló")
            await interaction.followup.send(
                "No pude actualizar el editor; revisa los logs.", ephemeral=True)
            return

        # 5. Confirm. WR-03: honor set_store_editor's no-op guard — when the editor already
        #    matched, nothing was committed and no rebuild is in flight, so don't claim one
        #    (mirrors /tienda sync's changed vs "Sin cambios." idiom).
        if result.get("committed"):
            msg = f"Editor actualizado a «{cleaned}» — la web tarda un par de minutos."
        else:
            msg = f"El editor ya era «{cleaned}»; no hubo cambios."
        await interaction.followup.send(msg, ephemeral=True)

    @editar.autocomplete("producto")
    async def _editar_producto_autocomplete(
            self, interaction: discord.Interaction, current: str):
        # Shares the medios product autocomplete: staff gate + snapshot read in _producto_choices
        # ([] for non-staff, T-09-20).
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

        # WR-09: honor this method's own "logged and skipped — never raised" contract. A
        # discord.Forbidden (no send permission — a subclass of HTTPException) or any other
        # HTTPException on the announce channel is COSMETIC: it must not hang the /tienda sync
        # ephemeral summary nor trigger a full poll restart-and-resync (T-09-10-03).
        try:
            await channel.send(embed=self._build_announce_embed(result))
        except discord.HTTPException:
            log.exception("jinxxy: no pude publicar el anuncio de la tienda")

    @staticmethod
    def _build_announce_embed(result: dict) -> discord.Embed:
        """English, engaging, visual store-news embed — the public conversion surface (GAP-2).

        This OVERRIDES D-05's Spanish-first for STORE announcements ONLY (the announce channel is
        public and the audience is now English). It is reached ONLY on a real change — ``_announce``
        still guards no-change to silence (D-06) and still swallows send errors to logs (D-05). The
        embed keeps brand red (``_BRAND_RED``) + a UTC timestamp and adds:

          * a store-page link to ``config.JINXXY_STORE_URL`` (also set as ``embed.url``),
          * each added/updated product rendered as ``[name](checkoutUrl)`` when the checkoutUrl
            passes ``store_sync.is_https_url`` (T-09-27), with the label stripped of markdown
            link-breaking chars ``[]()`` so a crafted name can't alter the link target (T-09-28),
          * a best-effort thumbnail from the first product (an ``added`` one preferred) whose
            ``images[0]`` is a site-relative ``/...`` path, composed against the trusted
            ``config.WEBSITE_BASE_URL`` constant (T-09-27) — omitted entirely when none has images.
        """
        products = [p for p in (result.get("products") or []) if isinstance(p, dict)]
        by_key = {p.get("checkoutUrl"): p for p in products}

        def _name(p, key):
            # English-first now (announce is English) → fall back to Spanish then the key.
            n = p.get("name") if isinstance(p, dict) else None
            if isinstance(n, dict):
                return n.get("en") or n.get("es") or key
            return n or key

        def _sanitize(label):
            # Strip markdown link-breaking chars so a crafted name can't break out of [label](url).
            return re.sub(r"[\[\]()]", "", str(label))

        def _render(keys):
            out = []
            for k in keys:
                p = by_key.get(k)
                if isinstance(p, dict):
                    label = _sanitize(_name(p, k))
                    url = p.get("checkoutUrl")
                    if store_sync.is_https_url(url):
                        out.append(f"• [{label}]({url})")
                    else:
                        out.append(f"• {label}")
                else:
                    # removed keys aren't in products → plain (sanitized) text, never a link
                    out.append(f"• {_sanitize(k)}")
            return out

        # CR-01: the headline must reflect what actually changed — an updated-only or
        # removed-only cycle must NOT claim "New on the Nocturna store". Only the presence
        # of an `added` product justifies the "new product" copy; everything else is the
        # change-agnostic "store updated" headline (the pre-09-13 behaviour, restored).
        added = result.get("added") or []
        updated = result.get("updated") or []
        if added:
            title = "New on the Nocturna store"
            description = "There's a new product on our webpage — make sure to check it out!"
        elif updated:
            title = "Nocturna store updated"
            description = "Some of our products just got updated — take a look!"
        else:
            title = "Nocturna store updated"
            description = "The store catalog just changed — take a look!"
        embed = discord.Embed(
            title=title,
            description=description,
            color=_BRAND_RED,
            url=config.JINXXY_STORE_URL,
        )
        embed.add_field(
            name="Store",
            value=f"[Browse the store]({config.JINXXY_STORE_URL})", inline=False)
        buckets = (("🆕 New", result.get("added") or []),
                   ("✏️ Updated", result.get("updated") or []),
                   ("🗑️ Removed", result.get("removed") or []))
        for label, keys in buckets:
            if keys:
                lines = _render(keys)
                # WR-02: each line can be a markdown link (`• [name](url)`) now — a hard
                # `[:1024]` slice could cut inside a `[label](url)` span and render a dangling
                # `[` / unterminated `(url` to the public channel. Truncate on a LINE boundary
                # (staying under Discord's 1024-char field cap) with an "...and N more" tail.
                out_lines: list[str] = []
                total_len = 0
                for i, line in enumerate(lines):
                    if total_len + len(line) + 1 > 1000:
                        out_lines.append(f"...and {len(lines) - i} more")
                        break
                    out_lines.append(line)
                    total_len += len(line) + 1
                embed.add_field(
                    name=f"{label} ({len(keys)})",
                    value="\n".join(out_lines), inline=False)

        # Best-effort thumbnail: prefer an added product, else an updated one, with a
        # site-relative image. WR-01: candidates are restricted to the CHANGED set
        # (added + updated) — never the full catalog — so an unrelated, unchanged product's
        # image can't be pulled into a "store updated" announcement it has nothing to do with.
        changed_keys = list(result.get("added") or []) + list(result.get("updated") or [])
        ordered = [by_key[k] for k in changed_keys if k in by_key]
        for p in ordered:
            images = p.get("images")
            if isinstance(images, list) and images:
                first = images[0]
                if isinstance(first, str) and first.startswith("/"):
                    embed.set_thumbnail(url=f"{config.WEBSITE_BASE_URL}{first}")
                    break

        embed.set_footer(text="Nocturna store")
        embed.timestamp = discord.utils.utcnow()
        return embed


async def setup(bot: commands.Bot):
    await bot.add_cog(JinxxyCog(bot))
