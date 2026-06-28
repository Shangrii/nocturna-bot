#!/usr/bin/env python3
"""encoder.py — Cinema encoding pipeline."""
import os
import sys
import json
import time
import shutil
import subprocess
import logging
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import requests

load_dotenv()

# ── Configuración ─────────────────────────────────────────────────────────────
BASE_DIR     = Path.home() / "cinema"
INPUT_DIR    = BASE_DIR / "input"
OUTPUT_DIR   = BASE_DIR / "output"
PENDING_DIR  = BASE_DIR / "pending"
SUBS_DIR     = BASE_DIR / "subs"
SPLIT_DIR    = BASE_DIR / "split"
FAILED_DIR   = BASE_DIR / "split" / "failed"   # ← nuevo: splits fallidos
LOG_FILE     = BASE_DIR / "logs" / "encoder.log"

# Bot local (reemplaza el webhook)
NOTIFY_URL      = os.getenv("NOTIFY_URL", "http://127.0.0.1:8765/notify")
DISCORD_USER_ID = os.getenv("DISCORD_USER_ID", "")

# Control remoto desde el bot (bot → encoder)
CONTROL_HOST    = os.getenv("ENCODER_CONTROL_HOST", "127.0.0.1")
CONTROL_PORT    = int(os.getenv("ENCODER_CONTROL_PORT", "8766"))

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flac", ".ts", ".m4v"}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger(__name__)

# ── Estado global — thread-safe ───────────────────────────────────────────────
split_event  = threading.Event()   # Set mientras hay split activo
encoder_lock = threading.Lock()    # Solo un encode a la vez

# Control remoto (lo maneja el servidor HTTP de control)
_paused       = threading.Event()  # Set → no iniciar nuevos encodes
_stop_after   = threading.Event()  # Set → pausar al terminar el encode actual
_stop_now     = threading.Event()  # Set → el corte actual fue intencional (no es "fallo")
_proc_lock    = threading.Lock()
_current_proc: "subprocess.Popen | None" = None
_current_file = ""

# ── Discord ───────────────────────────────────────────────────────────────────
def notify_discord(message: str):
    """Envía notificación al bot local, que la reenvía a Discord."""
    try:
        requests.post(NOTIFY_URL, json={"content": message}, timeout=5)
    except Exception as e:
        log.error(f"Notify falló (¿bot apagado?): {e}")

# ── Ejecución cancelable de ffmpeg ──────────────────────────────────────────────
def run_ffmpeg(cmd: list) -> tuple:
    """Ejecuta ffmpeg de forma que pueda cancelarse desde el control remoto.

    Devuelve (returncode, stderr). Si el bot pide "parar ahora", el proceso se
    mata y el returncode será distinto de 0.
    """
    global _current_proc
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    with _proc_lock:
        _current_proc = proc
    try:
        _out, stderr = proc.communicate()
    finally:
        with _proc_lock:
            _current_proc = None
    return proc.returncode, stderr or ""


def _kill_current():
    """Mata el ffmpeg en curso, si lo hay."""
    with _proc_lock:
        proc = _current_proc
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _is_busy() -> bool:
    """True si hay un ffmpeg corriendo o un split en curso."""
    with _proc_lock:
        return _current_proc is not None or split_event.is_set()

# ── Control remoto (HTTP) ───────────────────────────────────────────────────────
def _status_text() -> str:
    if _paused.is_set():
        estado = "⏸️ en pausa"
    elif _is_busy():
        estado = f"🎬 trabajando en `{_current_file}`" if _current_file else "🎬 trabajando"
    else:
        estado = "🟢 inactivo (esperando archivos)"
    pendientes = len(get_video_files(INPUT_DIR)) + len(get_video_files(SPLIT_DIR))
    return f"{estado} — {pendientes} archivo(s) en cola"


def handle_control(action: str) -> dict:
    """Procesa una orden del bot. Devuelve {ok, message/status}."""
    if action == "status":
        return {"ok": True, "status": _status_text()}

    if action == "stop_now":
        _paused.set()
        _stop_now.set()
        _kill_current()
        notify_discord("🛑 Encoder detenido de inmediato. Ya puedes reiniciar la PC.")
        return {"ok": True, "message": "Encoder detenido ahora. Ya puedes reiniciar."}

    if action == "stop_after":
        if not _is_busy():
            _paused.set()
            notify_discord("✅ Encoder detenido (no había nada en curso). Ya puedes reiniciar.")
            return {"ok": True, "message": "No había encode en curso; encoder detenido."}
        _stop_after.set()
        notify_discord("⏳ El encoder se detendrá al terminar el encode actual.")
        return {"ok": True, "message": "Se detendrá al terminar el encode actual."}

    if action == "resume":
        _paused.clear()
        _stop_after.clear()
        _stop_now.clear()
        notify_discord("▶️ Encoder reanudado.")
        return {"ok": True, "message": "Encoder reanudado."}

    return {"ok": False, "message": f"Acción desconocida: {action}"}


class _ControlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/control":
            self.send_response(404)
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            action = json.loads(body).get("action", "")
        except Exception:
            action = ""
        result = handle_control(action)
        payload = json.dumps(result).encode("utf-8")
        self.send_response(200 if result.get("ok") else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # silenciar el log por defecto de http.server


def start_control_server():
    server = HTTPServer((CONTROL_HOST, CONTROL_PORT), _ControlHandler)
    threading.Thread(target=server.serve_forever, daemon=True, name="control").start()
    log.info(f"Control HTTP activo en {CONTROL_HOST}:{CONTROL_PORT}")

# ── FFprobe ───────────────────────────────────────────────────────────────────
def probe(filepath: Path) -> dict:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(filepath)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)

def get_audio_streams(data: dict) -> list:
    return [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]

def get_subtitle_streams(data: dict) -> list:
    return [s for s in data.get("streams", []) if s.get("codec_type") == "subtitle"]

def is_spanish(stream: dict) -> bool:
    lang = stream.get("tags", {}).get("language", "").lower()
    return lang in ("spa", "es", "spanish")

def find_spanish_audio(streams: list) -> dict | None:
    return next((s for s in streams if is_spanish(s)), None)

def find_spanish_subtitle(streams: list) -> dict | None:
    return next((s for s in streams if is_spanish(s)), None)

def find_foreign_audio(streams: list) -> dict | None:
    """Devuelve la primera pista de audio que NO sea español."""
    return next((s for s in streams if not is_spanish(s)), None)

def get_lang_tag(stream: dict) -> str:
    """Devuelve el código de idioma en mayúsculas (ENG, JPN, FRA...)."""
    lang = stream.get("tags", {}).get("language", "und").upper()
    return lang if lang != "UND" else "OG"

# ── FFmpeg encoding ───────────────────────────────────────────────────────────
def encode_vp9(
    input_path: Path,
    output_path: Path,
    audio_index: int = None,
    sub_index: int = None,
    external_srt: Path = None
) -> bool:
    def escape_filter_path(p: Path) -> str:
        s = str(p).replace("\\", "/").replace("'", "\\'")
        s = s.replace(":", "\\:").replace("[", "\\[").replace("]", "\\]")
        return f"'{s}'"

    cmd = ["ffmpeg", "-y", "-i", str(input_path)]

    if external_srt:
        cmd += ["-vf", f"subtitles={escape_filter_path(external_srt)}"]
    elif sub_index is not None:
        cmd += ["-vf", f"subtitles={escape_filter_path(input_path)}:si={sub_index}"]

    if audio_index is not None:
        cmd += ["-map", "0:v:0", "-map", f"0:a:{audio_index}"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0"]

    cmd += [
        "-c:v", "libvpx-vp9",
        "-crf", "27",
        "-b:v", "0",
        "-row-mt", "1",
        "-tile-columns", "2",
        "-tile-rows", "1",
        "-threads", "6",
        "-c:a", "libopus",
        "-ac", "2",
        "-b:a", "128k",
        str(output_path)
    ]

    log.info(f"FFmpeg: {' '.join(cmd)}")
    rc, stderr = run_ffmpeg(cmd)
    if rc != 0:
        if not _stop_now.is_set():  # si fue un corte intencional, no es un error real
            log.error(f"FFmpeg error:\n{stderr[-2000:]}")
        return False
    return True


def _encode_and_finish(filepath: Path, output_path: Path, label_ok: str, **enc) -> None:
    """Codifica y maneja el resultado: éxito, fallo o cancelado por el usuario."""
    if encode_vp9(filepath, output_path, **enc):
        notify_discord(f"✅ {label_ok}: `{output_path.name}`")
        filepath.unlink()
        return
    if _stop_now.is_set():
        # Corte intencional: descartar la salida parcial y conservar el original en la cola.
        output_path.unlink(missing_ok=True)
        log.warning(f"Encode cancelado por el usuario: {filepath.name}")
        return
    notify_discord(f"❌ Falló el encode de `{filepath.name}`")

# ── Split ─────────────────────────────────────────────────────────────────────
def split_file(filepath: Path):
    global _current_file
    _current_file = filepath.name
    log.info(f"Split: analizando {filepath.name}")
    notify_discord(f"✂️ Separando pistas: `{filepath.name}`")

    try:
        data = probe(filepath)
    except Exception as e:
        notify_discord(f"❌ Error al analizar `{filepath.name}`: {e}")
        return

    audio_streams = get_audio_streams(data)
    sub_streams   = get_subtitle_streams(data)
    spa_audio     = find_spanish_audio(audio_streams)
    spa_sub       = find_spanish_subtitle(sub_streams)

    generated = []

    # Versión español
    if spa_audio:
        out_spa     = INPUT_DIR / (filepath.stem + " [SPA].mkv")
        spa_rel_idx = next((i for i, s in enumerate(audio_streams) if s["index"] == spa_audio["index"]), 0)
        cmd = [
            "ffmpeg", "-y", "-i", str(filepath),
            "-map", "0:v:0", "-map", f"0:a:{spa_rel_idx}",
            "-c", "copy", str(out_spa)
        ]
        rc, stderr = run_ffmpeg(cmd)
        if rc == 0:
            generated.append(out_spa.name)
            log.info(f"SPA generado: {out_spa.name}")
        elif _stop_now.is_set():
            out_spa.unlink(missing_ok=True)
            log.warning("Split cancelado por el usuario")
            return
        else:
            log.error(f"Error SPA: {stderr[-1000:]}")

    # Versión idioma original + subs español
    foreign_audio = find_foreign_audio(audio_streams)
    if foreign_audio:
        lang_tag      = get_lang_tag(foreign_audio)
        out_foreign   = INPUT_DIR / (filepath.stem + f" [{lang_tag}+SUB].mkv")
        foreign_rel   = next((i for i, s in enumerate(audio_streams) if s["index"] == foreign_audio["index"]), 0)
        cmd = [
            "ffmpeg", "-y", "-i", str(filepath),
            "-map", "0:v:0", "-map", f"0:a:{foreign_rel}",
        ]
        if spa_sub:
            spa_sub_idx = next((i for i, s in enumerate(sub_streams) if s["index"] == spa_sub["index"]), 0)
            cmd += ["-map", f"0:s:{spa_sub_idx}"]
        cmd += ["-c", "copy", str(out_foreign)]
        rc, stderr = run_ffmpeg(cmd)
        if rc == 0:
            generated.append(out_foreign.name)
            log.info(f"{lang_tag} generado: {out_foreign.name}")
        elif _stop_now.is_set():
            out_foreign.unlink(missing_ok=True)
            log.warning("Split cancelado por el usuario")
            return
        else:
            log.error(f"Error {lang_tag}: {stderr[-1000:]}")

    if generated:
        filepath.unlink()
        notify_discord(f"✅ Split completado: {', '.join(f'`{n}`' for n in generated)}")
    else:
        # ── FIX: mover a /failed en vez de dejar en /split ────────────────────
        # Sin esto, en cada restart el encoder reintentaba archivos irrecuperables
        FAILED_DIR.mkdir(parents=True, exist_ok=True)
        dest = FAILED_DIR / filepath.name
        shutil.move(str(filepath), str(dest))
        log.warning(f"Split sin pistas detectadas → movido a /split/failed/: {filepath.name}")
        notify_discord(
            f"⚠️ Split falló para `{filepath.name}` — sin pistas de audio detectadas.\n"
            f"Archivo movido a `/split/failed/` para revisión manual."
        )

# ── Encoder ───────────────────────────────────────────────────────────────────
def process_file(filepath: Path):
    global _current_file
    _current_file = filepath.name
    log.info(f"Procesando: {filepath.name}")
    notify_discord(f"🎬 Procesando: `{filepath.name}`")

    try:
        data = probe(filepath)
    except Exception as e:
        log.error(f"FFprobe falló en {filepath.name}: {e}")
        notify_discord(f"❌ Error al analizar `{filepath.name}`: {e}")
        return

    audio_streams = get_audio_streams(data)
    sub_streams   = get_subtitle_streams(data)

    # Caso 0: multi-audio (SPA + otro idioma) → separar pistas primero
    if find_spanish_audio(audio_streams) and find_foreign_audio(audio_streams):
        log.info("Multi-audio detectado → separando pistas")
        notify_discord(f"✂️ Multi-audio detectado, separando: `{filepath.name}`")
        split_file(filepath)
        return

    output_path   = OUTPUT_DIR / (filepath.stem + ".webm")
    external_srt  = SUBS_DIR / (filepath.stem + ".srt")

    # Caso 1: audio español
    spa_audio = find_spanish_audio(audio_streams)
    if spa_audio:
        audio_idx = spa_audio.get("index", 0)
        audio_rel = next((i for i, s in enumerate(audio_streams) if s["index"] == audio_idx), 0)
        log.info("Audio español → encode directo")
        _encode_and_finish(filepath, output_path, "Completado", audio_index=audio_rel)
        return

    # Caso 2: .srt externo
    if external_srt.exists():
        log.info(f"SRT externo: {external_srt.name}")
        _encode_and_finish(filepath, output_path, "Completado con subs", external_srt=external_srt)
        return

    # Caso 3: subtítulos internos en español
    spa_sub = find_spanish_subtitle(sub_streams)
    if spa_sub:
        sub_idx = next((i for i, s in enumerate(sub_streams) if s["index"] == spa_sub["index"]), 0)
        log.info("Subs internos español → quemando")
        _encode_and_finish(filepath, output_path, "Completado con subs internos", sub_index=sub_idx)
        return

    # Caso 4: una sola pista de audio
    if len(audio_streams) == 1:
        log.info("Una sola pista → encode directo")
        _encode_and_finish(filepath, output_path, "Completado")
        return

    # Caso 5: intervención manual
    pending_path = PENDING_DIR / filepath.name
    shutil.move(str(filepath), str(pending_path))
    log.warning(f"Sin audio/subs en español → pending: {filepath.name}")
    notify_discord(
        f"⚠️ **Intervención requerida**: `{filepath.name}`\n"
        f"No se encontró audio ni subtítulos en español.\n"
        f"Agrega `{filepath.stem}.srt` en `~/cinema/subs/` "
        f"y mueve el archivo de vuelta a `~/cinema/input/`"
    )

# ── Utilidades ────────────────────────────────────────────────────────────────
def get_video_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted([
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    ])

def wait_for_file(path: Path, timeout: int = 300):
    """Espera a que el archivo termine de copiarse (tamaño estable)."""
    prev_size = -1
    elapsed   = 0
    while elapsed < timeout:
        try:
            curr_size = path.stat().st_size
        except FileNotFoundError:
            time.sleep(2); elapsed += 2
            continue
        if curr_size == prev_size and curr_size > 0:
            return
        prev_size = curr_size
        time.sleep(3); elapsed += 3
    log.warning(f"Timeout esperando que {path.name} termine de copiarse")

# ── Split watcher ─────────────────────────────────────────────────────────────
class SplitHandler(FileSystemEventHandler):
    def __init__(self):
        self.processing: set[Path] = set()

    def on_created(self, event):
        if event.is_directory:
            return
        if _paused.is_set():
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            return
        if path in self.processing:
            return

        wait_for_file(path)
        split_event.set()
        self.processing.add(path)

        try:
            split_file(path)
            # Procesar cualquier otro archivo que haya llegado mientras tanto
            while True:
                if _paused.is_set():
                    break
                pending = [f for f in get_video_files(SPLIT_DIR) if f not in self.processing]
                if not pending:
                    break
                for f in pending:
                    wait_for_file(f)
                    self.processing.add(f)
                    try:
                        split_file(f)
                    finally:
                        self.processing.discard(f)
        finally:
            self.processing.discard(path)
            split_event.clear()
            log.info("Split terminado, encoder desbloqueado")

# ── Encoder loop ──────────────────────────────────────────────────────────────
def encoder_loop():
    """Procesa /input uno a uno, bloqueándose mientras haya split activo."""
    while True:
        time.sleep(5)

        # Control remoto: pausar al terminar el encode actual
        if _stop_after.is_set() and not _is_busy():
            _paused.set()
            _stop_after.clear()
            notify_discord("✅ Encoder detenido tras el encode actual. Ya puedes reiniciar.")
        if _paused.is_set():
            continue

        # Bloquear si hay split en curso o archivos aún en /split
        if split_event.is_set() or get_video_files(SPLIT_DIR):
            continue

        files = get_video_files(INPUT_DIR)
        if not files:
            continue

        path = files[0]
        if not path.exists():
            continue

        # Doble check por si el split arrancó entre el if de arriba y aquí
        if split_event.is_set() or get_video_files(SPLIT_DIR):
            continue

        with encoder_lock:
            if path.exists():
                process_file(path)

        if not get_video_files(INPUT_DIR):
            notify_discord(f"<@{DISCORD_USER_ID}> ✅ Cola vacía — no hay más archivos pendientes.")

# ── Procesamiento inicial (al arrancar) ───────────────────────────────────────
def process_split_dir():
    """Procesa lo que haya en /split al iniciar (p.ej. tras un restart)."""
    files = get_video_files(SPLIT_DIR)
    if not files:
        return
    split_event.set()
    log.info(f"Procesando {len(files)} archivo(s) en /split al iniciar")
    for f in files:
        if _paused.is_set():
            break
        wait_for_file(f)
        split_file(f)
    split_event.clear()

def process_input_dir():
    """Procesa lo que haya en /input al iniciar."""
    files = get_video_files(INPUT_DIR)
    if not files:
        return
    log.info(f"Procesando {len(files)} archivo(s) pendiente(s) en /input")
    for f in files:
        if _paused.is_set():
            break
        if f.exists():
            process_file(f)
    if not get_video_files(INPUT_DIR):
        notify_discord(f"<@{DISCORD_USER_ID}> ✅ Cola vacía — no hay más archivos pendientes.")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Crear carpetas necesarias
    for d in [INPUT_DIR, OUTPUT_DIR, PENDING_DIR, SUBS_DIR, SPLIT_DIR, FAILED_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    log.info("Cinema encoder iniciado")
    notify_discord("🟢 Cinema encoder iniciado")

    start_control_server()

    process_split_dir()
    process_input_dir()

    t = threading.Thread(target=encoder_loop, daemon=True)
    t.start()

    log.info("Monitoreando /split")
    handler  = SplitHandler()
    observer = Observer()
    observer.schedule(handler, str(SPLIT_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        log.info("Encoder detenido")

    observer.join()
