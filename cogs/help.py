import discord
from discord import app_commands
from discord.ext import commands

import config

EMBED_COLOR = 0x7B2FBE


class HelpCog(commands.Cog, name="Help"):
    """Comando /ayuda que lista todos los comandos disponibles, agrupados."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ayuda", description="Muestra todos los comandos de CachoraBot")
    async def ayuda(self, interaction: discord.Interaction):
        guild = discord.Object(id=config.GUILD_ID)
        cmds = self.bot.tree.get_commands(guild=guild) or self.bot.tree.get_commands()

        embed = discord.Embed(title="🐶 Comandos de CachoraBot", color=EMBED_COLOR)
        standalone: list[str] = []

        for cmd in sorted(cmds, key=lambda c: c.name):
            if isinstance(cmd, app_commands.Group):
                lines = [
                    f"• **/{cmd.name} {sub.name}** — {sub.description}"
                    for sub in sorted(cmd.commands, key=lambda s: s.name)
                ]
                embed.add_field(name=f"/{cmd.name}", value="\n".join(lines)[:1024], inline=False)
            else:
                standalone.append(f"• **/{cmd.name}** — {cmd.description}")

        if standalone:
            embed.add_field(name="General", value="\n".join(standalone)[:1024], inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
