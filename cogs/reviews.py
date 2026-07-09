"""Reviews publishing cog (Phase 7) — staff-approved client-review auto-publishing.

Watches the public reviews channel (``config.REVIEWS_CHANNEL_ID``): when a client types
a plain text review the cog adds a ✅ approve control (REV-02); a staff ✅ commits that
review to ``reviews.json`` in the website repo via the 07-02 cross-repo transport
(REV-03), a staff 🌙 unpublishes a live review or dismisses a pending one, and deleting a
published review auto-unpublishes it. Persistent-error UX (⚠️ + retry) and a startup
backfill/reconcile (over the reviews cursor) complete the cog.

Mirrors the repo's cog conventions (``cogs/forum.py``): a ``commands.Cog`` subclass with
``@commands.Cog.listener()`` handlers, ``import config``, ``log = logging.getLogger(__name__)``
and a module-level ``async def setup(bot)``. It is the reviews analog of ``cogs/gallery.py``
minus image optimization — the commit is a pure read-modify-write of ONE JSON file through
``core.github_publish.publish_review`` / ``remove_review``.

Author/text resolution is routed through a single seam (``_review_author_and_text``) so the
guided 2-button collection embed (07-04) can extend it for bot-posted review embeds without
a rewrite; in this plan the seam simply reads a plain client message's own display name + text.
"""

import asyncio
import logging
from datetime import timezone

import discord
from discord.ext import commands

import config
from core import db, github_publish

log = logging.getLogger(__name__)


# ── pure helpers (import without a running bot; unit-proven in test_reviews_cog) ──
def _is_staff(member) -> bool:
    """True iff the member holds a configured reviews-staff role (trust boundary, T-07-03).

    Reviews reuse the gallery staff roles by default (``REVIEWS_STAFF_ROLE_IDS`` falls back
    to ``GALLERY_STAFF_ROLE_IDS`` when unset). A bot or a role-less member is never staff.
    """
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(role_ids & set(config.REVIEWS_STAFF_ROLE_IDS))


def _review_author_and_text(message):
    """Resolve ``(author, text)`` for a review message — the extension SEAM (07-04).

    For a plain client message the author is the message author's own display name (they
    typed publicly) and the text is the stripped message content. Whitespace-only/empty
    content returns ``(None, "")`` so the caller skips it. 07-04 extends this to also read
    the bot's own review embeds (anonymous → ``author = None``); the transport stays dumb
    about identity and writes whatever author it is handed (``author: null`` for anonymous).
    """
    text = (getattr(message, "content", "") or "").strip()
    if not text:
        return (None, "")
    return (message.author.display_name, text)


def _is_published(message, entries=None) -> bool:
    """True iff the review is already published — Discord-native derived state.

    Published when the message carries the bot's own 🟢 marker reaction, OR (during startup
    reconcile, where ``entries`` is the live ``reviews.json``) when an entry's ``id`` equals
    ``str(message.id)``. Reviews key directly by the Discord message id (no filename regex,
    unlike the gallery) — the exact string match means a snowflake sharing a prefix
    (``9876543210`` vs ``987654321``) cannot collide. No per-message DB row is needed.
    """
    if any(str(r.emoji) == "🟢" and getattr(r, "me", False)
           for r in getattr(message, "reactions", [])):
        return True
    if entries:
        target = str(message.id)
        for entry in entries:
            if str(entry.get("id")) == target:
                return True
    return False


class ReviewsCog(commands.Cog):
    """Detects plain client reviews and publishes staff-approved ones to the live site."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._backfilled = False   # startup reconcile runs once (on_ready can re-fire)
        db.init_reviews_state()    # backfill-cursor table (separate from gallery_state)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Detection + ✅ approve control (REV-02): a plain client text review in the reviews
        # channel gets the pending prompt. Unlike the gallery, the AUTHOR is NOT gated on
        # staff — a review comes from a client. Bot messages and empty-text posts are ignored.
        if message.channel.id != config.REVIEWS_CHANNEL_ID or message.author.bot:
            return
        _, text = _review_author_and_text(message)
        if not text:
            return                                          # empty/whitespace-only — ignore
        await message.add_reaction("✅")                    # the approve control (REV-02)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        # RAW event: works even when the message isn't cached (post-restart / backfill). The
        # role gate on payload.member is the trust boundary in the public channel — a
        # non-staff or bot reaction can never trigger a publish (T-07-03).
        if payload.channel_id != config.REVIEWS_CHANNEL_ID:
            return
        if payload.member is None or payload.member.bot:    # member present for guild reactions
            return
        if not _is_staff(payload.member):                   # T-07-03 staff trust gate
            return
        emoji = str(payload.emoji)
        if emoji not in ("✅", "🌙"):                        # ✅ publishes; 🌙 unpublishes/dismisses
            return

        try:
            channel = self.bot.get_channel(payload.channel_id) or \
                await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)  # not guaranteed cached
        except discord.HTTPException:
            # Message deleted between reaction and fetch, or perms changed — no message to
            # surface a ⚠️ on, so log loudly instead of dying silently.
            log.exception("reviews: could not fetch reacted message %s", payload.message_id)
            return
        if emoji == "✅":
            await self._publish(message)
        else:                                               # 🌙 removal / dismiss
            await self._unpublish(message)

    async def _publish(self, message: discord.Message):
        """Commit the approved review to ``reviews.json`` in ONE commit (REV-03).

        Idempotent: a message already carrying the bot's 🟢 marker is skipped, so a second
        ✅ never double-publishes. Author/text come from the seam; empty text is skipped.
        """
        if any(str(r.emoji) == "🟢" and r.me for r in message.reactions):
            return                                          # already published

        author, text = _review_author_and_text(message)
        if not text:
            return                                          # nothing to publish

        # Match the shipped reviews.json date shape: ISO 8601, millisecond precision, 'Z'.
        date = message.created_at.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        date = date.replace("+00:00", "Z")
        entry = {"id": str(message.id), "author": author, "text": text, "date": date}

        try:
            await github_publish.publish_review(entry)
        except github_publish.GitHubPublishError:
            # Retries already exhausted inside the transport -> surface it (⚠️ + reply). Do
            # NOT add the 🟢 marker on failure; the ⚠️ + reply are the retry to-do.
            log.exception("reviews publish failed for discord msg %s", message.id)
            await self._surface_failure(message, "publicar la reseña")
            return

        try:
            await message.add_reaction("🟢")                # persistent published marker
            await message.add_reaction("🌙")                # visible unpublish control
            await self._clear_warning(message)              # drop a stale ⚠️ from a prior failure
            await message.reply(                            # auto-deleting confirmation
                "🟢 Publiqué la reseña — la web tarda un par de minutos en actualizarse.",
                delete_after=60,
            )
        except discord.HTTPException:
            # The COMMIT SUCCEEDED — a failed 🟢/reply must not look like a publish failure
            # (no ⚠️). A lost 🟢 is harmless: a re-✅ is a clean republish (id dedupe).
            log.exception(
                "reviews: publish committed for msg %s but post-commit bookkeeping "
                "failed (🟢/🌙/reply may be missing)", message.id)

    async def _unpublish(self, message: discord.Message):
        """🌙 removal (published) or dismiss (pending) — the safe counterpart to publish.

        Published (has the bot's 🟢 marker): remove the entry from ``reviews.json`` in ONE
        commit, clear the 🟢 marker so the message returns to pending — a later ✅ republishes
        it — and send a mirrored ``delete_after`` reply. Pending (never published — no 🟢):
        dismiss by clearing the bot's own ✅ prompt so it can't be published; commit NOTHING.
        """
        if _is_published(message):
            try:
                await github_publish.remove_review(message.id)  # single reviews.json commit
            except github_publish.GitHubPublishError:
                # Removal exhausted its retries -> persistent surface. Leave the 🟢 marker:
                # the review is still live, so it stays published.
                log.exception("reviews unpublish failed for discord msg %s", message.id)
                await self._surface_failure(message, "quitar la reseña")
                return
            try:
                await message.remove_reaction("🟢", self.bot.user)  # back to pending
                await self._remove_own_reaction(message, "🌙")  # clear the visible control
                await self._clear_warning(message)          # drop a stale ⚠️ from a prior failure
                await message.reply(                        # mirrored auto-deleting feedback
                    "🌙 Quité la reseña — la web tarda un par de minutos en actualizarse.",
                    delete_after=60,
                )
            except discord.HTTPException:
                # Removal COMMITTED — a stale 🟢 the bot failed to clear makes the message
                # merely LOOK published; log loudly, never re-surface as a removal failure.
                log.exception(
                    "reviews: removal committed for msg %s but post-commit bookkeeping "
                    "failed (stale 🟢/🌙 may remain)", message.id)
        else:
            # Pending: clear the ✅ prompt so it won't be published; no commit. Tolerant
            # removal: a NotFound on the absent prompt must not abort the dismiss.
            await self._remove_own_reaction(message, "✅")
            await self._remove_own_reaction(message, "🌙")  # in case a stale control lingers

    async def _remove_own_reaction(self, message: discord.Message, emoji: str):
        """Clear one of the bot's own reactions, tolerating its absence.

        Legacy/pending messages may lack a bot 🌙 — clearing the absent reaction raises
        ``NotFound``, which must never fail an unpublish/dismiss that already committed.
        """
        try:
            await message.remove_reaction(emoji, self.bot.user)
        except Exception:
            pass                                            # absent reaction — nothing to clear

    async def _surface_failure(self, message: discord.Message, verbo: str):
        """Persistent-error UX: when github_publish exhausts its retries and raises, leave a
        NON-auto-deleting reply + a ⚠️ reaction on the message. The reply names the failure
        and the ⚠️ doubles as a retry to-do — staff recover by removing and re-adding ✅
        (which re-enters ``_publish``). The 🟢 marker is never added on this path. The PAT is
        already kept out of the logs by ``github_publish``; only the msg id + trace are logged.
        """
        try:
            await message.add_reaction("⚠️")               # impossible-to-miss retry to-do
        except Exception:
            log.exception("could not add ⚠️ marker to discord msg %s", message.id)
        try:
            await message.reply(                            # NO delete_after: this must persist
                f"⚠️ No pude {verbo}: GitHub falló tras varios intentos. "
                "Quita y vuelve a poner ✅ para reintentar."
            )
        except Exception:
            # Even the failure reply can fail (perms/deleted message) — the ⚠️ (or at minimum
            # this log line) is the remaining signal; never raise from here.
            log.exception("could not send failure reply for discord msg %s", message.id)

    async def _clear_warning(self, message: discord.Message):
        """Remove a stale ⚠️ retry marker on a later success so it doesn't linger.

        The common case is no prior ⚠️; ``remove_reaction`` on an absent reaction is
        tolerated so a clean publish/removal never errors on the clear.
        """
        try:
            await message.remove_reaction("⚠️", self.bot.user)
        except Exception:
            pass                                            # no prior ⚠️ — nothing to clear

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        """Deleting a published review auto-unpublishes its entry.

        The channel is the source of truth: a deleted review message drops its
        ``reviews.json`` entry. ``remove_review`` is keyed by the message id and is a safe
        no-op when nothing was published, so this never creates an empty commit.
        """
        if payload.channel_id != config.REVIEWS_CHANNEL_ID:
            return
        # Defensive diagnostics: log entry + outcome so a failed delete-unpublish is visible
        # in journalctl instead of only discord.py's generic "Ignoring exception ...".
        log.info("reviews delete event: msg %s deleted in reviews channel -> reconciling",
                 payload.message_id)
        try:
            result = await github_publish.remove_review(payload.message_id)
        except Exception:
            log.exception("reviews delete-unpublish FAILED for msg %s "
                          "(entry left live; backfill orphan pass will heal on restart)",
                          payload.message_id)
            return
        log.info("reviews delete event: msg %s removal result: %s",
                 payload.message_id, result)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReviewsCog(bot))
