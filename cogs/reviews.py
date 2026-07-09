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

    # ── startup backfill / reconcile ─────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_ready(self):
        """Run the startup reconcile once (``on_ready`` can re-fire on reconnects)."""
        if self._backfilled:
            return
        self._backfilled = True
        try:
            await self._backfill()
        except Exception:
            log.exception("reviews startup backfill failed")

    async def _backfill(self):
        """Scan channel history after the reviews cursor and replay anything the bot missed
        while down — missed ✅ prompts, staff approvals, and 🌙 removals.

        The reviews cursor (separate from the gallery cursor) advances per message so a
        restart never re-scans the whole channel. Published-state during reconcile is derived
        from the 🟢 marker + the live ``reviews.json`` entries. Tolerates an empty channel and
        an empty/missing ``reviews.json``.
        """
        channel = self.bot.get_channel(config.REVIEWS_CHANNEL_ID) or \
            await self.bot.fetch_channel(config.REVIEWS_CHANNEL_ID)
        if channel is None:
            log.warning("reviews backfill: reviews channel %s not found",
                        config.REVIEWS_CHANNEL_ID)
            return

        cursor = db.get_reviews_cursor()
        after = discord.Object(id=cursor) if cursor else None
        entries = await self._fetch_entries()               # once for the whole scan

        scanned = 0
        async for message in channel.history(after=after, limit=None, oldest_first=True):
            try:
                await self._reconcile(message, entries)
            except Exception:
                log.exception("reviews backfill: reconcile failed for msg %s", message.id)
            db.set_reviews_cursor(message.id)                # advance even past a failed message
            scanned += 1
        log.info("reviews backfill: reconciled %d message(s) after cursor %s", scanned, cursor)

        # Inverse pass: history never yields DELETED messages, so a delete the bot missed
        # leaves its entry published forever — probe them explicitly.
        await self._reconcile_orphans(channel, entries)

    async def _reconcile_orphans(self, channel, entries):
        """Remove published entries whose Discord message no longer exists.

        ``channel.history()`` cannot surface deletions, so the forward scan alone never
        reconciles a message deleted while the bot was down (or whose live
        ``on_raw_message_delete`` failed). For every entry, fetch the message once per id:

        - ``discord.NotFound`` -> the message is gone -> ``remove_review(id)`` drops its entry.
        - ANY other error (rate limit, permissions, network) means "unknown", NOT "deleted" —
          the entry is left alone and logged, so a transient outage can never mass-remove the
          live reviews (T-07-06).

        Entries with a non-numeric/malformed id are skipped.
        """
        probed = set()
        for entry in entries or []:
            raw_id = (entry or {}).get("id")
            try:
                msg_id = int(raw_id)
            except (TypeError, ValueError):
                continue                                     # malformed id — never probe
            if msg_id in probed:
                continue
            probed.add(msg_id)
            try:
                await channel.fetch_message(msg_id)
            except discord.NotFound:
                log.info("reviews orphan reconcile: msg %s deleted -> removing its entry",
                         msg_id)
                try:
                    await github_publish.remove_review(msg_id)
                except Exception:
                    log.exception("reviews orphan reconcile: removal failed for msg %s",
                                  msg_id)
            except Exception:
                log.warning("reviews orphan reconcile: could not verify msg %s; "
                            "leaving its entry untouched", msg_id)

    async def _fetch_entries(self):
        """The live ``reviews.json`` array (for entry-derived published-state).

        Reuses the 07-02 transport's generic read path off the event loop; any failure
        degrades to ``[]`` so a startup with GitHub unreachable still adds prompts / falls
        back to the 🟢 marker rather than crashing the backfill.
        """
        try:
            return await asyncio.to_thread(
                github_publish._fetch_json,
                config.WEBSITE_REPO, config.WEBSITE_BRANCH, config.WEBSITE_REVIEWS_JSON)
        except Exception:
            log.exception("reviews backfill: could not fetch reviews.json; assuming []")
            return []

    async def _reconcile(self, message: discord.Message, entries=None):
        """Replay one history message into the correct state during backfill.

        Only plain client text reviews are managed. Bot messages are skipped in this plan
        (07-04 refines this to manage the cog's own review embeds). Dispatch (honoring the
        SAME staff gate as live operation): a staff 🌙 -> unpublish/dismiss; a staff ✅ on an
        unpublished review -> publish; a plain client review with no ✅ prompt -> add it. A
        review already published (🟢 marker or a matching ``reviews.json`` entry) is left alone.
        """
        if getattr(message.author, "bot", False):
            return                                           # bot post — not managed (07-04)
        _, text = _review_author_and_text(message)
        if not text:
            return                                           # no client text — nothing to manage

        # A staff 🌙 (removal/dismiss that arrived while down) takes priority over publish.
        if await self._reaction_by_staff(message, "🌙"):
            await self._unpublish(message)
            return

        if _is_published(message, entries):
            return                                           # already live — nothing to do

        # A staff ✅ approval we missed -> publish now.
        if await self._reaction_by_staff(message, "✅"):
            await self._publish(message)
            return

        # No ✅ prompt at all (we were down when it was posted) -> add the approve control.
        if not any(str(r.emoji) == "✅" for r in getattr(message, "reactions", [])):
            await message.add_reaction("✅")

    async def _resolve_member(self, guild, user_id):
        """Resolve a guild member with a REST fallback for cold caches.

        History/REST payloads carry plain users with no role data, and without the
        privileged members intent the guild member cache is essentially empty after a
        restart — so backfill role checks must be able to fetch the member explicitly.
        ``NotFound`` (left the guild) and any other API failure resolve to ``None``;
        callers treat that as "not staff" (fail closed).
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
        """True iff a staff member (not the bot) has reacted with ``emoji`` (T-07-03 gate).

        History messages carry reaction *counts*, not reactors, so the reactor list is
        fetched via ``reaction.users()`` and each non-bot user is role-checked against the
        guild — cache first, REST ``fetch_member`` on a cold cache — so a non-staff ✅/🌙
        during downtime can never trigger a publish/unpublish.
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


async def setup(bot: commands.Bot):
    await bot.add_cog(ReviewsCog(bot))
