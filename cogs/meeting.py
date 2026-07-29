"""cogs/meeting.py — Grabación, transcripción y resumen de reuniones de voz.

Flujo:
  /reunion grabar [tema]  → el bot entra al canal de voz y graba una pista por persona
                            (descifrando DAVE en el camino; ver dave_voice.py).
  /reunion parar          → transcribe (faster-whisper), fusiona por tiempo, detecta los
                            "toma nota" y genera el acta con un LLM local (Ollama),
                            publicándola como un post en el foro de reuniones.
  /reunion nota <texto>   → añade una nota manual; si hay reunión activa, va al acta.

El "toma nota" por VOZ se detecta sobre la transcripción al final (no en vivo).
El "toma nota" por TEXTO (comando o mención) es instantáneo.
"""
import asyncio
import io
import json
import logging
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, voice_recv

import config
from core import db, summarizer, transcription
from core.dave_voice import DaveVoiceRecorder

log = logging.getLogger(__name__)

EMBED_COLOR = 0x7B2FBE

# Frases que marcan una nota explícita dentro de la transcripción o un mensaje.
_NOTE_TRIGGER = re.compile(
    r"\b(?:toma|tomen|tom[aá])\s+nota(?:\s+de(?:\s+esto)?)?\s*[:,]?\s*"
    r"|\banota(?:r|n)?(?:\s+(?:esto|que))?\s*[:,]?\s*"
    r"|\bap[uú]nta(?:r|n)?(?:\s+(?:esto|que))?\s*[:,]?\s*",
    re.IGNORECASE,
)


def _fmt_ts(seconds: float) -> str:
    """Segundos → 'mm:ss'."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _extract_note(text: str) -> str | None:
    """Si el texto contiene un disparador de nota, devuelve lo que va después."""
    m = _NOTE_TRIGGER.search(text)
    if not m:
        return None
    note = text[m.end():].strip(" .,:;-—\n")
    return note or None


# ── Estado de una reunión en curso ───────────────────────────────────────────────
class MeetingSession:
    def __init__(self, vc, voice_channel, text_channel, started_by, out_dir: Path, tema: str = ""):
        self.vc = vc
        self.voice_channel = voice_channel
        self.text_channel = text_channel
        self.started_by = started_by
        self.out_dir = out_dir
        self.tema = tema
        self.recorder = DaveVoiceRecorder(out_dir)
        self.started_at = datetime.now()
        self.ended_at: datetime | None = None
        self.attendees: list[str] = []
        self.text_notes: list[tuple[str, str, str]] = []  # (hora, autor, texto)


# ── Cog ──────────────────────────────────────────────────────────────────────────
class MeetingCog(
    commands.GroupCog,
    name="Meeting",
    group_name="reunion",
    group_description="Graba reuniones de voz y genera actas con IA local",
):
    """Graba reuniones de voz y genera actas con IA local."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, MeetingSession] = {}  # guild_id -> sesión activa
        self._backfilled = False
        db.init_meetings()
        config.RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # ── /reunion grabar ──────────────────────────────────────────────────────────
    @app_commands.command(name="grabar", description="Entra al canal de voz y empieza a grabar la reunión")
    @app_commands.describe(tema="Tema de la reunión (opcional; se usa como título del acta)")
    async def grabar(self, interaction: discord.Interaction, tema: str = ""):
        if interaction.guild is None:
            await interaction.response.send_message("Esto solo funciona en un servidor.", ephemeral=True)
            return

        voice_state = interaction.user.voice
        if not voice_state or not voice_state.channel:
            await interaction.response.send_message(
                "❌ Tienes que estar en un canal de voz para que pueda grabar.", ephemeral=True
            )
            return

        if interaction.guild.id in self.sessions:
            await interaction.response.send_message(
                "⚠️ Ya hay una grabación en curso. Usa `/reunion parar` para terminarla.", ephemeral=True
            )
            return

        channel = voice_state.channel
        await interaction.response.defer()

        # Conectar (o moverse) usando el cliente de voz que sabe recibir audio.
        vc = interaction.guild.voice_client
        try:
            if vc and not isinstance(vc, voice_recv.VoiceRecvClient):
                await vc.disconnect(force=True)
                vc = None
            if vc is None:
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
            elif vc.channel != channel:
                await vc.move_to(channel)
        except discord.ClientException as e:
            await interaction.followup.send(f"❌ No pude conectarme al canal de voz: {e}")
            return

        out_dir = config.RECORDINGS_DIR / f"{interaction.guild.id}_{int(time.time())}"
        out_dir.mkdir(parents=True, exist_ok=True)

        session = MeetingSession(vc, channel, interaction.channel, interaction.user, out_dir, tema.strip())
        self.sessions[interaction.guild.id] = session
        vc.listen(session.recorder)

        log.info("Grabación iniciada en %s por %s", channel.name, interaction.user)
        await interaction.followup.send(
            f"🔴 **Grabando** en **{channel.name}**.\n"
            f"Di *“CachoraBot, toma nota de…”* para apuntar algo, o usa `/reunion nota`.\n"
            f"Cuando terminen, usa `/reunion parar`."
        )

    # ── /reunion parar ───────────────────────────────────────────────────────────
    @app_commands.command(name="parar", description="Detiene la grabación y genera el acta de la reunión")
    async def parar(self, interaction: discord.Interaction):
        guild = interaction.guild
        session = self.sessions.pop(guild.id, None) if guild else None
        if session is None:
            await interaction.response.send_message("No hay ninguna grabación en curso.", ephemeral=True)
            return

        await interaction.response.send_message(
            "⏏️ Grabación detenida. ⏳ Transcribiendo y redactando el acta… "
            "(esto puede tardar unos minutos, te aviso aquí cuando esté)."
        )
        await self._teardown(session)
        asyncio.create_task(self._process_meeting(session))

    async def _teardown(self, session: MeetingSession):
        """Detiene la captura, cierra los WAV y desconecta del canal de voz."""
        bot_ids = {
            member.id
            for member in session.voice_channel.members
            if member.bot
        }
        member_names = [
            member.display_name
            for member in session.voice_channel.members
            if not member.bot
        ]
        speaker_names = [
            user["name"]
            for user_id, user in session.recorder.users.items()
            if user_id not in bot_ids and user.get("name")
        ]
        session.attendees = list(dict.fromkeys(member_names + speaker_names))
        session.ended_at = datetime.now()
        try:
            session.vc.stop_listening()
        except Exception:
            pass
        session.recorder.cleanup()
        try:
            await session.vc.disconnect()
        except Exception:
            pass

    # ── Auto-parar cuando el canal de voz queda vacío ────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if member.bot or member.guild is None:
            return
        session = self.sessions.get(member.guild.id)
        if session is None:
            return
        # Solo reaccionar si alguien SALIÓ de nuestro canal grabado
        if before.channel != session.voice_channel or after.channel == session.voice_channel:
            return
        if any(not m.bot for m in session.voice_channel.members):
            return  # todavía queda gente en el canal

        session = self.sessions.pop(member.guild.id, None)
        if session is None:
            return  # /parar se adelantó
        log.info("Canal de voz vacío → auto-parando grabación")
        await self._teardown(session)
        try:
            await session.text_channel.send(
                "👋 Todos salieron del canal — detuve la grabación y estoy generando el acta…"
            )
        except discord.HTTPException:
            pass
        asyncio.create_task(self._process_meeting(session))

    async def _process_meeting(self, session: MeetingSession):
        """Transcribe, fusiona, detecta notas y publica el acta. Limpia el audio al final."""
        try:
            # 1) Transcribir cada pista (bloqueante → en hilo aparte, una a la vez)
            segments: list[tuple[float, float, str, str]] = []  # (inicio, fin, hablante, texto)
            for u in session.recorder.users.values():
                try:
                    segs = await asyncio.to_thread(transcription.transcribe, u["path"])
                except Exception as e:
                    log.error("Error transcribiendo %s: %s", u["path"].name, e)
                    continue
                for start, end, text in segs:
                    segments.append((start, end, u["name"], text))

            if not segments and not session.text_notes:
                await session.text_channel.send("🔇 No se captó audio en la reunión (¿nadie habló?).")
                return

            segments.sort(key=lambda s: s[0])

            # 2) Transcripción legible con hablantes
            transcript = "\n".join(
                f"[{_fmt_ts(s)}] **{name}**: {text}" for s, _e, name, text in segments
            )

            # 3) Notas ESCRITAS (comando/mención): exactas. Las HABLADAS ("toma nota")
            #    las extrae el LLM dentro del acta (idea completa, aunque haya pausas).
            notes = [f"[{hora}] {autor}: {texto}" for hora, autor, texto in session.text_notes]

            # 4) Resumen con el LLM local (si Ollama está disponible)
            summary = ""
            if transcript:
                try:
                    summary = await summarizer.summarize(transcript)
                except Exception as e:
                    log.error("Error al resumir con Ollama: %s", e)
                    summary = "⚠️ *No se pudo generar el resumen (¿Ollama apagado?). La transcripción va adjunta.*"

            # 5) Publicar el acta
            await self._publish(session, summary, notes, transcript)

        except Exception as e:
            log.exception("Error procesando la reunión: %s", e)
            try:
                await session.text_channel.send(f"❌ Error al procesar la reunión: {e}")
            except Exception:
                pass
        finally:
            shutil.rmtree(session.out_dir, ignore_errors=True)

    async def _publish(self, session: MeetingSession, summary: str, notes: list[str], transcript: str):
        """Crea un post en el foro de reuniones con el acta + transcripción adjunta.

        Si el foro no está configurado o falla, publica en el canal donde se usó /parar.
        """
        fecha = session.started_at.strftime("%d/%m/%Y %H:%M")
        title = f"📝 {fecha} — {session.tema or session.voice_channel.name}"

        embed = discord.Embed(
            title=title[:256],
            description=(summary or "*Sin resumen.*")[:4096],
            color=EMBED_COLOR,
        )
        if notes:
            embed.add_field(name="📝 Notas escritas", value="\n".join(f"• {n}" for n in notes)[:1024], inline=False)
        embed.set_footer(text="Transcripción completa adjunta")

        # Acta completa en Markdown (nada se pierde aunque el embed recorte)
        md = [f"# {title}\n"]
        if summary:
            md.append(summary + "\n")
        if notes:
            md.append("## 📝 Notas escritas\n" + "\n".join(f"- {n}" for n in notes) + "\n")
        md.append("## 📄 Transcripción\n" + (transcript or "*(vacía)*"))
        md_bytes = "\n".join(md).encode("utf-8")
        fname = f"acta_{session.started_at.strftime('%Y%m%d_%H%M')}.md"

        def _md_file() -> discord.File:  # un File se consume al enviarse: uno por intento
            return discord.File(io.BytesIO(md_bytes), filename=fname)

        # Publicar como un post nuevo en el foro de reuniones
        forum = self.bot.get_channel(config.MEETINGS_FORUM_ID)
        if isinstance(forum, discord.ForumChannel):
            try:
                created = await forum.create_thread(name=title[:100], embed=embed, file=_md_file())
            except discord.HTTPException as e:
                log.error("No se pudo publicar el acta en el foro: %s", e)
            else:
                try:
                    await asyncio.to_thread(
                        db.insert_meeting,
                        tema=session.tema,
                        started_at=session.started_at.isoformat(),
                        ended_at=(
                            session.ended_at.isoformat()
                            if session.ended_at is not None
                            else None
                        ),
                        attendees=session.attendees,
                        notes=notes,
                        transcript=transcript,
                        summary=summary,
                        thread_id=created.thread.id,
                        starter_message_id=created.message.id,
                    )
                except Exception:
                    log.exception(
                        "meeting: no pude persistir el acta publicada en foro (%s)",
                        title,
                    )
                if session.text_channel and session.text_channel.id != created.thread.id:
                    try:
                        await session.text_channel.send(
                            f"📋 Acta publicada en el foro: {created.thread.mention}"
                        )
                    except discord.HTTPException:
                        log.exception(
                            "meeting: no pude anunciar el acta publicada (%s)",
                            title,
                        )
                # D-11: activity_log row for the Overview "recent activity" list — additive,
                # never aborts the post (mirrors cogs/presence.py::_store's try/except idiom).
                try:
                    await asyncio.to_thread(
                        db.log_activity, "meeting_posted",
                        f"Acta de reunión publicada: {title} / Meeting minutes posted: {title}")
                except Exception:
                    log.exception("meeting: no pude registrar la actividad de publicación (%s)",
                                  title)
                return

        # Fallback: publicar en el canal donde se usó /parar
        await session.text_channel.send(embed=embed, file=_md_file())
        try:
            await asyncio.to_thread(
                db.insert_meeting,
                tema=session.tema,
                started_at=session.started_at.isoformat(),
                ended_at=(
                    session.ended_at.isoformat()
                    if session.ended_at is not None
                    else None
                ),
                attendees=session.attendees,
                notes=notes,
                transcript=transcript,
                summary=summary,
                thread_id=None,
                starter_message_id=None,
            )
        except Exception:
            log.exception(
                "meeting: no pude persistir el acta publicada en canal (%s)",
                title,
            )

    async def _republish(
        self, meeting_id: int, actor_name: str | None = None
    ) -> dict:
        """Edit the stored forum starter embed without replacing its transcript."""
        row = await asyncio.to_thread(db.get_meeting, meeting_id)
        if (
            row is None
            or row["thread_id"] is None
            or row["starter_message_id"] is None
        ):
            raise RuntimeError(
                "esta reunión no tiene una publicación en el foro · "
                "no forum post to edit"
            )

        channel = self.bot.get_channel(row["thread_id"])
        if channel is None:
            channel = await self.bot.fetch_channel(row["thread_id"])
        if not isinstance(channel, discord.Thread):
            raise RuntimeError("el hilo ya no existe · thread no longer exists")

        started_at = str(row["started_at"])
        try:
            fecha = datetime.fromisoformat(
                started_at.replace("Z", "+00:00")
            ).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            fecha = started_at
        title = f"📝 {fecha} — {row['tema']}"
        try:
            notes = json.loads(row["notes_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            notes = []

        embed = discord.Embed(
            title=title[:256],
            description=(row["summary"] or "*Sin resumen.*")[:4096],
            color=EMBED_COLOR,
        )
        if notes:
            embed.add_field(
                name="📝 Notas escritas",
                value="\n".join(f"• {note}" for note in notes)[:1024],
                inline=False,
            )
        embed.set_footer(text="Transcripción completa adjunta")

        was_archived = channel.archived
        if was_archived:
            await channel.edit(archived=False)
        try:
            partial = channel.get_partial_message(row["starter_message_id"])
            try:
                await partial.edit(embed=embed)
            except discord.NotFound as exc:
                raise RuntimeError(
                    "el mensaje ya no existe · message no longer exists"
                ) from exc
        finally:
            if was_archived:
                await channel.edit(archived=True)

        actor = actor_name or "desconocido"
        await asyncio.to_thread(
            db.log_activity,
            "meeting_republished",
            f"Acta editada por {actor}: {row['tema']} / "
            f"Meeting minutes edited by {actor}: {row['tema']}",
        )
        return {"ok": True}

    @commands.Cog.listener()
    async def on_ready(self):
        """Import historical forum meetings once per process startup."""
        if self._backfilled:
            return
        self._backfilled = True
        try:
            await self._backfill_meetings()
        except Exception:
            log.exception("meeting startup backfill failed")

    async def _backfill_meetings(self):
        """Best-effort import of active and archived meeting forum threads."""
        forum = self.bot.get_channel(config.MEETINGS_FORUM_ID)
        if forum is None:
            forum = await self.bot.fetch_channel(config.MEETINGS_FORUM_ID)
        if not isinstance(forum, discord.ForumChannel):
            log.warning(
                "meeting backfill: forum channel %s not found",
                config.MEETINGS_FORUM_ID,
            )
            return

        threads = list(forum.threads)
        async for archived_thread in forum.archived_threads(limit=None):
            threads.append(archived_thread)

        imported = 0
        for thread in threads:
            try:
                existing = await asyncio.to_thread(
                    db.get_meeting_by_thread_id, thread.id
                )
                if existing is not None:
                    continue

                starter = getattr(thread, "starter_message", None)
                if starter is None:
                    try:
                        starter = await thread.fetch_message(thread.id)
                    except discord.HTTPException:
                        log.exception(
                            "meeting backfill: starter message unavailable for thread %s",
                            thread.id,
                        )

                summary = ""
                transcript = None
                starter_message_id = thread.id
                if starter is not None:
                    starter_message_id = starter.id
                    if starter.embeds:
                        summary = starter.embeds[0].description or ""
                    attachment = next(
                        (
                            item
                            for item in starter.attachments
                            if item.filename.lower().endswith(".md")
                        ),
                        None,
                    )
                    if attachment is not None:
                        try:
                            raw = await attachment.read()
                            transcript = raw.decode("utf-8")
                        except Exception:
                            log.exception(
                                "meeting backfill: transcript unavailable for thread %s",
                                thread.id,
                            )

                created_at = thread.created_at
                started_at = (
                    created_at.isoformat()
                    if hasattr(created_at, "isoformat")
                    else str(created_at)
                )
                await asyncio.to_thread(
                    db.insert_meeting,
                    tema=thread.name,
                    started_at=started_at,
                    ended_at=None,
                    attendees=[],
                    notes=[],
                    transcript=transcript,
                    summary=summary,
                    thread_id=thread.id,
                    starter_message_id=starter_message_id,
                )
                imported += 1
            except Exception:
                log.exception(
                    "meeting backfill: import failed for thread %s",
                    getattr(thread, "id", "?"),
                )
        log.info("meeting backfill: imported %d meeting(s)", imported)

    # ── /reunion nota (texto, instantáneo) ───────────────────────────────────────
    @app_commands.command(name="nota", description="Añade una nota; si hay reunión activa, va al acta")
    @app_commands.describe(texto="Lo que quieres apuntar")
    async def nota(self, interaction: discord.Interaction, texto: str):
        texto = texto.strip()
        if not texto:
            await interaction.response.send_message("❌ La nota está vacía.", ephemeral=True)
            return
        en_reunion = self._add_note(interaction.guild, interaction.user.display_name, texto)
        sufijo = " (se incluirá en el acta)" if en_reunion else ""
        await interaction.response.send_message(f"📝 Anotado{sufijo}.", ephemeral=True)

    # ── Mención de texto: "@CachoraBot toma nota de ..." ─────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.bot.user or self.bot.user not in message.mentions:
            return
        note = _extract_note(message.content)
        if not note:
            return
        en_reunion = self._add_note(message.guild, message.author.display_name, note)
        sufijo = " (irá al acta)" if en_reunion else ""
        try:
            await message.reply(f"📝 Anotado{sufijo}.", mention_author=False)
        except discord.HTTPException:
            pass

    def _add_note(self, guild, autor: str, texto: str) -> bool:
        """Guarda la nota. Devuelve True si se adjuntó a una reunión activa."""
        session = self.sessions.get(guild.id) if guild else None
        hora = datetime.now().strftime("%H:%M")
        if session:
            session.text_notes.append((hora, autor, texto))
            return True
        # Sin reunión activa → guardar en el archivo de notas sueltas
        try:
            with open(config.NOTES_FILE, "a", encoding="utf-8") as f:
                f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {autor}: {texto}\n")
        except OSError as e:
            log.error("No se pudo guardar la nota: %s", e)
        return False


async def setup(bot: commands.Bot):
    await bot.add_cog(MeetingCog(bot))
