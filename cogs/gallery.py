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
from discord import app_commands
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


# The exact D-14 bot filename shape lives in ONE place (WR-06): the transport module.
_BOT_FILE_RE = github_publish._BOT_FILE_RE


def _entry_message_id(entry):
    """The Discord message id encoded in a gallery entry's filename, or ``None``.

    Only the exact bot shape ``{YYYYMMDD}-{msgID}-{index}.webp`` (D-14) parses;
    sample/manually-committed entries (any other name) return ``None`` so the
    orphan reconcile can never touch them. Delegates to the transport's strict
    parser so there is exactly one filename grammar (WR-06).
    """
    raw = github_publish._entry_message_id(((entry or {}).get("file") or ""))
    return int(raw) if raw is not None else None


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
        target = message.id
        for entry in entries:
            if _entry_message_id(entry) == target:   # strict bot-shape parse only (WR-06)
                return True
    return False


class GalleryCog(commands.Cog):
    """Detects staff photo posts and publishes approved images to the live gallery."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._backfilled = False   # startup reconcile runs once (on_ready can re-fire)
        db.init_gallery_state()    # backfill-cursor table (D-20)

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

        try:
            channel = self.bot.get_channel(payload.channel_id) or \
                await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)  # not guaranteed cached
        except discord.HTTPException:
            # WR-04: message deleted between reaction and fetch, or perms changed — there
            # is no message to surface a ⚠️ on, so log loudly instead of dying silently.
            log.exception("gallery: could not fetch reacted message %s", payload.message_id)
            return
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

        # WR-03: only staff-AUTHORED posts are publishable — the same author gate that
        # on_message (✅ prompt) and the backfill reconcile already enforce. REST-fetched
        # messages carry a plain user, so resolve the member (CR-03) before the check;
        # unresolvable or non-staff authors fail closed (D-01).
        author = await self._resolve_member(
            getattr(message, "guild", None), getattr(message.author, "id", None))
        if author is None or not _is_staff(author):
            return                                          # community/bot post — not publishable

        images = _image_attachments(message)                # D-13: non-images skipped silently
        if not images:
            return

        # Match the shipped gallery.json date shape exactly: ISO 8601, millisecond
        # precision, 'Z' suffix (e.g. 2026-07-03T14:05:09.000Z).
        date = message.created_at.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        date = date.replace("+00:00", "Z")
        caption = _caption(message.content)                 # BOT-06/D-06 (omitted when empty)

        try:
            entries = []
            for index, attachment in enumerate(images, start=1):
                raw = await attachment.read()
                # Keep Pillow's CPU re-encode off the event loop (Anti-Pattern otherwise).
                webp, width, height = await asyncio.to_thread(optimize_to_webp, raw)
                filename = _build_filename(message.id, message.created_at, index)  # D-14
                entries.append((webp, width, height, filename, caption))
        except discord.HTTPException:
            # WR-04(a): CDN hiccup / expired attachment — nothing was committed, so this
            # is a real publish failure and must fire the D-19 retry UX, not die silently.
            log.exception("gallery: attachment download failed for msg %s", message.id)
            await self._surface_failure(message, "publicar")
            return

        try:
            result = await github_publish.publish_message(message.id, entries, date=date)
        except github_publish.GitHubPublishError:
            # Retries already exhausted inside the transport (D-18) -> surface it (D-19).
            # Do NOT add the 🟢 marker on failure; the ⚠️ + reply are the retry to-do.
            log.exception("gallery publish failed for discord msg %s", message.id)
            await self._surface_failure(message, "publicar")
            return

        count = result.get("count", len(entries)) if isinstance(result, dict) else len(entries)
        # D-11: activity_log row for the Overview "recent activity" list — additive, never
        # aborts the publish (mirrors cogs/presence.py::_store's try/except idiom).
        try:
            await asyncio.to_thread(
                db.log_activity, "gallery_published",
                f"Foto publicada en la galería (msg {message.id}) / "
                f"Gallery photo published (msg {message.id})")
        except Exception:
            log.exception("gallery: no pude registrar la actividad de publicación (msg %s)",
                          message.id)
        try:
            await message.add_reaction("🟢")                # persistent published marker (D-05)
            await message.add_reaction("🌙")                # visible unpublish control (05-05 UX):
            # the bot's own 🌙 never triggers anything (bot reactions are gated out
            # everywhere); it exists so staff can SEE the unpublish gesture.
            await self._clear_warning(message)              # drop a stale ⚠️ from a prior failure
            await message.reply(                            # auto-deleting confirmation (D-04)
                f"📸 Publiqué {count} foto{'s' if count != 1 else ''} en la galería — "
                "la web tarda un par de minutos en actualizarse.",
                delete_after=60,
            )
        except discord.HTTPException:
            # WR-04(b): the COMMIT SUCCEEDED — a failed 🟢/reply must not look like a
            # publish failure (no ⚠️). A lost 🟢 is harmless: the WR-02 commit-level
            # dedupe makes a re-✅ a clean republish, but it must reach the log.
            log.exception(
                "gallery: publish committed for msg %s but post-commit bookkeeping "
                "failed (🟢/🌙/reply may be missing)", message.id)

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
            try:
                result = await github_publish.remove_message(message.id)  # photos+entries, 1 commit
            except github_publish.GitHubPublishError:
                # Removal exhausted its retries (D-18) -> persistent surface (D-19). Leave
                # the 🟢 marker in place: the photos are still live, so it stays published.
                log.exception("gallery unpublish failed for discord msg %s", message.id)
                await self._surface_failure(message, "quitar")
                return
            count = result.get("count", 0) if isinstance(result, dict) else 0
            # D-11: activity_log row for the Overview "recent activity" list — additive,
            # never aborts the removal (mirrors cogs/presence.py::_store's try/except idiom).
            try:
                await asyncio.to_thread(
                    db.log_activity, "gallery_removed",
                    f"Foto quitada de la galería (msg {message.id}) / "
                    f"Gallery photo removed (msg {message.id})")
            except Exception:
                log.exception("gallery: no pude registrar la actividad de remoción (msg %s)",
                              message.id)
            try:
                await message.remove_reaction("🟢", self.bot.user)  # back to pending (D-09)
                await self._remove_own_reaction(message, "🌙")  # clear the visible control
                await self._clear_warning(message)          # drop a stale ⚠️ from a prior failure
                await message.reply(                        # mirrored auto-deleting feedback (D-09)
                    f"🌙 Quité {count} foto{'s' if count != 1 else ''} de la galería — "
                    "la web tarda un par de minutos en actualizarse.",
                    delete_after=60,
                )
            except discord.HTTPException:
                # WR-04(b): removal COMMITTED — a stale 🟢 the bot failed to clear makes
                # the message merely LOOK published; log loudly, never re-surface as a
                # removal failure (the photos are already gone from the site).
                log.exception(
                    "gallery: removal committed for msg %s but post-commit bookkeeping "
                    "failed (stale 🟢/🌙 may remain)", message.id)
        else:
            # Pending: clear the ✅ prompt so it won't be published; no commit (D-07).
            # Tolerant removal (WR-05): a NotFound on the absent prompt must not abort
            # the dismiss — the helper exists for exactly this.
            await self._remove_own_reaction(message, "✅")
            await self._remove_own_reaction(message, "🌙")  # in case a stale control lingers

    async def _remove_own_reaction(self, message: discord.Message, emoji: str):
        """Clear one of the bot's own reactions, tolerating its absence (05-05 UX).

        Legacy messages published before the visible 🌙 control existed carry 🟢 but no
        bot 🌙 — clearing the absent reaction raises ``NotFound``, which must never fail
        an unpublish/dismiss that already committed.
        """
        try:
            await message.remove_reaction(emoji, self.bot.user)
        except Exception:
            pass                                            # absent reaction — nothing to clear

    async def _surface_failure(self, message: discord.Message, verbo: str):
        """D-19 persistent-error UX: when github_publish exhausts its retries and raises,
        leave a NON-auto-deleting reply + a ⚠️ reaction on the message. The reply names
        the failure and the ⚠️ doubles as a retry to-do — staff recover by removing and
        re-adding ✅ (which re-enters ``_publish``). The 🟢 marker is never added on this
        path. ``github_publish`` already keeps the PAT/Authorization value out of the logs
        (T-05-04); the ``log.exception`` at the call site records only the msg id + trace.
        """
        try:
            await message.add_reaction("⚠️")               # impossible-to-miss retry to-do
        except Exception:
            log.exception("could not add ⚠️ marker to discord msg %s", message.id)
        try:
            await message.reply(                            # NO delete_after: this must persist
                f"⚠️ No pude {verbo} las fotos: GitHub falló tras varios intentos. "
                "Quita y vuelve a poner ✅ para reintentar."
            )
        except Exception:
            # WR-04: even the failure reply can fail (perms/deleted message) — the ⚠️ (or
            # at minimum this log line) is the remaining signal; never raise from here.
            log.exception("could not send failure reply for discord msg %s", message.id)

    async def _clear_warning(self, message: discord.Message):
        """Remove a stale ⚠️ retry marker on a later success so it doesn't linger (D-19).

        The common case is no prior ⚠️; ``remove_reaction`` on an absent reaction is
        tolerated so a clean publish/removal never errors on the clear.
        """
        try:
            await message.remove_reaction("⚠️", self.bot.user)
        except Exception:
            pass                                            # no prior ⚠️ — nothing to clear

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
        # Defensive diagnostics (05-05, live acceptance (c)): log entry + outcome so a
        # failed delete-unpublish is visible in journalctl instead of only discord.py's
        # generic "Ignoring exception in on_raw_message_delete".
        log.info("gallery delete event: msg %s deleted in photo channel -> reconciling",
                 payload.message_id)
        try:
            result = await github_publish.remove_message(payload.message_id)
        except Exception:
            log.exception("gallery delete-unpublish FAILED for msg %s "
                          "(entries left live; backfill orphan pass will heal on restart)",
                          payload.message_id)
            return
        log.info("gallery delete event: msg %s removal result: %s",
                 payload.message_id, result)

    # ── startup backfill / reconcile (D-20) ──────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        """Run the startup reconcile once (``on_ready`` can re-fire on reconnects)."""
        if self._backfilled:
            return
        self._backfilled = True
        try:
            await self._backfill()
        except Exception:
            log.exception("gallery startup backfill failed")

    async def _backfill(self):
        """Scan channel history after the persisted cursor and replay anything the bot
        missed while down — missed ✅ prompts, staff approvals, and 🌙 removals (D-20).

        The cursor advances per message (T-05-17) so a restart never re-scans the whole
        channel. Published-state during reconcile is derived from the 🟢 marker + the
        live gallery.json entries (D-14) — the entries guard against a duplicate publish
        if the bot crashed after committing but before adding 🟢. Tolerates an empty
        channel and an empty/missing gallery.json.
        """
        channel = self.bot.get_channel(config.PHOTO_CHANNEL_ID) or \
            await self.bot.fetch_channel(config.PHOTO_CHANNEL_ID)
        if channel is None:
            log.warning("gallery backfill: photo channel %s not found", config.PHOTO_CHANNEL_ID)
            return

        cursor = db.get_cursor()
        after = discord.Object(id=cursor) if cursor else None
        entries = await self._fetch_entries()               # once for the whole scan (D-14)

        scanned = 0
        async for message in channel.history(after=after, limit=None, oldest_first=True):
            try:
                await self._reconcile(message, entries)
            except Exception:
                log.exception("gallery backfill: reconcile failed for msg %s", message.id)
            db.set_cursor(message.id)                        # advance even past a failed message
            scanned += 1
        log.info("gallery backfill: reconciled %d message(s) after cursor %s", scanned, cursor)

        # Inverse pass (05-05 Fix A): history never yields DELETED messages, so a delete
        # the bot missed leaves its entries published forever — probe them explicitly.
        await self._reconcile_orphans(channel, entries)

    async def _reconcile_orphans(self, channel, entries):
        """Remove published entries whose Discord message no longer exists (D-10/D-20).

        ``channel.history()`` cannot surface deletions, so the forward scan alone never
        reconciles a message deleted while the bot was down (or whose live
        ``on_raw_message_delete`` failed). For every entry whose filename parses to the
        exact bot shape (``_entry_message_id``), fetch the message once per id:

        - ``discord.NotFound`` -> the message is gone -> ``remove_message(id)`` drops all
          of its files + entries in one commit (self-heals live orphans on restart).
        - ANY other error (rate limit, permissions, network) means "unknown", NOT
          "deleted" — the entry is left alone and logged, so a transient outage can
          never mass-remove the live gallery (T-05-11-adjacent hazard).

        Sample/manually-committed entries whose filename doesn't parse are skipped.
        """
        probed = set()
        for entry in entries or []:
            msg_id = _entry_message_id(entry)
            if msg_id is None or msg_id in probed:
                continue
            probed.add(msg_id)
            try:
                await channel.fetch_message(msg_id)
            except discord.NotFound:
                log.info("gallery orphan reconcile: msg %s deleted -> removing its photos",
                         msg_id)
                try:
                    await github_publish.remove_message(msg_id)
                except Exception:
                    log.exception("gallery orphan reconcile: removal failed for msg %s",
                                  msg_id)
            except Exception:
                log.warning("gallery orphan reconcile: could not verify msg %s; "
                            "leaving its entries untouched", msg_id)

    async def _fetch_entries(self):
        """The live gallery.json array (for entry-derived published-state, D-14).

        Reuses the 05-02 transport's read path off the event loop; any failure degrades
        to ``[]`` so a startup with GitHub unreachable still adds prompts / falls back to
        the 🟢 marker rather than crashing the backfill.
        """
        try:
            return await asyncio.to_thread(
                github_publish._fetch_gallery, config.WEBSITE_REPO, config.WEBSITE_BRANCH)
        except Exception:
            log.exception("gallery backfill: could not fetch gallery.json; assuming []")
            return []

    async def _reconcile(self, message: discord.Message, entries=None):
        """Replay one history message into the correct state during backfill (D-20).

        Only staff photo posts are managed. Dispatch (honoring the SAME staff gate as live
        operation, D-08): a staff 🌙 -> unpublish/dismiss; a staff ✅ on an unpublished
        message -> publish; a staff image post with no ✅ prompt at all -> add the prompt.
        A message already published (🟢 marker or a matching gallery.json entry, D-14) is
        left alone so the scan never double-publishes.
        """
        if not _image_attachments(message):
            return                                           # no photos — nothing to manage
        if getattr(message.author, "bot", False):
            return                                           # bot post — not managed
        if not _is_staff(message.author):
            # History/REST payloads carry the author as a plain user with NO role data;
            # with a cold member cache (no members intent, no chunking after a restart)
            # `_is_staff` would be False for EVERY author and the whole D-20 backfill
            # would silently no-op. Upgrade to a real Member before concluding
            # "community post" (CR-03). The image gate above keeps this REST fetch
            # off text-only messages.
            member = await self._resolve_member(
                message.guild, getattr(message.author, "id", None))
            if member is None or not _is_staff(member):
                return                                       # community post — not managed

        # A staff 🌙 (removal/dismiss that arrived while down) takes priority over publish.
        if await self._reaction_by_staff(message, "🌙"):
            await self._unpublish(message)
            return

        if _is_published(message, entries):
            return                                           # already live — nothing to do (D-14)

        # A staff ✅ approval we missed -> publish now.
        if await self._reaction_by_staff(message, "✅"):
            await self._publish(message)
            return

        # No ✅ prompt at all (we were down when it was posted) -> add the approve control.
        if not any(str(r.emoji) == "✅" for r in getattr(message, "reactions", [])):
            await message.add_reaction("✅")

    async def _resolve_member(self, guild, user_id):
        """Resolve a guild member with a REST fallback for cold caches (CR-03 / D-20).

        History/REST payloads carry plain users with no role data, and without the
        privileged members intent the guild member cache is essentially empty after a
        restart — so backfill role checks must be able to fetch the member explicitly.
        ``NotFound`` (left the guild) and any other API failure resolve to ``None``;
        callers treat that as "not staff" (fail closed, D-01).
        """
        if guild is None or user_id is None:
            return None
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.HTTPException:       # NotFound / Forbidden / transient API error
            return None

    async def _reaction_by_staff(self, message: discord.Message, emoji: str) -> bool:
        """True iff a staff member (not the bot) has reacted with ``emoji`` (D-08 gate).

        History messages carry reaction *counts*, not reactors, so the reactor list is
        fetched via ``reaction.users()`` and each non-bot user is role-checked against
        the guild — cache first, REST ``fetch_member`` on a cold cache (CR-03) — so a
        non-staff ✅/🌙 during downtime can never trigger a publish/unpublish.
        """
        for reaction in getattr(message, "reactions", []):
            if str(reaction.emoji) != emoji:
                continue
            users = getattr(reaction, "users", None)
            if users is None:
                continue
            async for user in users():
                if getattr(user, "bot", False):
                    continue
                member = await self._resolve_member(
                    message.guild, getattr(user, "id", None))
                if member is not None and _is_staff(member):
                    return True
        return False

    # ── D-11 editor credit + D-04 NSFW flag (EDIT-08) ─────────────────────────────────
    # A ✅ reaction carries no text (RESEARCH Open Q1 / Pitfall 7), so the editor credit is
    # captured by an ephemeral slug-autocomplete FOLLOW-UP after ✅ — reusing the Phase-9
    # `/tienda editar` slug-autocomplete + staff-gate pattern (09-12). The chosen slug is
    # validated against the live editors.json slug set (D-12 exact match) BEFORE the transport
    # write, so an unknown slug can never reach gallery.json.
    galeria = app_commands.Group(
        name="galeria",
        description="Gestión de la galería (staff)",
    )

    async def _fetch_editor_slugs(self) -> set:
        """The set of existing editor slugs from the website's ``editors.json`` (D-12).

        Reads the cross-repo ``editors.json`` array off the event loop via the transport's
        generic reader. Any failure degrades to an empty set so the affordance rejects every
        slug (fail closed) rather than crashing — a credit is never written against an
        unverifiable slug set.
        """
        try:
            editors = await asyncio.to_thread(
                github_publish._fetch_json,
                config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_EDITORS_JSON)
        except Exception:
            log.exception("gallery credit: could not fetch editors.json for slug validation")
            return set()
        return {e.get("slug") for e in editors
                if isinstance(e, dict) and e.get("slug")}

    async def _editor_choices(self, interaction: discord.Interaction, current: str):
        """Slug-autocomplete Choices — ``[]`` for a non-staff caller (T-10-06-01).

        The staff gate returns an empty list BEFORE any cross-repo read (an autocomplete
        callback cannot send an ephemeral reply). For staff, offers each existing editor slug
        (label == value == slug), substring-filtered by ``current``, capped at Discord's 25.
        """
        if not _is_staff(interaction.user):
            return []
        slugs = await self._fetch_editor_slugs()
        needle = (current or "").lower()
        choices = []
        for slug in sorted(slugs):
            if needle and needle not in slug.lower():
                continue
            choices.append(app_commands.Choice(name=slug, value=slug))
            if len(choices) >= 25:
                break
        return choices

    @galeria.command(
        name="creditar",
        description="Acredita al editor de una foto ya publicada (staff)")
    @app_commands.describe(
        mensaje="ID del mensaje de la foto ya publicada",
        editor="Slug del editor a acreditar (usa el autocompletar)",
        nsfw="Marca la foto como NSFW (se excluye de los perfiles de editores)")
    async def creditar(self, interaction: discord.Interaction, mensaje: str,
                       editor: str, nsfw: bool = False):
        """Ephemeral slug-autocomplete follow-up after ✅ (D-11). Delegates to the plainly
        testable :meth:`_do_creditar` (the registered Command is awkward to reach in tests)."""
        await self._do_creditar(interaction, mensaje, editor, nsfw)

    @creditar.autocomplete("editor")
    async def _creditar_editor_autocomplete(
            self, interaction: discord.Interaction, current: str):
        return await self._editor_choices(interaction, current)

    async def _do_creditar(self, interaction: discord.Interaction, mensaje: str,
                           editor: str, nsfw: bool):
        """Credit an already-published photo's editor slug into gallery.json (D-11/D-12/D-04).

        Order mirrors ``/tienda editar`` (09-12): (1) staff gate FIRST (T-10-06-01) — a
        non-staff invoker gets "Sin permisos." before any work; (2) parse the message id BEFORE
        defer; (3) defer, then VALIDATE the slug against the live editors.json slug set (D-12
        exact match, T-10-06-02) — an unknown slug is rejected with an ephemeral reply and NO
        write; (4) commit via ``set_gallery_editor`` (no-op-safe when the photo isn't published);
        (5) confirm. A ``GitHubPublishError`` is logged and answered with a single ephemeral
        reply — never a public post.
        """
        # 1. Staff gate FIRST — before defer or any transport work (T-10-06-01).
        if not _is_staff(interaction.user):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        # 2. Parse the message id BEFORE defer (cheap, no network).
        try:
            message_id = int(mensaje)
        except (TypeError, ValueError):
            await interaction.response.send_message(
                "ID de mensaje inválido (usa el ID numérico de la foto publicada).",
                ephemeral=True)
            return

        # 3. Defer (validating the slug reads editors.json cross-repo — can exceed the 3s ack).
        await interaction.response.defer(ephemeral=True)
        slugs = await self._fetch_editor_slugs()
        if editor not in slugs:                              # D-12: exact existing slug only
            await interaction.followup.send(
                f"«{editor}» no es un editor existente (usa el autocompletar).",
                ephemeral=True)
            return

        # 4. Commit the credit (+ optional NSFW flag) onto the message's entries.
        try:
            result = await github_publish.set_gallery_editor(
                message_id, editor=editor, nsfw=nsfw)
        except github_publish.GitHubPublishError:
            log.exception("gallery credit failed for discord msg %s", message_id)
            await interaction.followup.send(
                "No pude acreditar la foto; revisa los logs.", ephemeral=True)
            return

        # 5. Confirm (honor the transport's no-op guard for an unpublished/no-match message).
        if result.get("committed"):
            tag = " (NSFW)" if nsfw else ""
            await interaction.followup.send(
                f"Acredité «{editor}»{tag} en la foto — la web tarda un par de minutos.",
                ephemeral=True)
        else:
            await interaction.followup.send(
                "No encontré fotos publicadas para ese mensaje (¿ya está publicada?).",
                ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(GalleryCog(bot))
