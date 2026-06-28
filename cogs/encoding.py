import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

import config

log = logging.getLogger(__name__)


class EncodingCog(
    commands.GroupCog,
    name="Encoding",
    group_name="encoder",
    group_description="Notificaciones y control del encoder de video",
):
    """Recibe notificaciones del encoder vía HTTP y permite controlarlo desde Discord."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._runner: web.AppRunner | None = None

    # ── Servidor HTTP: encoder → bot (notificaciones) ────────────────────────────
    async def cog_load(self):
        app = web.Application()
        app.router.add_post("/notify", self._handle_notify)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, config.NOTIFY_HOST, config.NOTIFY_PORT)
        await site.start()
        log.info(f"HTTP listener activo en {config.NOTIFY_HOST}:{config.NOTIFY_PORT}")

    async def cog_unload(self):
        if self._runner:
            await self._runner.cleanup()

    async def _handle_notify(self, request: web.Request) -> web.Response:
        try:
            data    = await request.json()
            message = data.get("content", "").strip()
            if not message:
                return web.Response(status=400)

            channel = self.bot.get_channel(config.ENCODING_CHANNEL_ID)
            if channel is None:
                # No está en caché (¿permiso de Ver Canal?): intentar traerlo por API.
                try:
                    channel = await self.bot.fetch_channel(config.ENCODING_CHANNEL_ID)
                except discord.HTTPException:
                    channel = None

            if channel:
                await channel.send(message)
            else:
                log.warning(
                    "ENCODING_CHANNEL_ID (%s) no encontrado — ¿el bot está en ese servidor "
                    "y tiene permiso de Ver Canal?", config.ENCODING_CHANNEL_ID
                )

            return web.Response(status=200)
        except Exception as e:
            log.error(f"Error procesando notificación: {e}")
            return web.Response(status=500)

    # ── Cliente HTTP: bot → encoder (control) ────────────────────────────────────
    async def _send_control(self, action: str) -> dict | None:
        """Manda una orden al encoder. Devuelve la respuesta o None si no responde."""
        url = f"http://{config.ENCODER_CONTROL_HOST}:{config.ENCODER_CONTROL_PORT}/control"
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json={"action": action}) as resp:
                    return await resp.json()
        except Exception as e:
            log.error(f"No se pudo contactar al encoder: {e}")
            return None

    def _is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == config.DISCORD_USER_ID

    # ── /encoder estado ──────────────────────────────────────────────────────────
    @app_commands.command(name="estado", description="Muestra qué está haciendo el encoder ahora mismo")
    async def estado(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = await self._send_control("status")
        if res is None:
            await interaction.followup.send("❌ El encoder no responde (¿está apagado?).", ephemeral=True)
            return
        await interaction.followup.send(f"📊 {res.get('status', 'Estado desconocido')}", ephemeral=True)

    # ── /encoder detener ─────────────────────────────────────────────────────────
    @app_commands.command(name="detener", description="Detiene el encoder para poder reiniciar la PC")
    @app_commands.describe(modo="¿Cuándo debe parar?")
    @app_commands.choices(modo=[
        app_commands.Choice(name="Ahora mismo (corta el encode actual)", value="stop_now"),
        app_commands.Choice(name="Al terminar el actual", value="stop_after"),
    ])
    async def detener(self, interaction: discord.Interaction, modo: app_commands.Choice[str]):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = await self._send_control(modo.value)
        if res is None:
            await interaction.followup.send("❌ El encoder no responde (¿está apagado?).", ephemeral=True)
            return
        await interaction.followup.send(f"✅ {res.get('message', 'Hecho')}", ephemeral=True)

    # ── /encoder reanudar ────────────────────────────────────────────────────────
    @app_commands.command(name="reanudar", description="Reanuda el encoder después de una pausa")
    async def reanudar(self, interaction: discord.Interaction):
        if not self._is_admin(interaction):
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        res = await self._send_control("resume")
        if res is None:
            await interaction.followup.send("❌ El encoder no responde (¿está apagado?).", ephemeral=True)
            return
        await interaction.followup.send(f"▶️ {res.get('message', 'Reanudado')}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EncodingCog(bot))
