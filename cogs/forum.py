import asyncio
import difflib
import logging
import re
from urllib.parse import urlparse, urlunparse

import discord
from discord import app_commands
from discord.ext import commands

import config
from core.db import (
    init_db, save_post, delete_post, search_posts,
    get_known_avatars, count_avatars, rename_avatar, delete_avatar,
    find_duplicate_url, get_posts_without_url, update_source_url,
)

log = logging.getLogger(__name__)

# ── Constantes de palabras clave ───────────────────────────────────────────────
_GENERAL_KEYWORDS = ["general", "ninguno"]

# ── Constantes de mensajes ─────────────────────────────────────────────────────
TYPO_CORRECTION_PROMPT = "🔍 Detecté posibles errores ortográficos:\n\n{}\n\n¿Los corrijo?"
SEARCH_HINT = "Usa /buscar <avatar> para encontrar assets compatibles"
THREAD_ONLY_ERROR = "Este comando solo funciona dentro de un post del foro de assets."

# Dominios de plataformas de venta de assets
_ASSET_DOMAINS = {
    "booth.pm",
    "gumroad.com",
    "patreon.com",
    "ko-fi.com",
    "itch.io",
    "jinxxy.com",
}

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)


def _normalize_url(raw: str) -> str:
    """Normaliza una URL: quita query params, fragmentos y trailing slash."""
    parsed = urlparse(raw)
    clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
    return clean.lower()


def _extract_source_url(text: str) -> str:
    """Extrae la primera URL de una plataforma de assets conocida del texto."""
    for match in _URL_RE.finditer(text):
        url = match.group()
        try:
            host = urlparse(url).netloc.lower()
        except ValueError:
            continue
        for domain in _ASSET_DOMAINS:
            if host == domain or host.endswith("." + domain):
                return _normalize_url(url)
    return ""


# ── Vista de confirmación de typos ─────────────────────────────────────────────
class TypoConfirmView(discord.ui.View):
    def __init__(self, author_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.accepted: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Solo el autor del post puede responder.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Sí, corregir", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accepted = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="No, mantener como está", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accepted = False
        await interaction.response.defer()
        self.stop()


# ── Vista de paginación para búsqueda ──────────────────────────────────────────
class SearchPaginationView(discord.ui.View):
    def __init__(self, lines: list[str], avatar: str, fuzzy_note: str, first_image: str, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.lines = lines
        self.avatar = avatar
        self.fuzzy_note = fuzzy_note
        self.first_image = first_image
        self.current_page = 0
        self.items_per_page = 10
        self.total_pages = (len(lines) + self.items_per_page - 1) // self.items_per_page
        
        self.update_buttons()

    def update_buttons(self):
        """Actualiza el estado de los botones según la página actual."""
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == self.total_pages - 1

    def get_embed(self) -> discord.Embed:
        """Genera el embed para la página actual."""
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_lines = self.lines[start:end]
        
        description = self.fuzzy_note + "\n\n" if self.fuzzy_note else ""
        description += "\n".join(page_lines) if page_lines else "*No hay posts disponibles.*"
        
        embed = discord.Embed(
            title=f"🔎 Assets para {self.avatar.title()}",
            description=description,
            color=0x7B2FBE
        )
        if self.first_image:
            embed.set_thumbnail(url=self.first_image)
        
        page_text = f"Página {self.current_page + 1}/{self.total_pages}"
        embed.set_footer(text=f"{len(self.lines)} resultado(s) • {page_text}")
        
        return embed

    @discord.ui.button(label="◀ Anterior", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="Siguiente ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)
        else:
            await interaction.response.defer()


# ── Cog ────────────────────────────────────────────────────────────────────────
class ForumCog(
    commands.GroupCog,
    name="Forum",
    group_name="foro",
    group_description="Gestión del foro de assets (buscar, etiquetar, etc.)",
):
    """Sistema de etiquetas de avatares para el foro de assets."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pending: set[int] = set()   # thread_ids esperando respuesta
        init_db()

    # ── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    async def _fetch_starter(thread: discord.Thread) -> discord.Message | None:
        """Obtiene el mensaje inicial del thread."""
        try:
            starter = thread.starter_message
            if starter is None:
                starter = await thread.fetch_message(thread.id)
            return starter
        except discord.HTTPException:
            return None

    @staticmethod
    def _extract_image_from_message(msg: discord.Message) -> str:
        """Obtiene la primera imagen de un mensaje."""
        for att in msg.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                return att.url
        for emb in msg.embeds:
            if emb.thumbnail and emb.thumbnail.url:
                return emb.thumbnail.url
            if emb.image and emb.image.url:
                return emb.image.url
        return ""

    @staticmethod
    def _detect_typos(avatars: list[str]) -> dict[str, str]:
        """Compara los nombres contra la DB y devuelve {original: sugerencia}."""
        known = get_known_avatars()
        if not known:
            return {}
        corrections: dict[str, str] = {}
        for a in avatars:
            lower_a = a.lower().strip()
            if lower_a not in known:
                matches = difflib.get_close_matches(
                    lower_a, list(known), n=1, cutoff=0.7
                )
                if matches:
                    corrections[a] = matches[0]
        return corrections

    @staticmethod
    def _apply_corrections(avatars: list[str], corrections: dict[str, str]) -> list[str]:
        return [
            corrections[a].title() if a in corrections else a
            for a in avatars
        ]

    async def _parse_and_correct_avatars(
        self, content: str, author_id: int, context: discord.abc.Messageable | discord.Interaction
    ) -> tuple[list[str], str]:
        """Parse user input, detect typos, apply corrections, and format for display.
        
        Args:
            content: Raw user input (comma-separated avatar names)
            author_id: Discord user ID for typo confirmation
            context: Either a thread (for wait_for) or interaction (for ephemeral responses)
            
        Returns:
            (avatars_list, formatted_display_string) where avatars are title-cased
        """
        content = content.strip()

        # Check for "general" keyword
        if (content.lower() in _GENERAL_KEYWORDS
                or difflib.get_close_matches(content.lower(), _GENERAL_KEYWORDS, n=1, cutoff=0.7)):
            return ["general"], "*General — compatible con múltiples avatares*"

        # Parse comma-separated list
        avatars = [a.strip() for a in content.split(",") if a.strip()]

        # Detect and offer typo corrections
        corrections = self._detect_typos(avatars)
        if corrections:
            lines = [
                f"• **{orig}** → **{sug.title()}**"
                for orig, sug in corrections.items()
            ]
            view = TypoConfirmView(author_id=author_id)
            
            # Handle both thread context (for on_thread_create) and interaction context (for commands)
            if isinstance(context, discord.abc.Messageable) and not isinstance(context, discord.Interaction):
                typo_msg = await context.send(
                    TYPO_CORRECTION_PROMPT.format("\n".join(lines)),
                    view=view,
                )
            else:  # Interaction
                await context.response.send_message(
                    TYPO_CORRECTION_PROMPT.format("\n".join(lines)),
                    view=view,
                    ephemeral=True,
                )
                typo_msg = None
            
            await view.wait()

            if view.accepted:
                avatars = self._apply_corrections(avatars, corrections)

            if typo_msg:
                try:
                    await typo_msg.delete()
                except discord.Forbidden:
                    pass

        # Format with backticks, preserving original capitalization
        avatar_display = "  ".join(f"`{a}`" for a in avatars)
        return avatars, avatar_display

    # ── Listeners ──────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        if thread.parent_id != config.FORUM_CHANNEL_ID:
            return
        delete_post(thread.id)
        log.info(f"Post eliminado de la DB: {thread.name} ({thread.id})")

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        # Solo actuar en el foro de assets configurado
        if thread.parent_id != config.FORUM_CHANNEL_ID:
            return
        # Evitar doble-disparo
        if thread.id in self._pending:
            return
        self._pending.add(thread.id)

        try:
            # Discord no deja enviar mensajes hasta que el autor del post
            # haya enviado su mensaje inicial. Reintentar con backoff.
            await thread.join()
            prompt = None
            starter = None
            for attempt in range(6):
                await asyncio.sleep(2 * (attempt + 1))
                # Intentar obtener el mensaje inicial en cada intento
                if starter is None:
                    starter = await self._fetch_starter(thread)
                try:
                    prompt = await thread.send(
                        f"👋 <@{thread.owner_id}> ¿Para qué avatares sirve este asset?\n\n"
                        f"Escríbelos separados por comas (SIN COMETER ERRORES ORTOGRÁFICOS) — ejemplo: `Manuka, Rindo, Shinano`\n"
                        f"*(Escribe `general` si es compatible con múltiples avatares, como aretes u otros accesorios)*"
                    )
                    break
                except discord.Forbidden as e:
                    if e.code == 40058 and attempt < 5:
                        log.debug(f"Thread {thread.id}: esperando mensaje inicial (intento {attempt + 1})")
                        continue
                    raise

            if prompt is None:
                log.warning(f"Thread {thread.id}: no se pudo enviar prompt tras 6 intentos")
                return

            # ── Extraer datos del mensaje inicial ──────────────────────────────
            image_url = ""
            source_url = ""
            if starter:
                image_url = self._extract_image_from_message(starter)
                # Buscar URL de plataforma en texto + embeds
                source_url = _extract_source_url(starter.content or "")
                if not source_url:
                    for emb in starter.embeds:
                        if emb.url:
                            source_url = _extract_source_url(emb.url)
                            if source_url:
                                break

            # ── Detección de duplicados ─────────────────────────────────────────
            if source_url:
                dup = find_duplicate_url(source_url, exclude_thread=thread.id)
                if dup:
                    dup_thread = self.bot.get_channel(dup["thread_id"])
                    dup_link = dup_thread.jump_url if dup_thread else f"(thread {dup['thread_id']})"
                    await thread.send(
                        f"⚠️ **Asset posiblemente duplicado** — ya existe un post con el mismo link:\n"
                        f"➜ [{dup['title']}]({dup_link})"
                    )

            def check(m: discord.Message) -> bool:
                return (
                    m.channel.id == thread.id
                    and m.author.id == thread.owner_id
                    and not m.author.bot
                )

            try:
                reply = await self.bot.wait_for("message", check=check, timeout=300)
            except asyncio.TimeoutError:
                await prompt.edit(
                    content="⏰ No se recibió respuesta — el post quedó sin etiquetas de avatar. "
                            "Puedes pedirle al <@&1418724526308593834> que lo etiquete."
                )
                return

            # ── Parsear respuesta ──────────────────────────────────────────────
            content = reply.content.strip()
            avatars, avatar_display = await self._parse_and_correct_avatars(
                content, thread.owner_id, thread
            )

            save_post(thread.id, thread.name, thread.owner_id, avatars,
                      image_url, source_url)

            # ── Editar el mensaje del bot con embed limpio ─────────────────────
            embed = discord.Embed(
                title="🏷️ Avatares compatibles",
                description=avatar_display or "*Ninguno*",
                color=0x7B2FBE
            )
            embed.set_footer(text=SEARCH_HINT)

            await prompt.edit(content=None, embed=embed)

            # Borrar la respuesta del usuario para mantener el hilo limpio
            try:
                await reply.delete()
            except (discord.Forbidden, discord.NotFound):
                pass  # Sin permisos o ya fue borrado, no es crítico

        except Exception as e:
            log.error(f"Error en on_thread_create (thread {thread.id}): {e}")
        finally:
            self._pending.discard(thread.id)

    # ── Slash command /buscar ──────────────────────────────────────────────────
    @app_commands.command(
        name="buscar",
        description="Busca assets en el foro compatibles con un avatar específico"
    )
    @app_commands.describe(avatar="Nombre del avatar (ej: Manuka, Rindo, Shinano...)")
    async def buscar(self, interaction: discord.Interaction, avatar: str):
        """Search for assets compatible with an avatar name.
        
        Performs exact search, then fuzzy matching if no exact results found.
        Uses pagination for results > 10.
        
        Args:
            interaction: Discord interaction context
            avatar: Avatar name to search for (1-50 characters)
        """
        # Validate input
        avatar = avatar.strip()
        if not avatar:
            await interaction.response.send_message(
                "❌ Por favor proporciona un nombre de avatar.",
                ephemeral=True
            )
            return
        
        if len(avatar) > 50:
            await interaction.response.send_message(
                "❌ El nombre del avatar es demasiado largo (máx 50 caracteres).",
                ephemeral=True
            )
            return

        rows = search_posts(avatar)
        fuzzy_note = ""

        if not rows:
            # Intentar búsqueda difusa si no hay resultados exactos
            known = get_known_avatars()
            matches = difflib.get_close_matches(avatar.lower(), list(known), n=1, cutoff=0.6)
            if matches:
                rows = search_posts(matches[0])
                fuzzy_note = (
                    f"*No encontré \"{avatar}\", mostrando resultados "
                    f"para \"{matches[0].title()}\".*"
                )

        if not rows:
            await interaction.response.send_message(
                f"No encontré assets etiquetados para **{avatar}**.\n"
                f"Prueba con una variación del nombre o revisa el foro directamente.",
                ephemeral=True
            )
            return

        lines: list[str] = []
        first_image = ""
        for row in rows:
            # Construir el jump_url directamente sin hacer fetch del thread
            jump_url = f"https://discord.com/channels/{config.GUILD_ID}/{row['thread_id']}"
            lines.append(f"[{row['title']}]({jump_url})")
            if not first_image and row["image_url"]:
                first_image = row["image_url"]

        if not lines:
            await interaction.response.send_message(
                f"No hay posts disponibles para **{avatar}**.",
                ephemeral=True
            )
            return

        # Usar paginación si hay múltiples resultados
        view = SearchPaginationView(lines, avatar, fuzzy_note, first_image)
        embed = view.get_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── Slash command /etiquetar ───────────────────────────────────────────────
    @app_commands.command(
        name="etiquetar",
        description="Etiqueta manualmente un post del foro con avatares compatibles"
    )
    @app_commands.describe(avatares="Nombres separados por comas (ej: Manuka, Rindo) o 'general'")
    async def etiquetar(self, interaction: discord.Interaction, avatares: str):
        thread = interaction.channel
        if not isinstance(thread, discord.Thread) or thread.parent_id != config.FORUM_CHANNEL_ID:
            await interaction.response.send_message(
                THREAD_ONLY_ERROR,
                ephemeral=True
            )
            return

        avatar_list, avatar_display = await self._parse_and_correct_avatars(
            avatares, interaction.user.id, interaction
        )

        starter = await self._fetch_starter(thread)
        img = self._extract_image_from_message(starter) if starter else ""
        src = ""
        if starter:
            src = _extract_source_url(starter.content or "")
            if not src:
                for emb in starter.embeds:
                    if emb.url:
                        src = _extract_source_url(emb.url)
                        if src:
                            break

        save_post(thread.id, thread.name, thread.owner_id or interaction.user.id,
                  avatar_list, img, src)

        embed = discord.Embed(
            title="🏷️ Avatares compatibles",
            description=avatar_display or "*Ninguno*",
            color=0x7B2FBE
        )
        embed.set_footer(text=SEARCH_HINT)

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    # ── Slash command /avatares (admin) ─────────────────────────────────────
    @app_commands.command(
        name="avatares",
        description="Lista todos los nombres de avatar en la base de datos"
    )
    async def avatares(self, interaction: discord.Interaction):
        """List all avatar names in the database with post counts.
        
        Admin-only command showing frequency of each avatar across all posts.
        """
        if interaction.user.id != config.DISCORD_USER_ID:
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        counts = count_avatars()
        if not counts:
            await interaction.response.send_message("No hay avatares en la DB.", ephemeral=True)
            return

        sorted_avatars = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        lines = [f"`{name.title()}` — {c} post(s)" for name, c in sorted_avatars]

        embed = discord.Embed(
            title="🎭 Avatares en la base de datos",
            description="\n".join(lines)[:4000],
            color=0x7B2FBE
        )
        embed.set_footer(text=f"{len(counts)} avatar(es) único(s) — usa /corregir para arreglar errores")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Slash command /corregir (admin) ─────────────────────────────────────
    @app_commands.command(
        name="corregir",
        description="Corrige o elimina un nombre de avatar en toda la base de datos"
    )
    @app_commands.describe(
        mal_escrito="Nombre incorrecto (ej: eneral)",
        correcto="Nombre correcto (ej: general). Déjalo vacío para eliminarlo."
    )
    async def corregir(self, interaction: discord.Interaction, mal_escrito: str, correcto: str = ""):
        """Rename or delete an avatar name across all database entries.
        
        If correcto is provided, renames mal_escrito to correcto.
        If correcto is empty, deletes all references to mal_escrito.
        
        Args:
            interaction: Discord interaction context
            mal_escrito: Incorrect/old avatar name
            correcto: New correct name, or empty to delete
        """
        if interaction.user.id != config.DISCORD_USER_ID:
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        if correcto.strip():
            count = rename_avatar(mal_escrito, correcto)
            if count == 0:
                await interaction.response.send_message(
                    f"No encontré **{mal_escrito}** en la base de datos.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"✅ **{mal_escrito}** → **{correcto}** en {count} entrada(s).", ephemeral=True
                )
        else:
            count = delete_avatar(mal_escrito)
            if count == 0:
                await interaction.response.send_message(
                    f"No encontré **{mal_escrito}** en la base de datos.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"🗑️ **{mal_escrito}** eliminado de {count} entrada(s).", ephemeral=True
                )

    # ── Slash command /escanear (admin) ─────────────────────────────────────
    @app_commands.command(
        name="escanear",
        description="Escanea posts antiguos para extraer links de tienda y detectar duplicados"
    )
    async def escanear(self, interaction: discord.Interaction):
        """Scan old posts for store URLs using direct API, not cached threads.
        
        Attempts to extract source URLs from starter messages and reports duplicates.
        Handles threads not in bot cache by constructing URLs directly.
        """
        if interaction.user.id != config.DISCORD_USER_ID:
            await interaction.response.send_message("Sin permisos.", ephemeral=True)
            return

        posts = get_posts_without_url()
        if not posts:
            await interaction.response.send_message(
                "✅ Todos los posts ya tienen link de tienda (o no hay posts).", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"🔍 Escaneando {len(posts)} post(s) sin link de tienda...", ephemeral=True
        )

        found = 0
        dupes = []
        errors = 0
        for row in posts:
            # Construct thread URL directly (handles threads not in bot cache)
            thread_url = f"https://discord.com/channels/{config.GUILD_ID}/{row['thread_id']}"
            
            try:
                # Try to fetch thread from cache, fallback to None
                thread = self.bot.get_channel(row["thread_id"])
                starter = await self._fetch_starter(thread) if thread else None
                
                # If not in cache or fetch failed, attempt direct fetch by URL format
                if starter is None and thread:
                    log.warning(f"Could not fetch thread {row['thread_id']} from cache")
                    continue

                if starter is None:
                    continue

                src = _extract_source_url(starter.content or "")
                if not src:
                    for emb in starter.embeds:
                        if emb.url:
                            src = _extract_source_url(emb.url)
                            if src:
                                break

                if src:
                    update_source_url(row["thread_id"], src)
                    found += 1

                    dup = find_duplicate_url(src, exclude_thread=row["thread_id"])
                    if dup:
                        dupes.append((row["title"], dup["title"], thread_url))

            except Exception as e:
                log.error(f"Error escaneando thread {row['thread_id']}: {e}")
                errors += 1

            await asyncio.sleep(0.5)  # Rate limit

        # Resultado
        lines = [f"**Escaneados:** {len(posts)}  •  **Links encontrados:** {found}"]
        if errors:
            lines.append(f"**Errores:** {errors}")

        if dupes:
            lines.append("\n⚠️ **Duplicados detectados:**")
            for new_title, old_title, link in dupes[:15]:
                lines.append(f"• [{new_title}]({link}) = **{old_title}**")

        await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ForumCog(bot))
