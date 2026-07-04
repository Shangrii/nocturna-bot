#!/usr/bin/env python3
import logging
import sys

import discord
from discord.ext import commands

import config

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
# NOTA (CR-03): el intent privilegiado `members` queda APAGADO a propósito — activarlo
# en código sin el toggle "Server Members Intent" del Developer Portal tumbaría el bot
# al arrancar (PrivilegedIntentsRequired). El backfill de la galería resuelve members
# con fetch_member() cuando la caché está fría (cogs/gallery.py::_resolve_member), así
# que los role-checks funcionan sin el intent. Si algún día se activa el toggle en el
# portal, añadir aquí `intents.members = True` convierte esos fetch REST en lookups
# de caché (optimización, no requisito).


class NocturnaBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        await self.load_extension("cogs.encoding")
        await self.load_extension("cogs.forum")
        await self.load_extension("cogs.gallery")
        await self.load_extension("cogs.help")

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

    bot = NocturnaBot()
    bot.run(config.BOT_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
