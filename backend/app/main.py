"""HTTP API: starts calls (LiveKit token + agent dispatch) and feeds the dashboard.

The dashboard is public in the demo and callers may say their real phone
number, so every phone is masked on the way out; the full number stays in
the database for the barbershop.
"""

import re
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from livekit import api
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_session
from app.models import Agendamento, Canal, Conversa, Mensagem, Papel, Servico, StatusAgendamento

app = FastAPI(title="Navalha", docs_url="/api/docs", openapi_url="/api/openapi.json")

LIGACOES_POR_IP = 5  # per window; each call spends shared free-tier quota
JANELA_S = 10 * 60
_ligacoes: dict[str, deque[float]] = defaultdict(deque)
# LiveKit's free plan has 1,000 agent minutes a month: ~30 short calls a day.
_hoje: dict[date, int] = {}

INTERROMPIDA = " [interrompida]"  # suffix the voice recorder adds when the customer cut in
TELEFONE = re.compile(r"(?<!\d)\(?(\d{2})\)?[\s.-]{0,2}(\d{4,5})[\s.-]?(\d{4})(?!\d)")


def mascarar(texto: str) -> str:
    """'11 98765-4321' → '(11) 9••••-4321'."""

    def troca(m: re.Match) -> str:
        meio = m.group(2)
        return f"({m.group(1)}) {meio[0]}{'•' * (len(meio) - 1)}-{m.group(3)}"

    return TELEFONE.sub(troca, texto)


class Ligacao(BaseModel):
    url: str
    token: str
    sala: str


@app.post("/api/ligacao", response_model=Ligacao)
async def ligar(request: Request) -> Ligacao:
    hoje = datetime.now(settings.tz).date()
    if _hoje.get(hoje, 0) >= settings.ligacoes_por_dia:
        raise HTTPException(429, "A recepção da demo atingiu o limite de ligações de hoje. Volte amanhã!")
    # Behind Vercel's rewrite the socket peer is Vercel; the visitor is the first hop.
    encaminhado = request.headers.get("x-forwarded-for", "")
    ip = encaminhado.split(",")[0].strip() or (request.client.host if request.client else "?")
    agora = time.monotonic()
    fila = _ligacoes[ip]
    while fila and agora - fila[0] > JANELA_S:
        fila.popleft()
    if len(fila) >= LIGACOES_POR_IP:
        raise HTTPException(429, "Muitas ligações seguidas. Tente de novo em alguns minutos.")
    fila.append(agora)
    if hoje not in _hoje:
        _hoje.clear()  # a new day: yesterday's count goes away
    _hoje[hoje] = _hoje.get(hoje, 0) + 1

    sala = f"ligacao-{uuid.uuid4().hex[:10]}"
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(f"cliente-{uuid.uuid4().hex[:6]}")
        .with_name("Cliente")
        .with_ttl(timedelta(minutes=15))
        .with_grants(api.VideoGrants(room_join=True, room=sala, can_publish=True, can_subscribe=True))
        # Joining the room is what calls the receptionist in.
        .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=settings.nome_agente)]))
        .to_jwt()
    )
    return Ligacao(url=settings.livekit_url, token=token, sala=sala)


@app.get("/api/servicos")
async def servicos(session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (await session.scalars(select(Servico).where(Servico.ativo).order_by(Servico.id))).all()
    return [{"nome": s.nome, "duracao_min": s.duracao_min, "preco_centavos": s.preco_centavos} for s in rows]


@app.get("/api/agenda")
async def agenda(dia: date | None = None, dias: int = 7, session: AsyncSession = Depends(get_session)) -> list[dict]:
    inicio = datetime.combine(dia or datetime.now(settings.tz).date(), datetime.min.time(), settings.tz)
    rows = (
        await session.scalars(
            select(Agendamento)
            .where(
                Agendamento.status == StatusAgendamento.agendado,
                Agendamento.inicio >= inicio,
                Agendamento.inicio < inicio + timedelta(days=min(dias, 31)),
            )
            .order_by(Agendamento.inicio)
        )
    ).all()
    return [
        {
            "id": a.id,
            "inicio": a.inicio.astimezone(settings.tz).isoformat(),
            "fim": a.fim.astimezone(settings.tz).isoformat(),
            "cliente": a.cliente_nome,
            "telefone": mascarar(a.cliente_telefone),
            "servico": a.servico.nome,
            "barbeiro": a.barbeiro.nome,
            "pela_recepcionista": a.conversa_id is not None,
        }
        for a in rows
    ]


@app.get("/api/conversas")
async def conversas(limite: int = 20, session: AsyncSession = Depends(get_session)) -> list[dict]:
    falas = (
        select(
            Mensagem.conversa_id,
            func.count().label("n"),
            func.count().filter(Mensagem.papel == Papel.cliente).label("cliente"),
        )
        .where(Mensagem.papel != Papel.ferramenta)
        .group_by(Mensagem.conversa_id)
        .subquery()
    )
    agendou = select(Agendamento.conversa_id).where(Agendamento.conversa_id.is_not(None))
    rows = (
        await session.execute(
            select(Conversa, falas.c.n, Conversa.id.in_(agendou))
            .join(falas, falas.c.conversa_id == Conversa.id)
            # Calls where the customer never spoke (mic denied, tab closed after the
            # greeting) are noise on the dashboard.
            .where(Conversa.canal != Canal.eval, falas.c.cliente > 0)
            .order_by(Conversa.iniciada_em.desc())
            .limit(min(limite, 100))
        )
    ).all()
    return [
        {
            "id": str(c.id),
            "canal": c.canal.value,
            "iniciada_em": c.iniciada_em.astimezone(settings.tz).isoformat(),
            "duracao_s": c.duracao_s,
            "latencia_media_ms": c.latencia_media_ms,
            "custo_usd": float(c.custo_usd),
            "falas": n,
            "agendou": bool(fez),
        }
        for c, n, fez in rows
    ]


@app.get("/api/resumo")
async def resumo(session: AsyncSession = Depends(get_session)) -> dict:
    """Headline numbers for the dashboard, over every real call."""
    com_cliente = (
        select(Mensagem.conversa_id).where(Mensagem.papel == Papel.cliente).distinct().scalar_subquery()
    )
    reais = select(Conversa).where(Conversa.canal != Canal.eval, Conversa.id.in_(com_cliente)).subquery()
    ligacoes, latencia, custo = (
        await session.execute(
            select(func.count(), func.avg(reais.c.latencia_media_ms), func.avg(reais.c.custo_usd))
        )
    ).one()
    agendados = await session.scalar(
        select(func.count()).select_from(Agendamento).where(Agendamento.conversa_id.in_(select(reais.c.id)))
    )
    return {
        "ligacoes": ligacoes,
        "agendamentos_pela_ia": agendados,
        "latencia_media_ms": round(latencia) if latencia is not None else None,
        "custo_medio_usd": round(float(custo), 4) if custo is not None else None,
    }


@app.get("/api/conversas/{conversa_id}")
async def conversa(conversa_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> dict:
    c = await session.get(Conversa, conversa_id)
    if c is None or c.canal == Canal.eval:
        raise HTTPException(404, "Conversa não encontrada")
    msgs = (await session.scalars(select(Mensagem).where(Mensagem.conversa_id == c.id).order_by(Mensagem.id))).all()
    return {
        "id": str(c.id),
        "iniciada_em": c.iniciada_em.astimezone(settings.tz).isoformat(),
        "duracao_s": c.duracao_s,
        "latencia_media_ms": c.latencia_media_ms,
        "tokens": c.tokens_entrada + c.tokens_saida,
        "custo_usd": float(c.custo_usd),
        "mensagens": [
            {
                "papel": m.papel.value,
                "texto": mascarar(m.conteudo.removesuffix(INTERROMPIDA)),
                "interrompida": m.conteudo.endswith(INTERROMPIDA),
                "ferramenta": m.ferramenta,
                "latencia_ms": m.latencia_ms,
                "em": m.created_at.astimezone(settings.tz).isoformat(),
            }
            for m in msgs
        ],
    }
