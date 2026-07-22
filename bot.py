#!/usr/bin/env python3
import logging
import sys

import discord
from discord.ext import commands

import config
import core.settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
log = logging.getLogger(__name__)

# Silenciar el ruido de la recepción de voz (RTCP, 'seq' del gateway, pérdidas de paquetes)
for _noisy in ("discord.ext.voice_recv.gateway",
               "discord.ext.voice_recv.reader",
               "discord.ext.voice_recv.opus"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

# ── Intents ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True   # Para leer la respuesta del usuario en el foro
# El intent privilegiado `members` está ACTIVADO (Fase 10, plan 10-09). El toggle
# "Server Members Intent" del Developer Portal quedó habilitado en 10-03 (confirmado en
# deploy/EDITOR_DEPLOY.md §5), así que activarlo aquí es seguro y ya NO tumba el bot al
# arrancar. Es REQUISITO de EditorsCog: sin `intents.members = True` el evento
# `on_member_update` nunca se dispara y la despublicación por pérdida de rol en tiempo
# real (D-10, mecanismo PRIMARIO) no funcionaría — sólo quedaría el sweep periódico de
# respaldo. Bono: convierte los fetch_member() REST de la galería en lookups de caché.
intents.members = True
# El intent privilegiado `presences` alimenta PresenceCog: el bot lee el estado
# (online/idle/dnd/offline) de cada editor y lo sirve a sus páginas públicas sin
# depender de Lanyard. Requiere el toggle "Presence Intent" del Developer Portal
# ACTIVADO (hecho); sin él el bot no arrancaría.
intents.presences = True


class NocturnaBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.encoding")
        await self.load_extension("cogs.forum")
        await self.load_extension("cogs.gallery")
        await self.load_extension("cogs.reviews")
        await self.load_extension("cogs.reminders")
        await self.load_extension("cogs.jinxxy")
        await self.load_extension("cogs.editors")
        await self.load_extension("cogs.presence")
        await self.load_extension("cogs.help")
        await self.load_extension("cogs.payments")
        await self.load_extension("cogs.heartbeat")

        # El cog de reuniones usa dependencias pesadas (voz, whisper). Si no están
        # instaladas, el resto del bot debe seguir funcionando igualmente.
        try:
            await self.load_extension("cogs.meeting")
        except Exception as e:
            log.warning("Cog de reuniones no cargado (¿faltan dependencias?): %s", e)

        # Registrar comandos solo en el guild específico (actualizaciones instantáneas)
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

        # Limpiar comandos globales para evitar duplicados en Discord
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        log.info("Slash commands sincronizados (guild-only)")

    async def on_ready(self):
        log.info(f"Bot listo: {self.user} ({self.user.id})")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="el encoder 🎬"
            )
        )


def main():
    # Sembrar la tabla settings una sola vez antes de cualquier lectura de tunable segura
    # (STORE-05). Idempotente: en reinicios es un no-op y NUNCA pisa la edición de un owner
    # (Pitfall 3). Va ANTES del fail-fast para que esos checks — FORUM_CHANNEL_ID,
    # ENCODING_CHANNEL_ID, GALLERY_STAFF_ROLE_IDS, REVIEWS_CHANNEL_ID, REMINDERS_TZ, que ahora
    # se leen vía settings.get — vean filas ya sembradas. Sin try/except defensivo: un fallo
    # real de siembra debe aflorar, igual que el resto del arranque fail-fast.
    core.settings.seed_defaults()
    if not config.BOT_TOKEN:
        log.error("BOT_TOKEN no configurado en el .env")
        sys.exit(1)
    if not config.FORUM_CHANNEL_ID:
        log.error("FORUM_CHANNEL_ID no configurado en el .env")
        sys.exit(1)
    if not config.ENCODING_CHANNEL_ID:
        log.error("ENCODING_CHANNEL_ID no configurado en el .env")
        sys.exit(1)
    # ── Galería (Fase 5): el cog de publicación de fotos requiere estos secretos
    #    para el push cross-repo y la frontera de confianza de staff. Fallo rápido
    #    si faltan, igual que los canales de arriba (D-01/D-15/T-05-SC).
    if not config.GITHUB_PAT:
        log.error("GITHUB_PAT no configurado en el .env (requerido para publicar la galería)")
        sys.exit(1)
    if not config.WEBSITE_REPO:
        log.error("WEBSITE_REPO no configurado en el .env (repo destino de la galería)")
        sys.exit(1)
    if not config.GALLERY_STAFF_ROLE_IDS:
        log.error("GALLERY_STAFF_ROLE_IDS no configurado en el .env (roles que aprueban fotos)")
        sys.exit(1)
    # ── Reseñas (Fase 7): el cog de reseñas necesita su canal. El PAT/repo ya están
    #    validados arriba (mismo destino que la galería) y REVIEWS_STAFF_ROLE_IDS cae en
    #    GALLERY_STAFF_ROLE_IDS cuando no se define, así que no hace falta un check aparte.
    if not config.REVIEWS_CHANNEL_ID:
        log.error("REVIEWS_CHANNEL_ID no configurado en el .env (canal de reseñas)")
        sys.exit(1)
    # ── Tienda / Jinxxy (Fase 9): el cog de sync necesita la API key del Creator API
    #    para enumerar la tienda. El PAT/repo ya están validados arriba (mismo destino
    #    cross-repo) y JINXXY_STAFF_ROLE_IDS cae en GALLERY_STAFF_ROLE_IDS cuando no se
    #    define, así que basta con el fail-fast de la key (mismo trato que GITHUB_PAT).
    if not config.JINXXY_API_KEY:
        log.error("JINXXY_API_KEY no configurado en el .env (requerido para el sync de la tienda)")
        sys.exit(1)
    # ── Recordatorios (Fase 8): todo el schedule-math ancla en REMINDERS_TZ (D-07).
    #    Si la zona IANA es inválida, ZoneInfo revienta en el primer tick del scheduler
    #    en vez de al arrancar — así que fallamos rápido aquí. REMINDERS_STAFF_ROLE_IDS
    #    cae en GALLERY_STAFF_ROLE_IDS cuando no se define (mismo motivo que reseñas).
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        ZoneInfo(config.REMINDERS_TZ)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        log.error(
            "REMINDERS_TZ inválida en el .env (%s) — usa una zona IANA, "
            "p. ej. America/Mexico_City", config.REMINDERS_TZ)
        sys.exit(1)

    bot = NocturnaBot()
    bot.run(config.BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
