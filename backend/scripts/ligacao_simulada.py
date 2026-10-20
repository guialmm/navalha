"""End-to-end voice check without a microphone.

A synthetic customer (Gemini TTS) joins a LiveKit room, the real agent is
dispatched to it, and the customer speaks each line only after the agent has
finished talking. The transcript comes from the database afterwards.

    python -m scripts.ligacao_simulada "Oi, quero cortar o cabelo amanhã às 15h" "..."
"""

import asyncio
import hashlib
import os
import re
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from google import genai
from google.genai import errors, types
from livekit import api, rtc

from app.core.config import settings

TAXA = 24000  # Gemini TTS outputs 24 kHz mono 16-bit PCM
SILENCIO_FIM_S = 1.6  # agent quiet this long = its turn is over
# The free TTS tier allows 3 requests a minute: keep every line ever synthesized.
CACHE = Path(__file__).parent / ".cache_tts"
# Each TTS model has its own free quota (10 requests/day, 3/minute).
MODELOS_TTS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]


async def sintetizar(client: genai.Client, texto: str) -> np.ndarray:
    arquivo = CACHE / (hashlib.sha256(texto.encode()).hexdigest()[:16] + ".pcm")
    if arquivo.exists():
        return np.frombuffer(arquivo.read_bytes(), dtype=np.int16)
    modelos = list(MODELOS_TTS)
    while modelos:
        try:
            audio = await _sintetizar(client, modelos[0], texto)
            break
        except errors.ClientError as exc:
            if exc.code != 429:
                raise
            if "PerDay" in str(exc):  # today's quota is gone: next model
                modelos.pop(0)
                continue
            espera = float(m.group(1)) if (m := re.search(r"retry in ([0-9.]+)s", str(exc))) else 30
            print(f"  (cota por minuto do TTS: esperando {espera:.0f}s)")
            await asyncio.sleep(espera + 1)
    else:
        raise RuntimeError("todos os modelos de TTS sem cota hoje")
    CACHE.mkdir(exist_ok=True)
    arquivo.write_bytes(audio.tobytes())
    return audio


async def _sintetizar(client: genai.Client, modelo: str, texto: str) -> np.ndarray:
    r = await client.aio.models.generate_content(
        model=modelo,
        contents=texto,  # anything else in here would be spoken too
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck"))
            ),
        ),
    )
    return np.frombuffer(r.candidates[0].content.parts[0].inline_data.data, dtype=np.int16)


class Ouvido:
    """Tracks whether the agent is speaking from its audio energy."""

    def __init__(self):
        self.ultimo_som = 0.0
        self.falou = asyncio.Event()

    async def ouvir(self, track: rtc.Track) -> None:
        async for evento in rtc.AudioStream(track):
            amostras = np.frombuffer(evento.frame.data, dtype=np.int16)
            if amostras.size and np.sqrt(np.mean(amostras.astype(np.float32) ** 2)) > 300:
                self.ultimo_som = time.monotonic()
                self.falou.set()

    async def esperar_fim_da_fala(self, limite_s: float = 45) -> float:
        """Returns seconds until the agent started speaking."""
        inicio = time.monotonic()
        self.falou.clear()
        await asyncio.wait_for(self.falou.wait(), limite_s)
        latencia = time.monotonic() - inicio
        while time.monotonic() - self.ultimo_som < SILENCIO_FIM_S:
            await asyncio.sleep(0.1)
        return latencia


async def main(falas: list[str]) -> None:
    gemini = genai.Client(api_key=settings.gemini_api_key)
    audios = [await sintetizar(gemini, f) for f in falas]

    sala = f"teste-{uuid.uuid4().hex[:8]}"
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity("cliente-simulado")
        .with_grants(api.VideoGrants(room_join=True, room=sala))
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=settings.nome_agente)]))
        .to_jwt()
    )
    room = rtc.Room()
    ouvido = Ouvido()
    room.on("track_subscribed", lambda track, *_: track.kind == rtc.TrackKind.KIND_AUDIO and asyncio.ensure_future(ouvido.ouvir(track)))
    await room.connect(settings.livekit_url, token)
    fonte = rtc.AudioSource(TAXA, 1)
    await room.local_participant.publish_track(
        rtc.LocalAudioTrack.create_audio_track("microfone", fonte),
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )
    print(f"sala {sala}: esperando a recepcionista atender…")
    print(f"  saudação começou em {await ouvido.esperar_fim_da_fala():.1f}s")

    falando = asyncio.Queue()
    fim = asyncio.Event()

    async def microfone():
        """Like a real mic: a steady 20 ms stream, silence whenever nobody speaks."""
        quadro = TAXA // 50
        silencio = np.zeros(quadro, dtype=np.int16).tobytes()
        while not fim.is_set():
            audio = None if falando.empty() else falando.get_nowait()
            if audio is None:
                await fonte.capture_frame(rtc.AudioFrame(silencio, TAXA, 1, quadro))
                continue
            for i in range(0, len(audio), quadro):
                pedaco = np.pad(audio[i : i + quadro], (0, max(0, quadro - len(audio[i : i + quadro]))))
                await fonte.capture_frame(rtc.AudioFrame(pedaco.tobytes(), TAXA, 1, quadro))

    mic = asyncio.create_task(microfone())
    for fala, audio in zip(falas, audios):
        print(f"cliente: {fala}")
        await falando.put(audio)
        await asyncio.sleep(len(audio) / TAXA)
        print(f"  agente começou a responder em {await ouvido.esperar_fim_da_fala():.1f}s")

    fim.set()
    await mic
    await room.disconnect()
    await asyncio.sleep(3)  # let the worker close the call and write the totals


if __name__ == "__main__":
    for chave in ("livekit_url", "livekit_api_key", "livekit_api_secret"):
        os.environ.setdefault(chave.upper(), getattr(settings, chave))
    asyncio.run(main(sys.argv[1:]))
