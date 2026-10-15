"""The tools the model may call, shared by the text agent and the voice agent.

Inputs are what a model produces from speech ("2026-10-20", "14h30", "tanto
faz"); outputs are small JSON-able dicts. A tool never raises: a refusal comes
back as {"erro": "<sentence the agent can say>"} so the conversation goes on.
Every call is logged with its arguments and result.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agenda import service as agenda
from app.agenda.service import ErroAgenda, HorarioIndisponivel
from app.core.config import settings
from app.models import Agendamento, Barbeiro, Mensagem, Papel, Servico

DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MAX_HORARIOS = 40


def _data(valor: str) -> date:
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        raise ErroAgenda("Não entendi a data.") from None


def _hora(valor: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2})\s*(?:[:h]\s*(\d{2})?)?\s*", valor.lower())
    if not m or int(m.group(1)) > 23:
        raise ErroAgenda("Não entendi o horário.")
    return time(int(m.group(1)), int(m.group(2) or 0))


def _quando(dia: str, hora: str) -> datetime:
    return datetime.combine(_data(dia), _hora(hora), settings.tz)


def _descrever(a: Agendamento) -> dict:
    inicio = a.inicio.astimezone(settings.tz)
    return {
        "agendamento_id": a.id,
        "servico": a.servico.nome,
        "barbeiro": a.barbeiro.nome,
        "data": inicio.date().isoformat(),
        "dia_da_semana": DIAS[inicio.weekday()],
        "hora": inicio.strftime("%H:%M"),
        "cliente": a.cliente_nome,
    }


def _alternativas(exc: HorarioIndisponivel) -> list[dict]:
    return [
        {"data": h.inicio.date().isoformat(), "hora": h.inicio.strftime("%H:%M"), "barbeiro": h.barbeiro}
        for h in exc.alternativas
    ]


class Ferramentas:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        conversa_id: uuid.UUID | None = None,
        agora: Callable[[], datetime] = lambda: datetime.now(settings.tz),
    ):
        self.sessions = sessions
        self.conversa_id = conversa_id
        self.agora = agora

    async def _executar(self, nome: str, args: dict, fn: Callable[[AsyncSession], Awaitable[dict]]) -> dict:
        async with self.sessions() as session:
            try:
                resultado = await fn(session)
            except HorarioIndisponivel as exc:
                await session.rollback()
                resultado = {"erro": str(exc), "alternativas": _alternativas(exc)}
            except ErroAgenda as exc:
                await session.rollback()
                resultado = {"erro": str(exc)}
            if self.conversa_id is not None:
                session.add(
                    Mensagem(
                        conversa_id=self.conversa_id,
                        papel=Papel.ferramenta,
                        conteudo=resultado.get("erro") or "ok",
                        ferramenta=nome,
                        dados={"argumentos": args, "resultado": resultado},
                    )
                )
                await session.commit()
        return resultado

    async def listar_servicos(self) -> dict:
        async def fn(session):
            servicos = (await session.scalars(select(Servico).where(Servico.ativo).order_by(Servico.id))).all()
            barbeiros = (await session.scalars(select(Barbeiro).where(Barbeiro.ativo).order_by(Barbeiro.id))).all()
            return {
                "servicos": [
                    {"nome": s.nome, "duracao_min": s.duracao_min, "preco": f"R$ {s.preco_centavos / 100:.2f}".replace(".", ",")}
                    for s in servicos
                ],
                "barbeiros": [b.nome for b in barbeiros],
            }

        return await self._executar("listar_servicos", {}, fn)

    async def listar_horarios(self, data: str, servico: str, barbeiro: str | None = None) -> dict:
        args = {"data": data, "servico": servico, "barbeiro": barbeiro}

        async def fn(session):
            dia = _data(data)
            s = await agenda.buscar_servico(session, servico)
            b = await agenda.buscar_barbeiro(session, barbeiro)
            livres = await agenda.horarios_livres(session, dia, s, b, agora=self.agora())
            return {
                "data": dia.isoformat(),
                "dia_da_semana": DIAS[dia.weekday()],
                "servico": s.nome,
                "barbeiro": b.nome if b else "qualquer",
                "horarios": [
                    {"hora": h.inicio.strftime("%H:%M"), "barbeiro": h.barbeiro} for h in livres[:MAX_HORARIOS]
                ],
                "fechado": not livres,
            }

        return await self._executar("listar_horarios", args, fn)

    async def agendar(
        self, nome: str, telefone: str, servico: str, data: str, hora: str, barbeiro: str | None = None
    ) -> dict:
        args = {"nome": nome, "telefone": telefone, "servico": servico, "data": data, "hora": hora, "barbeiro": barbeiro}

        async def fn(session):
            a = await agenda.agendar(
                session,
                nome=nome,
                telefone=telefone,
                servico=await agenda.buscar_servico(session, servico),
                inicio=_quando(data, hora),
                barbeiro=await agenda.buscar_barbeiro(session, barbeiro),
                conversa_id=self.conversa_id,
                agora=self.agora(),
            )
            return {"agendado": _descrever(a)}

        return await self._executar("agendar", args, fn)

    async def meus_agendamentos(self, telefone: str) -> dict:
        async def fn(session):
            lista = await agenda.agendamentos_do_cliente(session, telefone, agora=self.agora())
            return {"agendamentos": [_descrever(a) for a in lista]}

        return await self._executar("meus_agendamentos", {"telefone": telefone}, fn)

    async def remarcar(
        self, agendamento_id: int, telefone: str, data: str, hora: str, barbeiro: str | None = None
    ) -> dict:
        args = {"agendamento_id": agendamento_id, "telefone": telefone, "data": data, "hora": hora, "barbeiro": barbeiro}

        async def fn(session):
            a = await agenda.remarcar(
                session,
                int(agendamento_id),
                telefone,
                _quando(data, hora),
                barbeiro=await agenda.buscar_barbeiro(session, barbeiro),
                agora=self.agora(),
            )
            return {"remarcado": _descrever(a)}

        return await self._executar("remarcar", args, fn)

    async def cancelar(self, agendamento_id: int, telefone: str) -> dict:
        async def fn(session):
            a = await agenda.cancelar(session, int(agendamento_id), telefone, agora=self.agora())
            return {"cancelado": _descrever(a)}

        return await self._executar("cancelar", {"agendamento_id": agendamento_id, "telefone": telefone}, fn)


# Declarations in the provider-neutral JSON-schema shape both Gemini and LiveKit accept.
DATA = {"type": "string", "description": "Data no formato AAAA-MM-DD"}
HORA = {"type": "string", "description": "Hora no formato HH:MM, ex.: 14:30"}
TELEFONE = {"type": "string", "description": "Telefone do cliente com DDD, só números"}
BARBEIRO = {"type": "string", "description": "Nome do barbeiro; omita se o cliente não tem preferência"}
SERVICO = {"type": "string", "description": "Nome do serviço, como em listar_servicos"}
ID = {"type": "integer", "description": "agendamento_id devolvido por meus_agendamentos"}

DECLARACOES: list[dict[str, Any]] = [
    {
        "name": "listar_servicos",
        "description": "Serviços da barbearia com duração e preço, e os nomes dos barbeiros.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "listar_horarios",
        "description": "Horários livres de um dia para um serviço. Use SEMPRE antes de oferecer ou "
        "confirmar um horário: nunca ofereça horário que não veio daqui.",
        "parameters": {
            "type": "object",
            "properties": {"data": DATA, "servico": SERVICO, "barbeiro": BARBEIRO},
            "required": ["data", "servico"],
        },
    },
    {
        "name": "agendar",
        "description": "Marca o horário. Só chame depois de o cliente confirmar serviço, dia, hora, "
        "nome e telefone.",
        "parameters": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do cliente"},
                "telefone": TELEFONE,
                "servico": SERVICO,
                "data": DATA,
                "hora": HORA,
                "barbeiro": BARBEIRO,
            },
            "required": ["nome", "telefone", "servico", "data", "hora"],
        },
    },
    {
        "name": "meus_agendamentos",
        "description": "Agendamentos futuros do cliente pelo telefone. Use antes de remarcar ou cancelar.",
        "parameters": {"type": "object", "properties": {"telefone": TELEFONE}, "required": ["telefone"]},
    },
    {
        "name": "remarcar",
        "description": "Muda dia/hora de um agendamento existente. Consulte listar_horarios antes.",
        "parameters": {
            "type": "object",
            "properties": {"agendamento_id": ID, "telefone": TELEFONE, "data": DATA, "hora": HORA, "barbeiro": BARBEIRO},
            "required": ["agendamento_id", "telefone", "data", "hora"],
        },
    },
    {
        "name": "cancelar",
        "description": "Cancela um agendamento. Confirme com o cliente antes.",
        "parameters": {
            "type": "object",
            "properties": {"agendamento_id": ID, "telefone": TELEFONE},
            "required": ["agendamento_id", "telefone"],
        },
    },
]
