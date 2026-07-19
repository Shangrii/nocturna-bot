"""Comando ``/pago`` — publica los métodos de pago disponibles (solo staff).

El staff dispara ``/pago`` en un canal y el bot postea un embed **público** bilingüe
(ES/EN) con los métodos de pago cuyos datos estén configurados. Los datos sensibles
(CLABE, Revolut, PayPal) viven **solo** en el ``.env`` (``config.PAGO_*_INFO``) — nunca
en el repo — y cada método es opcional: si su valor está vacío, se omite del mensaje.
Un no-staff recibe un "Sin permisos" efímero y no se postea nada (misma frontera de
confianza que el resto de los cogs: la reacción/el comando solo cuenta si viene de un
rol de staff configurado).

La lógica de decisión (``_is_staff`` / ``build_payment_embed`` / ``plan_response``) es
pura e import-safe para poder testearse sin Discord; el método del comando solo la cablea
a ``interaction.response.send_message``.
"""
import discord
from discord import app_commands
from discord.ext import commands

import config

# Rojo de marca (mismo que el embed de anuncios de la tienda).
_BRAND_RED = 0xC0192C

# Métodos en orden de aparición: (título bilingüe ES · EN, nombre del atributo de config).
# El día que exista el método internacional, basta con rellenar PAGO_INTERNACIONAL_INFO
# en el .env — no hay cambio de código.
_METHODS = [
    ("💳 Depósito bancario (México) · Bank deposit (Mexico)", "PAGO_DEPOSITO_MX_INFO"),
    ("🌎 Transferencia internacional (Revolut) · International transfer (Revolut)",
     "PAGO_INTERNACIONAL_INFO"),
    ("🅿️ PayPal", "PAGO_PAYPAL_INFO"),
]


def _is_staff(member) -> bool:
    """True iff ``member`` holds a configured pago-staff role (trust boundary).

    ``PAGO_STAFF_ROLE_IDS`` falls back to ``GALLERY_STAFF_ROLE_IDS`` when unset (config).
    A bot or a role-less member is never staff (an empty role intersection is falsy).
    """
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(role_ids & set(config.PAGO_STAFF_ROLE_IDS))


def _configured_methods():
    """Return the (title, details) pairs whose details are configured (non-empty)."""
    out = []
    for title, attr in _METHODS:
        details = (getattr(config, attr, "") or "").strip()
        if details:
            out.append((title, details))
    return out


def build_payment_embed():
    """Build the public bilingual payment-methods embed, or ``None`` if nothing is set."""
    methods = _configured_methods()
    if not methods:
        return None
    embed = discord.Embed(
        title="💰 Métodos de pago · Payment methods",
        description=("Estos son los métodos de pago disponibles. · "
                     "These are the available payment methods."),
        color=_BRAND_RED,
    )
    for title, details in methods:
        embed.add_field(name=title, value=details, inline=False)
    embed.set_footer(text="Nocturna Avatars")
    return embed


def plan_response(is_staff: bool, embed):
    """Pure decision of what ``/pago`` should send: ``(content, embed, ephemeral)``.

    - non-staff → ephemeral "Sin permisos." (nothing posted publicly)
    - staff but no method configured → ephemeral warning
    - staff with an embed → the public embed (``ephemeral=False``)
    """
    if not is_staff:
        return ("Sin permisos.", None, True)
    if embed is None:
        return ("⚠️ No hay métodos de pago configurados. · "
                "No payment methods are configured.", None, True)
    return (None, embed, False)


class PaymentsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="pago",
        description="Publica los métodos de pago · Post the available payment methods (staff)",
    )
    async def pago(self, interaction: discord.Interaction):
        content, embed, ephemeral = plan_response(
            _is_staff(interaction.user), build_payment_embed())
        await interaction.response.send_message(
            content=content, embed=embed, ephemeral=ephemeral)


async def setup(bot: commands.Bot):
    await bot.add_cog(PaymentsCog(bot))
