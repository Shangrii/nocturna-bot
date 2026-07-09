import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Bot ────────────────────────────────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN")
DISCORD_USER_ID = int(os.getenv("DISCORD_USER_ID", "0"))

# ── Servidor Discord ────────────────────────────────────────────────────────────
GUILD_ID            = int(os.getenv("GUILD_ID", "1411899319468167190"))
FORUM_CHANNEL_ID    = int(os.getenv("FORUM_CHANNEL_ID", "0"))
ENCODING_CHANNEL_ID = int(os.getenv("ENCODING_CHANNEL_ID", "0"))
ROLE_MODERATOR_ID   = int(os.getenv("ROLE_MODERATOR_ID", "1418724526308593834"))

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
WHISPER_MODEL   = os.getenv("WHISPER_MODEL", "large-v3-turbo")  # cabe en la 1050 (~1.5 GB)
WHISPER_DEVICE  = os.getenv("WHISPER_DEVICE", "cpu")     # "cuda" en el servidor con GPU NVIDIA
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")   # int8 (CPU/GPU modesta) | float16 (GPU)
WHISPER_THREADS = int(os.getenv("WHISPER_THREADS", "4")) # hilos CPU (deja margen al encoder)
MEETING_LANG    = os.getenv("MEETING_LANG", "es")
# Pista de contexto/nombres propios para Whisper (ayuda con nombres como CachoraBot)
WHISPER_PROMPT  = os.getenv("WHISPER_PROMPT", "Reunión en español del equipo Nocturna. Bot: CachoraBot.")

# ── Reuniones: resumen (Ollama, LLM local) ───────────────────────────────────────
OLLAMA_HOST  = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi4")         # corre en CPU (la GPU es para Whisper)

# Carpeta temporal donde se guardan las grabaciones de voz antes de transcribir
RECORDINGS_DIR = Path(os.getenv("RECORDINGS_DIR", "recordings"))

# Foro donde se publican las actas de reuniones (un post por reunión)
MEETINGS_FORUM_ID = int(os.getenv("MEETINGS_FORUM_ID", "1517386124044013588"))

# Archivo donde se guardan las notas pedidas fuera de una reunión activa
NOTES_FILE = Path(os.getenv("NOTES_FILE", "notas.md"))

# ── Galería (Fase 5: cog de publicación de fotos) ─────────────────────────────────
# El cog vigila un canal público de fotos, publica los adjuntos aprobados por staff
# (reacción ✅) hacia el repo del sitio web vía la API de GitHub, y los quita con 🌙.
# Canal público donde el staff sube las fotos de avatares (D-03).
PHOTO_CHANNEL_ID = int(os.getenv("PHOTO_CHANNEL_ID", "1416329356426481717"))
# Roles cuyas reacciones ✅/🌙 sí publican/quitan (frontera de confianza, D-01/D-08).
# Cadena separada por comas en el .env → lista de ints; se ignoran valores en blanco.
GALLERY_STAFF_ROLE_IDS = [
    int(x) for x in os.getenv("GALLERY_STAFF_ROLE_IDS", "").split(",") if x.strip()
]
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
# Canal donde los clientes dejan sus reseñas.
REVIEWS_CHANNEL_ID = int(os.getenv("REVIEWS_CHANNEL_ID", "1453534905706221600"))
# Roles cuyas reacciones ✅/🌙 publican/quitan reseñas. Cadena separada por comas → lista
# de ints; si queda vacía, cae en los mismos roles de staff de la galería (CONTEXT L29).
REVIEWS_STAFF_ROLE_IDS = [
    int(x) for x in os.getenv("REVIEWS_STAFF_ROLE_IDS", "").split(",") if x.strip()
] or GALLERY_STAFF_ROLE_IDS
# Ruta del JSON de reseñas dentro del repo del sitio (mismo repo/rama que la galería).
WEBSITE_REVIEWS_JSON = os.getenv("WEBSITE_REVIEWS_JSON", "src/data/reviews.json")
