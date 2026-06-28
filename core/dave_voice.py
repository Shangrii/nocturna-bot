"""dave_voice.py — Grabación de voz con descifrado DAVE (E2EE) para discord.py.

Desde marzo 2026 Discord exige cifrado de extremo a extremo (protocolo DAVE) en los
canales de voz. discord.py 2.7+ establece la sesión MLS (vía `davey`) pero no recibe
audio, y las librerías de recepción (discord-ext-voice-recv) no descifran DAVE — por eso
el audio entrante salía como "corrupted stream". Este módulo cierra ese hueco:

  1. Pide el opus SIN decodificar (wants_opus=True) → bajo DAVE es el frame cifrado.
  2. Lo descifra con la sesión DAVE viva de discord.py:
         voice_client._connection.dave_session.decrypt(user_id, MediaType.audio, frame)
     (OJO: davey espera user_id como int, no str.)
  3. Lo decodifica a PCM y lo escribe en un WAV por usuario, alineado en el tiempo.

Hasta donde sabemos, es el primer DAVE-recibir funcional en Python. Se apoya en
`davey` (Snazzah), `dave.py`/`libdave` (DisnakeDev) y discord-ext-voice-recv.
"""
import logging
import time
import wave
from pathlib import Path

import discord
import discord.opus
from discord.ext import voice_recv

log = logging.getLogger(__name__)

_SILENCE_FRAME = b"\xf8\xff\xfe"  # frame de silencio de Discord (no se descifra)


def _audio_media_type():
    """Miembro MediaType de audio de davey (el nombre se resuelve en runtime)."""
    try:
        import davey
        mt = davey.MediaType
        return getattr(mt, "AUDIO", None) or getattr(mt, "audio", None)
    except Exception:
        return None


class DaveVoiceRecorder(voice_recv.AudioSink):
    """Graba una pista WAV por usuario (48 kHz, estéreo), descifrando DAVE en el camino.

    Las pistas se rellenan con silencio para que todas compartan la misma línea de
    tiempo (así se puede ordenar quién habló cuándo).
    """

    SAMPLE_RATE = 48000
    CHANNELS = 2
    SAMPLE_WIDTH = 2
    BYTES_PER_SEC = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH  # 192000
    FRAME = CHANNELS * SAMPLE_WIDTH                        # bytes por muestra (todos los canales)

    def __init__(self, out_dir: Path):
        super().__init__()
        self.out_dir = out_dir
        self.start = time.monotonic()
        self.users: dict[int, dict] = {}  # user_id -> {name, wav, path, written, decoder, ok, fail}
        self._closed = False
        self._media_audio = _audio_media_type()
        self._diag_logged = False
        self._last_epoch = None
        self._decrypt_fail = 0

    def wants_opus(self) -> bool:
        return True  # recibimos el frame sin decodificar para descifrar DAVE nosotros

    def _dave_session(self):
        """Busca la sesión DAVE de discord.py probando varias rutas de acceso."""
        vc = getattr(self, "voice_client", None)
        for attr in ("_connection", "connection", "_state"):
            ds = getattr(getattr(vc, attr, None), "dave_session", None)
            if ds is not None:
                return ds
        return getattr(vc, "dave_session", None)

    def write(self, user, data) -> None:
        if user is None:
            return
        frame = getattr(data, "opus", None)
        if not frame or frame == _SILENCE_FRAME:
            return

        session = self._dave_session()

        if not self._diag_logged:
            self._diag_logged = True
            log.info("DAVE diag → session=%r ready=%s media_audio=%r",
                     session, getattr(session, "ready", None), self._media_audio)

        if session is not None:
            # Registrar cambios de epoch (entradas/salidas re-generan llaves)
            epoch = getattr(session, "epoch", None)
            if epoch != self._last_epoch:
                log.info("DAVE epoch: %s → %s", self._last_epoch, epoch)
                self._last_epoch = epoch

            if not getattr(session, "ready", False):
                return  # handshake MLS aún no listo
            try:
                # davey espera user_id como ENTERO (no str, pese a las docs JS)
                frame = session.decrypt(user.id, self._media_audio, frame)
            except Exception as e:
                self._decrypt_fail += 1
                if self._decrypt_fail <= 3 or self._decrypt_fail % 200 == 0:
                    log.warning("DAVE decrypt #%d falló (%s, epoch=%s): %r",
                                self._decrypt_fail, getattr(user, "display_name", user),
                                getattr(session, "epoch", None), e)
                return
            if not frame:
                self._decrypt_fail += 1
                return

        u = self.users.get(user.id)
        if u is None:
            path = self.out_dir / f"{user.id}.wav"
            wav = wave.open(str(path), "wb")
            wav.setnchannels(self.CHANNELS)
            wav.setsampwidth(self.SAMPLE_WIDTH)
            wav.setframerate(self.SAMPLE_RATE)
            u = {"name": user.display_name, "wav": wav, "path": path, "written": 0,
                 "decoder": discord.opus.Decoder(), "ok": 0, "fail": 0}
            self.users[user.id] = u

        # Decodificar el opus ya limpio → PCM
        try:
            pcm = u["decoder"].decode(frame, fec=False)
        except Exception as e:
            u["fail"] += 1
            if u["fail"] <= 3:
                log.warning("Opus decode falló (%s): %r", u["name"], e)
            return
        u["ok"] += 1

        # Rellenar el hueco de silencio desde lo último escrito hasta "ahora".
        elapsed = time.monotonic() - self.start
        gap = int(elapsed * self.BYTES_PER_SEC) - u["written"] - len(pcm)
        if gap > 0:
            gap -= gap % self.FRAME  # alinear a muestra entera
            u["wav"].writeframes(b"\x00" * gap)
            u["written"] += gap

        u["wav"].writeframes(pcm)
        u["written"] += len(pcm)

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        for u in self.users.values():
            log.info("Pista %s: %d frames OK, %d con error", u["name"], u["ok"], u["fail"])
            try:
                u["wav"].close()
            except Exception:
                pass
        if self._decrypt_fail:
            log.info("DAVE: %d frames no descifrados en total", self._decrypt_fail)
