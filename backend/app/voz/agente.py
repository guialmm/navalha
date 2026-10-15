"""The receptionist on the phone line: LiveKit carries the audio, Gemini Live
listens, decides and speaks, and the tools are the same ones the text agent uses.

    python -m app.voz.agente dev       # worker connected to LiveKit Cloud
    python -m app.voz.agente console   # talk to it through this computer's mic
"""

import json
import logging
import os
from datetime import datetime

from livekit.agents import Agent, AgentServer, AgentSession, JobContext, JobProcess, cli, function_tool
from livekit.agents.llm import ChatMessage
from livekit.plugins import google, silero

from app.agente.ferramentas import DECLARACOES, Ferramentas
from app.agente.instrucoes import instrucoes
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Canal, Conversa, Papel
from app.voz.registro import RegistroVoz

log = logging.getLogger("navalha.voz")
log.setLevel(logging.INFO)
NOME_AGENTE = "recepcionista"



def carregar_vad(proc: JobProcess) -> None:
    """Once per worker process: a local voice-activity detector. Gemini decides
    when to answer; Silero tells us precisely when the customer stopped talking,
    which is where the latency we report starts."""
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(setup_fnc=carregar_vad)


def ferramentas_livekit(ferramentas: Ferramentas) -> list:
    """Wrap each shared tool for LiveKit using the very same JSON schema."""

    def criar(nome: str):
        async def executar(raw_arguments: dict[str, object]) -> str:
            resultado = await getattr(ferramentas, nome)(**raw_arguments)
            return json.dumps(resultado, ensure_ascii=False)

        return executar

    return [function_tool(criar(d["name"]), raw_schema=d) for d in DECLARACOES]


@server.rtc_session(agent_name=NOME_AGENTE)
async def atender(ctx: JobContext) -> None:
    agora = datetime.now(settings.tz)
    async with SessionLocal() as session:
        conversa = Conversa(canal=Canal.voz, iniciada_em=agora, modelo=settings.gemini_modelo_voz)
        session.add(conversa)
        await session.commit()
    registro = RegistroVoz(SessionLocal, conversa.id)
    ferramentas = Ferramentas(SessionLocal, conversa.id)

    sessao = AgentSession(
        vad=ctx.proc.userdata["vad"],
        llm=google.realtime.RealtimeModel(
            model=settings.gemini_modelo_voz,
            voice=settings.gemini_voz,
            language="pt-BR",
            api_key=settings.gemini_api_key,
            temperature=0.4,
        )
    )

    @sessao.on("conversation_item_added")
    def _fala(evento) -> None:
        item = evento.item
        if isinstance(item, ChatMessage) and item.role in ("user", "assistant") and item.text_content:
            papel = Papel.cliente if item.role == "user" else Papel.agente
            registro.fala(papel, item.text_content, interrompida=item.interrupted)

    @sessao.on("user_state_changed")
    def _cliente(evento) -> None:
        if evento.old_state == "speaking":
            registro.cliente_parou(evento.created_at)

    @sessao.on("agent_state_changed")
    def _agente(evento) -> None:
        if evento.new_state == "speaking":
            registro.agente_comecou(evento.created_at)

    @sessao.on("session_usage_updated")
    def _uso(evento) -> None:
        registro.uso(evento.usage.model_usage)

    async def fechar() -> None:
        await registro.encerrar()

    ctx.add_shutdown_callback(fechar)

    await sessao.start(
        agent=Agent(instructions=instrucoes(agora), tools=ferramentas_livekit(ferramentas)),
        room=ctx.room,
    )
    await sessao.generate_reply(
        instructions="Atenda dizendo apenas: 'Barbearia Navalha, tudo bem? Como posso te ajudar?'"
    )


if __name__ == "__main__":
    # The LiveKit SDK reads its credentials from the environment, not from .env.
    for chave in ("livekit_url", "livekit_api_key", "livekit_api_secret"):
        os.environ.setdefault(chave.upper(), getattr(settings, chave))
    cli.run_app(server)
