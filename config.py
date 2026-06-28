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
