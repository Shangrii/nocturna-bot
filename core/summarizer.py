"""summarizer.py — Resumen de reuniones con un LLM local vía Ollama.

Usa la API HTTP de Ollama (http://127.0.0.1:11434 por defecto): sin cuentas,
sin internet, todo local. Para transcripciones largas hace un resumen por partes
(map-reduce) para no saturar el contexto del modelo en una sola pasada.
"""
import logging

import aiohttp

import config

log = logging.getLogger(__name__)

# Aproximación conservadora (~4 chars por token): troceamos antes de llenar el contexto.
_CHUNK_CHARS = 8000

_SYSTEM = (
    "Eres un asistente que redacta actas de reuniones en español. "
    "Eres claro, conciso y fiel a lo que se dijo. Nunca inventes información."
)

_FINAL_PROMPT = """\
A continuación tienes la transcripción de una reunión (con hablantes y marcas de tiempo).
Redacta un acta en español usando EXACTAMENTE estas secciones en formato Markdown:

## 📋 Resumen
Un párrafo breve con lo esencial de la reunión.

## 🔑 Puntos clave
- Lista con los temas o decisiones más importantes.

## 📝 Notas pedidas
- Lo que alguien pidió anotar explícitamente (dijo "toma nota de…", "anota…", "apunta…").
  Redacta la idea COMPLETA aunque en la transcripción esté partida en varias líneas por
  pausas, e ignora lo que NO sea parte de esa idea. Una viñeta por nota, con quién la pidió.
  Si no hubo ninguna, escribe "Ninguna".

## ✅ Tareas y acuerdos
- Tareas concretas, con responsable si se menciona. Si no hay ninguna, escribe "Ninguna".

Transcripción:
---
{content}
---
"""

_MAP_PROMPT = """\
Resume en español, en viñetas breves, los puntos importantes de este fragmento de una reunión.
Si alguien pide anotar algo explícitamente ("toma nota de…", "apunta…"), inclúyelo COMPLETO
(aunque esté partido por pausas) y marca esa viñeta con "NOTA:". No agregues encabezados ni
introducción, solo las viñetas.

Fragmento:
---
{content}
---
"""


async def _generate(prompt: str, system: str = _SYSTEM) -> str:
    """Llama a Ollama (/api/chat) y devuelve el texto de la respuesta."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    timeout = aiohttp.ClientTimeout(total=600)  # en CPU puede tardar varios minutos
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{config.OLLAMA_HOST}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return data["message"]["content"].strip()


def _chunk(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    """Trocea el texto por líneas, sin cortar a mitad de una intervención."""
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > size:
            chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


async def summarize(transcript: str) -> str:
    """Genera el acta en Markdown a partir de la transcripción completa.

    Para transcripciones largas resume cada parte y luego combina los resúmenes.
    """
    chunks = _chunk(transcript)

    if len(chunks) <= 1:
        return await _generate(_FINAL_PROMPT.format(content=transcript))

    log.info("Transcripción larga: resumiendo en %d partes", len(chunks))
    partials = []
    for i, ch in enumerate(chunks, 1):
        log.info("Resumiendo parte %d/%d", i, len(chunks))
        partials.append(await _generate(_MAP_PROMPT.format(content=ch)))
    return await _generate(_FINAL_PROMPT.format(content="\n".join(partials)))


async def health_check() -> bool:
    """True si Ollama responde. Útil para avisar antes de empezar."""
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{config.OLLAMA_HOST}/api/tags") as resp:
                return resp.status == 200
    except Exception:
        return False
