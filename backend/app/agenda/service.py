"""The shop's calendar. The agent's tools are thin wrappers around these functions.

Every error is an `ErroAgenda` with a message the agent can say out loud,
so a failed booking turns into "that time was just taken, I have 15:30 or
16:00" instead of a stack trace.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from asyncpg.exceptions import ExclusionViolationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Agendamento, Barbeiro, Servico, StatusAgendamento


class ErroAgenda(Exception):
    """Something the customer can fix; the message is meant to be spoken."""


class HorarioIndisponivel(ErroAgenda):
    def __init__(self, mensagem: str, alternativas: list["Horario"]):
        super().__init__(mensagem)
        self.alternativas = alternativas


@dataclass(frozen=True)
class Horario:
    inicio: datetime
    barbeiro: str


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto.lower().strip()) if unicodedata.category(c) != "Mn"
    )


def normalizar_telefone(telefone: str) -> str:
    digitos = re.sub(r"\D", "", telefone)
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        raise ErroAgenda("Não entendi o telefone. Pode repetir com o DDD?")
    # Brazilian mobiles have 11 digits and start with 9 after the area code; a
    # 10-digit number starting with 9 does not exist. Speech recognition drops
    # digits ("nove nove oito sete seis" heard as "99875"), so refuse it here
    # instead of booking a number nobody answers.
    if len(digitos) == 10 and digitos[2] in "6789":
        raise ErroAgenda("Parece que faltou um número no celular. Pode repetir o telefone com o DDD?")
    return digitos


async def buscar_servico(session: AsyncSession, nome: str) -> Servico:
    servicos = (await session.scalars(select(Servico).where(Servico.ativo))).all()
    alvo = _sem_acento(nome)
    exatos = [s for s in servicos if _sem_acento(s.nome) == alvo]
    parciais = [s for s in servicos if alvo and (alvo in _sem_acento(s.nome) or _sem_acento(s.nome) in alvo)]
    if exatos or len(parciais) == 1:
        return (exatos or parciais)[0]
    nomes = ", ".join(s.nome for s in servicos)
    raise ErroAgenda(f"Não temos o serviço '{nome}'. Os serviços são: {nomes}.")


async def buscar_barbeiro(session: AsyncSession, nome: str | None) -> Barbeiro | None:
    """None (or "qualquer") means any barber will do."""
    if not nome or _sem_acento(nome) in ("qualquer", "qualquer um", "tanto faz", "sem preferencia"):
        return None
    barbeiros = (await session.scalars(select(Barbeiro).where(Barbeiro.ativo))).all()
    for b in barbeiros:
        if _sem_acento(b.nome) == _sem_acento(nome) or _sem_acento(b.nome).split()[0] == _sem_acento(nome):
            return b
    nomes = ", ".join(b.nome for b in barbeiros)
    raise ErroAgenda(f"Não temos barbeiro chamado {nome}. Os barbeiros são: {nomes}.")


async def horarios_livres(
    session: AsyncSession,
    dia: date,
    servico: Servico,
    barbeiro: Barbeiro | None = None,
    *,
    agora: datetime | None = None,
    ignorar: int | None = None,
) -> list[Horario]:
    """Start times where `servico` fits whole inside a barber's shift without
    touching another appointment. One entry per time (first free barber wins)
    when no barber is chosen. `ignorar` skips an appointment being rescheduled."""
    tz = settings.tz
    agora = agora or datetime.now(tz)
    if dia < agora.astimezone(tz).date():
        raise ErroAgenda("Essa data já passou.")
    if dia > agora.astimezone(tz).date() + timedelta(days=settings.horizonte_dias):
        raise ErroAgenda(f"A agenda abre só para os próximos {settings.horizonte_dias} dias.")

    query = select(Barbeiro).where(Barbeiro.ativo).options(selectinload(Barbeiro.expedientes))
    if barbeiro is not None:
        query = query.where(Barbeiro.id == barbeiro.id)
    barbeiros = (await session.scalars(query.order_by(Barbeiro.id))).all()

    comeco_dia = datetime.combine(dia, datetime.min.time(), tz)
    ocupados_q = select(Agendamento.barbeiro_id, Agendamento.inicio, Agendamento.fim).where(
        Agendamento.status == StatusAgendamento.agendado,
        Agendamento.inicio < comeco_dia + timedelta(days=1),
        Agendamento.fim > comeco_dia,
    )
    if ignorar is not None:
        ocupados_q = ocupados_q.where(Agendamento.id != ignorar)
    ocupados: dict[int, list[tuple[datetime, datetime]]] = {}
    for barbeiro_id, inicio, fim in await session.execute(ocupados_q):
        ocupados.setdefault(barbeiro_id, []).append((inicio, fim))

    duracao = timedelta(minutes=servico.duracao_min)
    passo = timedelta(minutes=settings.passo_minutos)
    limite = agora + timedelta(minutes=settings.antecedencia_minutos)
    por_inicio: dict[datetime, str] = {}
    for b in barbeiros:
        for turno in (e for e in b.expedientes if e.dia_semana == dia.weekday()):
            inicio = datetime.combine(dia, turno.inicio, tz)
            fim_turno = datetime.combine(dia, turno.fim, tz)
            while inicio + duracao <= fim_turno:
                fim = inicio + duracao
                livre = inicio >= limite and all(
                    fim <= oi or inicio >= of for oi, of in ocupados.get(b.id, [])
                )
                if livre:
                    por_inicio.setdefault(inicio, b.nome)
                inicio += passo
    return [Horario(i, por_inicio[i]) for i in sorted(por_inicio)]


def _mais_proximos(horarios: list[Horario], alvo: datetime, n: int = 3) -> list[Horario]:
    return sorted(horarios, key=lambda h: abs(h.inicio - alvo))[:n]


def _conflito(exc: IntegrityError) -> bool:
    return isinstance(getattr(exc.orig, "__cause__", None), ExclusionViolationError) or "sem_conflito" in str(exc)


async def _escolher_barbeiro(
    session: AsyncSession,
    servico: Servico,
    inicio: datetime,
    barbeiro: Barbeiro | None,
    agora: datetime | None,
    ignorar: int | None = None,
) -> Barbeiro:
    dia = inicio.astimezone(settings.tz).date()
    livres = await horarios_livres(session, dia, servico, barbeiro, agora=agora, ignorar=ignorar)
    escolhido = next((h for h in livres if h.inicio == inicio), None)
    if escolhido is None:
        quem = f" com o {barbeiro.nome}" if barbeiro else ""
        raise HorarioIndisponivel(
            f"Esse horário não está livre{quem}.", _mais_proximos(livres, inicio)
        )
    if barbeiro is not None:
        return barbeiro
    return await session.scalar(select(Barbeiro).where(Barbeiro.nome == escolhido.barbeiro))


async def agendar(
    session: AsyncSession,
    *,
    nome: str,
    telefone: str,
    servico: Servico,
    inicio: datetime,
    barbeiro: Barbeiro | None = None,
    conversa_id: uuid.UUID | None = None,
    agora: datetime | None = None,
) -> Agendamento:
    if not nome.strip():
        raise ErroAgenda("Qual é o seu nome?")
    telefone = normalizar_telefone(telefone)
    escolhido = await _escolher_barbeiro(session, servico, inicio, barbeiro, agora)
    agendamento = Agendamento(
        cliente_nome=nome.strip().title(),
        cliente_telefone=telefone,
        servico=servico,
        barbeiro=escolhido,
        inicio=inicio,
        fim=inicio + timedelta(minutes=servico.duracao_min),
        conversa_id=conversa_id,
    )
    session.add(agendamento)
    # A rollback expires every loaded object; reading one afterwards would need
    # lazy IO, which async SQLAlchemy forbids. Keep the ids to reload them.
    servico_id, barbeiro_id = servico.id, barbeiro.id if barbeiro else None
    try:
        await session.commit()
    except IntegrityError as exc:
        # Someone else took it between our check and the insert.
        await session.rollback()
        if not _conflito(exc):
            raise
        servico = await session.get(Servico, servico_id)
        barbeiro = await session.get(Barbeiro, barbeiro_id) if barbeiro_id else None
        livres = await horarios_livres(session, inicio.astimezone(settings.tz).date(), servico, barbeiro, agora=agora)
        raise HorarioIndisponivel("Esse horário acabou de ser ocupado.", _mais_proximos(livres, inicio)) from exc
    return agendamento


async def agendamentos_do_cliente(
    session: AsyncSession, telefone: str, *, agora: datetime | None = None
) -> list[Agendamento]:
    agora = agora or datetime.now(settings.tz)
    return list(
        (
            await session.scalars(
                select(Agendamento)
                .where(
                    Agendamento.cliente_telefone == normalizar_telefone(telefone),
                    Agendamento.status == StatusAgendamento.agendado,
                    Agendamento.inicio >= agora,
                )
                .order_by(Agendamento.inicio)
            )
        ).all()
    )


async def _do_cliente(session: AsyncSession, agendamento_id: int, telefone: str) -> Agendamento:
    agendamento = await session.get(Agendamento, agendamento_id)
    # Same message for "doesn't exist" and "not yours": no probing other people's bookings.
    if (
        agendamento is None
        or agendamento.cliente_telefone != normalizar_telefone(telefone)
        or agendamento.status != StatusAgendamento.agendado
    ):
        raise ErroAgenda("Não encontrei esse agendamento no seu telefone.")
    return agendamento


async def cancelar(
    session: AsyncSession, agendamento_id: int, telefone: str, *, agora: datetime | None = None
) -> Agendamento:
    agendamento = await _do_cliente(session, agendamento_id, telefone)
    agora = agora or datetime.now(settings.tz)
    if agendamento.inicio <= agora:
        raise ErroAgenda("Esse horário já começou, não dá mais para cancelar.")
    agendamento.status = StatusAgendamento.cancelado
    agendamento.cancelado_em = agora
    await session.commit()
    return agendamento


async def remarcar(
    session: AsyncSession,
    agendamento_id: int,
    telefone: str,
    novo_inicio: datetime,
    *,
    barbeiro: Barbeiro | None = None,
    agora: datetime | None = None,
) -> Agendamento:
    """Moves the same row, so the old slot frees up only if the new one is taken."""
    agendamento = await _do_cliente(session, agendamento_id, telefone)
    servico = agendamento.servico
    escolhido = await _escolher_barbeiro(session, servico, novo_inicio, barbeiro, agora, ignorar=agendamento.id)
    agendamento.barbeiro = escolhido
    agendamento.inicio = novo_inicio
    agendamento.fim = novo_inicio + timedelta(minutes=servico.duracao_min)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not _conflito(exc):
            raise
        raise HorarioIndisponivel("Esse horário acabou de ser ocupado.", []) from exc
    return agendamento
