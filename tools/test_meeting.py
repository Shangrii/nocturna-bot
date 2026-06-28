#!/usr/bin/env python3
"""Prueba la transcripción y el resumen SIN Discord.

Sirve para validar en el servidor que faster-whisper y Ollama funcionan antes de
grabar una reunión de verdad.

Uso (desde la raíz del repo):
    python tools/test_meeting.py --ollama      # solo verifica que Ollama responde
    python tools/test_meeting.py audio.wav     # transcribe y resume un audio
"""
import asyncio
import pathlib
import sys

# Permite ejecutar el script desde tools/ resolviendo el paquete core/ de la raíz
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core import summarizer, transcription


async def main():
    if "--ollama" in sys.argv:
        ok = await summarizer.health_check()
        print("Ollama:", "✅ responde" if ok else "❌ no responde (¿está corriendo?)")
        return

    if len(sys.argv) < 2:
        print(__doc__)
        return

    audio = sys.argv[1]
    print(f"⏳ Transcribiendo {audio} ...")
    segments = transcription.transcribe(audio)
    transcript = "\n".join(f"[{s:6.1f}s] {text}" for s, _e, text in segments)
    print("\n── Transcripción ──")
    print(transcript or "(sin texto detectado)")

    if not transcript:
        return

    print("\n⏳ Resumiendo con Ollama ...")
    try:
        print("\n── Acta ──")
        print(await summarizer.summarize(transcript))
    except Exception as e:
        print(f"❌ Error al resumir: {e}")


if __name__ == "__main__":
    asyncio.run(main())
