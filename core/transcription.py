"""transcription.py — Transcripción de voz local con faster-whisper.

El modelo se carga una sola vez (perezosamente) y se reutiliza entre reuniones.
`transcribe()` es BLOQUEANTE (CPU/GPU intensivo): llámalo con `asyncio.to_thread`.

Si la GPU (CUDA) no está disponible o falta una librería, cae automáticamente a CPU
para que la transcripción funcione igual (solo más lento).
"""
import logging
from pathlib import Path

import config

log = logging.getLogger(__name__)

_model = None
_device_used: str | None = None


def _preload_cuda_libs():
    """ctranslate2 no busca libcublas/libcudnn en los paquetes pip `nvidia-*`.
    Las precargamos con RTLD_GLOBAL para que `dlopen` las resuelva.

    `nvidia` es un namespace package (su __file__ es None), así que usamos __path__.
    Cualquier fallo aquí es no-fatal: si no se precargan, caemos a CPU más adelante.
    """
    import ctypes
    import glob
    import os

    try:
        import nvidia
    except ImportError:
        return  # sin paquetes nvidia (ej. instalación CPU)

    try:
        bases = list(getattr(nvidia, "__path__", []) or [])
        if getattr(nvidia, "__file__", None):
            bases.append(os.path.dirname(nvidia.__file__))

        order = ["cublas", "cuda_runtime", "cuda_nvrtc", "cudnn"]
        libs: list[str] = []
        for base in bases:
            for sub in order:
                libs += sorted(glob.glob(os.path.join(base, sub, "lib", "*.so*")))
            libs += sorted(glob.glob(os.path.join(base, "*", "lib", "*.so*")))

        seen = set()
        for so in libs:
            if so in seen:
                continue
            seen.add(so)
            try:
                ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass
    except Exception as e:
        log.debug("Preload de libs CUDA no completado: %s", e)


def _build(device: str, compute: str):
    from faster_whisper import WhisperModel
    return WhisperModel(
        config.WHISPER_MODEL,
        device=device,
        compute_type=compute,
        cpu_threads=config.WHISPER_THREADS,
    )


def _get_model():
    """Carga el modelo Whisper (GPU si se puede, si no CPU) y lo cachea."""
    global _model, _device_used
    if _model is None:
        _preload_cuda_libs()
        try:
            log.info("Cargando Whisper '%s' (%s/%s)...",
                     config.WHISPER_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE)
            _model = _build(config.WHISPER_DEVICE, config.WHISPER_COMPUTE)
            _device_used = config.WHISPER_DEVICE
        except Exception as e:
            if config.WHISPER_DEVICE != "cpu":
                log.warning("Whisper en '%s' falló (%s) → usando CPU", config.WHISPER_DEVICE, e)
                _model = _build("cpu", "int8")
                _device_used = "cpu"
            else:
                raise
        log.info("Whisper cargado en %s", _device_used)
    return _model


def _run(model, path: Path, language: str | None):
    segments, _info = model.transcribe(
        str(path),
        language=language or config.MEETING_LANG,
        beam_size=5,
        vad_filter=True,
        # Más padding alrededor del habla → no recorta inicios/finales de frase.
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=400),
        # Las pistas por usuario tienen silencios largos; no arrastrar contexto entre
        # huecos evita que el modelo "alucine" o derive de un fragmento a otro.
        condition_on_previous_text=False,
        # Sesga hacia el vocabulario/nombres propios del servidor (ej. CachoraBot).
        initial_prompt=config.WHISPER_PROMPT or None,
    )
    # Consumir el generador aquí (es donde realmente corre el cómputo)
    return [(s.start, s.end, s.text.strip()) for s in segments if s.text.strip()]


def transcribe(path: Path, language: str | None = None) -> list[tuple[float, float, str]]:
    """Transcribe un archivo de audio a (inicio, fin, texto) por segmento.

    Si la GPU falla en pleno cómputo (ej. falta una librería CUDA), reconstruye el
    modelo en CPU y reintenta una vez.
    """
    global _model, _device_used
    model = _get_model()
    try:
        return _run(model, path, language)
    except Exception as e:
        if _device_used != "cpu":
            log.warning("Transcripción en '%s' falló (%s) → reintentando en CPU", _device_used, e)
            _model = _build("cpu", "int8")
            _device_used = "cpu"
            return _run(_model, path, language)
        raise
