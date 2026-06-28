# Nocturna Bot — Setup

## Estructura
```
nocturna-bot/
├── bot.py                  # Entry point del bot
├── config.py               # Lee variables del .env
├── encoder.py              # Encoder del cinema (programa aparte)
├── requirements.txt        # Dependencias
├── cogs/                   # Comandos de Discord
│   ├── encoding.py         #   → /encoder
│   ├── forum.py            #   → /foro
│   ├── meeting.py          #   → /reunion
│   └── help.py             #   → /ayuda
├── core/                   # Lógica del bot (no-comandos)
│   ├── db.py               #   Base de datos (SQLite)
│   ├── dave_voice.py       #   Grabación de voz con descifrado DAVE/E2EE
│   ├── transcription.py    #   Transcripción (faster-whisper)
│   └── summarizer.py       #   Resumen (Ollama)
└── tools/
    └── test_meeting.py     #   Prueba (transcripción + resumen) sin Discord
```

## Reuniones (voz con IA, 100% local)

El bot entra al canal de voz, **descifra el audio DAVE/E2EE** (obligatorio en Discord
desde mar-2026) con la sesión `davey` de discord.py 2.7 — ver [dave_voice.py](dave_voice.py) —,
transcribe con faster-whisper (GPU) y genera un acta (resumen + tareas) con un LLM local
vía Ollama, publicándola en un foro.

**Dependencias en el servidor (una sola vez):**

```bash
sudo apt install -y ffmpeg libopus0
sudo ubuntu-drivers autoinstall && sudo reboot        # driver NVIDIA (para la GPU)
pip install -r requirements.txt
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12      # libs CUDA para Whisper en GPU
curl -fsSL https://ollama.com/install.sh | sh && ollama pull phi4
```

**Variables clave en `.env`** (ver `.env.example`): `WHISPER_MODEL=large-v3-turbo`,
`WHISPER_DEVICE=cuda`, `OLLAMA_MODEL=phi4`, `MEETINGS_FORUM_ID=<id del foro de actas>`.

**Comandos:** `/reunion grabar [tema]` · `/reunion parar` · `/reunion nota`.

## Setup del bot

```bash
# 1. Clonar / copiar los archivos al servidor
cd ~
mkdir nocturna-bot && cd nocturna-bot

# 2. Crear virtualenv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configurar
cp .env.example .env
nano .env   # Rellena BOT_TOKEN, ENCODING_CHANNEL_ID, FORUM_CHANNEL_ID

# 4. Probar manualmente primero
python bot.py

# 5. Instalar como servicio (sustituye YOUR_USER por tu usuario)
sudo cp nocturna-bot.service /etc/systemd/system/
sudo nano /etc/systemd/system/nocturna-bot.service   # Ajusta User y WorkingDirectory
sudo systemctl daemon-reload
sudo systemctl enable nocturna-bot
sudo systemctl start nocturna-bot

# Ver logs en tiempo real
journalctl -u nocturna-bot -f
```

## Setup del encoder

```bash
# El encoder ahora necesita python-dotenv y requests (ya los tenías)
pip install python-dotenv --break-system-packages

# Copia encoder.py al servidor cinema
# Crea un .env en ~/cinema/ o en el mismo directorio del encoder:

echo "NOTIFY_URL=http://127.0.0.1:8765/notify" >> ~/.env
echo "DISCORD_USER_ID=265742687150276608"      >> ~/.env

# Para que /encoder (detener/reanudar/estado) funcione, el encoder abre un puerto
# de control. Debe coincidir con el del bot (ENCODER_CONTROL_PORT).
echo "ENCODER_CONTROL_HOST=127.0.0.1"          >> ~/.env
echo "ENCODER_CONTROL_PORT=8766"               >> ~/.env
```

## Permisos del bot en Discord

El bot necesita en el servidor:
- `Read Messages / View Channels`
- `Send Messages`
- `Manage Messages` (para borrar la respuesta del usuario en el foro)
- `Read Message History`
- `Attach Files` (para adjuntar la transcripción del acta)
- En el foro de reuniones: `Create Posts` (para publicar las actas)
- Para reuniones de voz: `Connect` y `Speak` en los canales de voz

En el Developer Portal → Bot:
- Activa **Message Content Intent**
- Activa **Server Members Intent** (opcional pero recomendado)

## Cómo agregar más cogs después

```bash
# Crear cogs/editores.py con la misma estructura
# Agregar en bot.py setup_hook:
await self.load_extension("cogs.editores")
```
