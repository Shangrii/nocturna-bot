import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Config store (Fase 01) ───────────────────────────────────────────────────────
# Las 19 "tunables seguras" (canales, roles de staff, TZ, cadencias, modelos) ya NO
# se congelan como asignaciones a nivel de módulo: se leen EN EL PUNTO DE USO a través
# de core.settings.get, vía el shim __getattr__ del final de este archivo (CONF-01).
# Así una edición guardada por el owner surte efecto en la siguiente lectura, sin tocar
# ningún call-site (todos hacen `config.X`, acceso por atributo → dispara __getattr__).
# Los SECRETOS y valores ESTRUCTURALES de abajo SIGUEN congelados aquí (CONF-02): nunca
# pasan por el store ni por el panel.

# ── Bot ────────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN")
DISCORD_USER_ID = int(os.getenv("DISCORD_USER_ID", "0"))

# ── Servidor Discord ────────────────────────────────────────────────────────────
GUILD_ID            = int(os.getenv("GUILD_ID", "1411899319468167190"))
ROLE_MODERATOR_ID   = int(os.getenv("ROLE_MODERATOR_ID", "1418724526308593834"))
# FORUM_CHANNEL_ID / ENCODING_CHANNEL_ID → tunables seguras (settings.get, ver __getattr__).

# ── HTTP local ──────────────────────────────────────────────────────────────────
# encoder → bot (notificaciones)
NOTIFY_HOST = os.getenv("NOTIFY_HOST", "127.0.0.1")
NOTIFY_PORT = int(os.getenv("NOTIFY_PORT", "8765"))

# bot → encoder (control: parar/reanudar/estado)
ENCODER_CONTROL_HOST = os.getenv("ENCODER_CONTROL_HOST", "127.0.0.1")
ENCODER_CONTROL_PORT = int(os.getenv("ENCODER_CONTROL_PORT", "8766"))

# ── Base de datos ───────────────────────────────────────────────────────────────
DB_PATH = Path(os.getenv("DB_PATH", "bot.db"))

# ── Reuniones: transcripción (faster-whisper) ─────────────────────────────────────
# WHISPER_MODEL / WHISPER_PROMPT / MEETING_LANG → tunables seguras (settings.get).
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE", "cpu")     # "cuda" en el servidor con GPU NVIDIA
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")   # int8 (CPU/GPU modesta) | float16 (GPU)
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "4")) # hilos CPU (deja margen al encoder)

# ── Reuniones: resumen (Ollama, LLM local) ───────────────────────────────────────
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
# OLLAMA_MODEL → tunable segura (settings.get).

# Carpeta temporal donde se guardan las grabaciones de voz antes de transcribir
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", "recordings"))

# Foro donde se publican las actas de reuniones → MEETINGS_FORUM_ID es tunable segura (settings.get).

# Archivo donde se guardan las notas pedidas fuera de una reunión activa
NOTES_FILE = Path(os.getenv("NOTES_FILE", "notas.md"))

# ── Galería (Fase 5: cog de publicación de fotos) ─────────────────────────────────
# El cog vigila un canal público de fotos, publica los adjuntos aprobados por staff
# (reacción ✅) hacia el repo del sitio web vía la API de GitHub, y los quita con 🌙.
# PHOTO_CHANNEL_ID (canal público de fotos, D-03) y GALLERY_STAFF_ROLE_IDS (roles cuyas
# reacciones ✅/🌙 publican/quitan, D-01/D-08) → tunables seguras (settings.get).
# Token de acceso personal de GitHub (fine-grained, Contents: read/write) para el push
# cross-repo. SOLO se lee del entorno; nunca se registra en logs ni commits (D-17).
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
# Repo del sitio web destino (owner/name) — confirmado desde el remote git del sitio.
WEBSITE_REPO = os.getenv("WEBSITE_REPO", "Shangrii/Nocturna-Avatars")
# Rama destino; se cambia en el cutover a producción sin tocar código (D-15).
WEBSITE_BRANCH = os.getenv("WEBSITE_BRANCH", "revamp")
# Ruta del JSON de la galería y del directorio de imágenes dentro del repo del sitio.
WEBSITE_GALLERY_JSON = os.getenv("WEBSITE_GALLERY_JSON", "src/data/gallery.json")
WEBSITE_IMAGE_DIR = os.getenv("WEBSITE_IMAGE_DIR", "public/gallery")

# ── Reseñas (Fase 7: cog de publicación de reseñas) ───────────────────────────────
# El cog vigila el canal de reseñas, publica las reseñas aprobadas por staff (✅) hacia
# src/data/reviews.json en el repo del sitio, y las quita con 🌙 — mismo transporte y
# mismo PAT/repo/rama que la galería (no hay imágenes: solo un blob JSON por commit).
# REVIEWS_CHANNEL_ID (canal de reseñas) y REVIEWS_STAFF_ROLE_IDS (roles ✅/🌙; si queda
# vacío cae en GALLERY_STAFF_ROLE_IDS vía el fallback de settings.get, CONF-03) → tunables
# seguras (settings.get).
# Ruta del JSON de reseñas dentro del repo del sitio (mismo repo/rama que la galería).
WEBSITE_REVIEWS_JSON = os.getenv("WEBSITE_REVIEWS_JSON", "src/data/reviews.json")

# ── Recordatorios (Fase 8: cog de recordatorios programados) ──────────────────────
# El cog programa recordatorios semanales/mensuales/únicos y los publica en un canal.
# REMINDERS_TZ (zona IANA, default America/Mexico_City, D-07), REMINDERS_STAFF_ROLE_IDS
# (roles gestores; vacío → GALLERY_STAFF_ROLE_IDS vía settings.get, D-02) y
# REMINDERS_CATCHUP_GRACE_HOURS (ventana de gracia, default 6h, banda 6–12h, D-13) →
# tunables seguras (settings.get).

# ── Jinxxy (Fase 9: sync de la tienda) ────────────────────────────────────────────
# El cog consulta periódicamente la Creator API de Jinxxy y refleja los productos en
# src/data/store.json del repo del sitio (mismo transporte/PAT/repo/rama que la galería).
# Clave de la Creator API de Jinxxy (secreto). SOLO se lee del entorno y se coloca en el
# header x-api-key; nunca se registra en logs ni commits — misma disciplina que GITHUB_PAT.
JINXXY_API_KEY = os.getenv("JINXXY_API_KEY", "")
# JINXXY_ANNOUNCE_CHANNEL_ID (canal de anuncios, D-18), JINXXY_POLL_HOURS (cadencia del
# poll, default 6h, banda 6–12h, D-03), JINXXY_STAFF_ROLE_IDS (roles gestores; vacío →
# GALLERY_STAFF_ROLE_IDS vía settings.get), WEBSITE_BASE_URL (origen del sitio público,
# sin barra final) y JINXXY_STORE_URL (página de tienda EN que enlaza el embed) → tunables
# seguras (settings.get).
# Ruta del JSON de la tienda dentro del repo del sitio (mismo repo/rama que la galería).
WEBSITE_STORE_JSON = os.getenv("WEBSITE_STORE_JSON", "src/data/store.json")
# Directorio de imágenes de la tienda en el repo del sitio; GitHub Pages lo sirve como
# /store/<archivo> (flujo de attach del staff, D-15).
WEBSITE_STORE_IMAGE_DIR = os.getenv("WEBSITE_STORE_IMAGE_DIR", "public/store")

# ── Editores (Fase 10: app admin web de perfiles de editores) ────────────────────
# App FastAPI separada (systemd propio en "cinema") que autentica editores vía Discord
# OAuth2 + una verificación en vivo del rol de editor (D-07), y publica editors.json +
# imágenes al repo del sitio con el mismo transporte cross-repo que la galería/tienda
# (core/github_publish.py, mismo GITHUB_PAT/WEBSITE_REPO/WEBSITE_BRANCH).
# Ruta del JSON de editores y del directorio de imágenes dentro del repo del sitio
# (mismo idiom que WEBSITE_STORE_JSON / WEBSITE_STORE_IMAGE_DIR).
WEBSITE_EDITORS_JSON = os.getenv("WEBSITE_EDITORS_JSON", "src/data/editors.json")
WEBSITE_EDITORS_IMAGE_DIR = os.getenv("WEBSITE_EDITORS_IMAGE_DIR", "public/editors")
# Credenciales de la app OAuth2 de Discord registrada para el panel admin. SOLO se leen
# del entorno; nunca se registran en logs ni commits (mismo trato que GITHUB_PAT).
DISCORD_OAUTH_CLIENT_ID = os.getenv("DISCORD_OAUTH_CLIENT_ID", "")
DISCORD_OAUTH_CLIENT_SECRET = os.getenv("DISCORD_OAUTH_CLIENT_SECRET", "")
DISCORD_OAUTH_REDIRECT_URI = os.getenv("DISCORD_OAUTH_REDIRECT_URI", "")
# Clave de firma de la cookie de sesión (Starlette SessionMiddleware / itsdangerous).
# SIN valor por defecto — debe fallar rápido (fail-fast) si la app arranca sin ella en
# el entorno; nunca se registra en logs ni commits.
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
# Origen (sin barra final) del subdominio donde vive el panel admin, p.ej.
# https://editors.nocturna-avatars.site — usado para construir el redirect_uri de OAuth
# y enlaces absolutos (no confundir con WEBSITE_BASE_URL, que es el sitio público).
EDITOR_APP_BASE_URL = os.getenv("EDITOR_APP_BASE_URL", "https://editors.nocturna-avatars.site")
# El rol de editor reutiliza el rol de moderador existente (D-15) — no se crea un
# ROLE_EDITOR_ID nuevo; ROLE_MODERATOR_ID (arriba) ya cubre esta frontera de confianza.

# ── Pagos (comando /pago — métodos de pago) ───────────────────────────────────────
# El staff dispara /pago y el bot postea un embed PÚBLICO bilingüe con los métodos de
# pago cuyos datos estén configurados. Los datos son SENSIBLES → SOLO en el .env, nunca
# en el repo; cada método es opcional (vacío → se omite del mensaje).
# Roles cuyo /pago puede postear (frontera de confianza). Cadena separada por comas →
# lista de ints; si queda vacía, cae en los mismos roles de staff de la galería. Este
# tunable NO está en el store (fuera de alcance de la Fase 01), así que sigue congelado
# aquí; su fallback a la galería se resuelve del .env en el import (byte-idéntico a antes),
# no vía settings.get — por eso se re-parsea GALLERY_STAFF_ROLE_IDS inline en lugar de
# referenciar el nombre (que ya no existe a nivel de módulo → daría NameError).
PAGO_STAFF_ROLE_IDS = [
    int(x) for x in os.getenv("PAGO_STAFF_ROLE_IDS", "").split(",") if x.strip()
] or [
    int(x) for x in os.getenv("GALLERY_STAFF_ROLE_IDS", "").split(",") if x.strip()
]
# Datos de cada método (texto libre; neutro de idioma: CLABE, tag, link/email).
PAGO_DEPOSITO_MX_INFO = os.getenv("PAGO_DEPOSITO_MX_INFO", "")     # depósito/CLABE México
PAGO_INTERNACIONAL_INFO = os.getenv("PAGO_INTERNACIONAL_INFO", "")  # Revolut internacional (EE.UU.) — futuro
PAGO_PAYPAL_INFO = os.getenv("PAGO_PAYPAL_INFO", "")               # paypal.me / email


# ── Config store shim (Fase 01, plan 01-03) ───────────────────────────────────────
# Las 19 tunables seguras se leen en el punto de uso a través del store. Se listan aquí
# en un allowlist explícito; SOLO estas rutan a settings.get — cualquier otro atributo
# ausente levanta AttributeError como siempre (los secretos/estructurales de arriba son
# atributos normales del módulo y ni siquiera llegan a __getattr__).
_SAFE_TUNABLE_KEYS = frozenset({
    "PHOTO_CHANNEL_ID",
    "GALLERY_STAFF_ROLE_IDS",
    "REVIEWS_CHANNEL_ID",
    "REVIEWS_STAFF_ROLE_IDS",
    "REMINDERS_TZ",
    "REMINDERS_STAFF_ROLE_IDS",
    "REMINDERS_CATCHUP_GRACE_HOURS",
    "JINXXY_ANNOUNCE_CHANNEL_ID",
    "JINXXY_POLL_HOURS",
    "JINXXY_STAFF_ROLE_IDS",
    "JINXXY_STORE_URL",
    "WEBSITE_BASE_URL",
    "MEETINGS_FORUM_ID",
    "MEETING_LANG",
    "WHISPER_PROMPT",
    "WHISPER_MODEL",
    "OLLAMA_MODEL",
    "FORUM_CHANNEL_ID",
    "ENCODING_CHANNEL_ID",
})


def __getattr__(name):
    """PEP 562 module hook: route the 19 safe tunables to the store, read-at-use (CONF-01).

    Only fires for names NOT found as real module attributes, so every secret/structural
    assignment above shadows this and never routes through the store (CONF-02). The
    ``from core import settings`` import is DEFERRED inside the body on purpose: core/db.py
    does ``import config`` at module top, so a module-level import here would form a circular
    import at startup (01-RESEARCH.md Pitfall 1). No DB I/O happens at config import time —
    this only runs on attribute access.
    """
    if name in _SAFE_TUNABLE_KEYS:
        from core import settings
        return settings.get(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
