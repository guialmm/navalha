"""Eval scenarios: a goal for the simulated customer and a check on the database.

The check reads what was actually booked, not what the agent said. "Now" is
fixed (Monday 2026-10-19, 9h) so dates in the personas are stable.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Agendamento, Barbeiro, Mensagem, Papel, Servico, StatusAgendamento

TZ = settings.tz
AGORA = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)  # Monday
TERCA, QUARTA, QUINTA, SABADO = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22), date(2026, 10, 24)

Checagem = Callable[[AsyncSession], Awaitable[tuple[bool, str]]]


@dataclass
class Cenario:
    id: str
    descricao: str
    persona: str
    checar: Checagem
    preparar: Callable[[AsyncSession], Awaitable[None]] | None = None
    max_turnos: int = 10


def em(dia: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(dia, time(h, m), TZ)


async def reservar(session: AsyncSession, nome, telefone, servico, barbeiro, inicio) -> None:
    s = await session.scalar(select(Servico).where(Servico.nome == servico))
    b = await session.scalar(select(Barbeiro).where(Barbeiro.nome == barbeiro))
    session.add(
        Agendamento(
            cliente_nome=nome, cliente_telefone=telefone, servico_id=s.id, barbeiro_id=b.id,
            inicio=inicio, fim=inicio + timedelta(minutes=s.duracao_min),
        )
    )
    await session.commit()


async def ativos(session: AsyncSession, telefone: str | None = None) -> list[Agendamento]:
    q = select(Agendamento).where(Agendamento.status == StatusAgendamento.agendado)
    if telefone:
        q = q.where(Agendamento.cliente_telefone == telefone)
    return list((await session.scalars(q.order_by(Agendamento.id))).all())


def local(a: Agendamento) -> datetime:
    return a.inicio.astimezone(TZ)


def resumo(lista: list[Agendamento]) -> str:
    return "; ".join(f"{a.cliente_telefone} {a.servico.nome} {a.barbeiro.nome} {local(a):%d/%m %H:%M}" for a in lista) or "nenhum"


# --- checks -----------------------------------------------------------------------------


async def _marcar_simples(session):
    lista = await ativos(session, "11977771234")
    ok = (
        len(lista) == 1
        and lista[0].servico.nome == "Corte"
        and local(lista[0]).date() == SABADO
        and local(lista[0]).hour < 12
    )
    return ok, resumo(lista)


async def _horario_ocupado(session):
    lista = await ativos(session, "11933332222")
    ocupado = em(TERCA, 14)
    ok = len(lista) == 1 and not (lista[0].barbeiro.nome == "Rafael" and lista[0].inicio == ocupado)
    return ok, resumo(lista)


async def _muda_de_ideia(session):
    lista = await ativos(session, "11922221111")
    ok = len(lista) == 1 and local(lista[0]) == em(QUARTA, 15) and lista[0].servico.nome == "Barba"
    return ok, resumo(lista)


async def _remarcar(session):
    lista = await ativos(session, "11966665555")
    ok = len(lista) == 1 and lista[0].id == 1 and local(lista[0]).date() == QUINTA and local(lista[0]).hour >= 13
    return ok, resumo(lista)


async def _cancelar_alheio(session):
    ana = await ativos(session, "11955550000")
    return len(ana) == 1, f"agendamento da Ana: {resumo(ana)}"


async def _telefone_incompleto(session):
    todos = await ativos(session)
    ok = [a.cliente_telefone for a in todos] == ["11987654321"]
    return ok, resumo(todos)


async def _fora_do_assunto(session):
    todos = await ativos(session)
    escritas = (
        await session.scalars(
            select(Mensagem.ferramenta).where(
                Mensagem.papel == Papel.ferramenta,
                Mensagem.ferramenta.in_(["agendar", "remarcar", "cancelar"]),
            )
        )
    ).all()
    return not todos and not escritas, f"agendamentos: {resumo(todos)}; escritas: {list(escritas) or 'nenhuma'}"


async def _barbeiro_de_folga(session):
    # Diego is off on Tuesdays; the customer accepts him on Wednesday afternoon.
    todos = await ativos(session, "11944443333")
    ok = (
        len(todos) == 1
        and todos[0].barbeiro.nome == "Diego"
        and local(todos[0]).date() == QUARTA
        and local(todos[0]).hour >= 13
    )
    return ok, resumo(todos)


# --- setups -----------------------------------------------------------------------------


async def _ocupar_rafael_terca_14h(session):
    await reservar(session, "Outro Cliente", "11900001111", "Corte", "Rafael", em(TERCA, 14))


async def _agendamento_para_remarcar(session):
    await reservar(session, "Lucas", "11966665555", "Corte", "Bruno", em(TERCA, 10))


async def _agendamento_da_ana(session):
    await reservar(session, "Ana", "11955550000", "Corte", "Rafael", em(QUARTA, 10))


CENARIOS = [
    Cenario(
        "marcar_simples",
        "Marca um corte no sábado de manhã",
        "Você é a Carla, telefone 11 97777-1234. Quer um corte no sábado de manhã, com "
        "qualquer barbeiro. Aceite o primeiro horário que oferecerem e confirme quando pedirem.",
        _marcar_simples,
    ),
    Cenario(
        "horario_ocupado",
        "Insiste num horário já ocupado",
        "Você é o Rodrigo, telefone 11 93333-2222. Quer um corte com o Rafael na terça às 14h. "
        "Se disserem que não dá, insista uma vez; depois aceite o horário mais próximo que "
        "oferecerem e confirme.",
        _horario_ocupado,
        _ocupar_rafael_terca_14h,
    ),
    Cenario(
        "muda_de_ideia",
        "Troca o horário antes de confirmar",
        "Você é o Felipe, telefone 11 92222-1111. Quer fazer a barba na quarta às 14h. Quando a "
        "recepcionista repetir os dados pedindo confirmação, diga que mudou de ideia e prefere "
        "às 15h do mesmo dia. Confirme o novo horário.",
        _muda_de_ideia,
    ),
    Cenario(
        "remarcar",
        "Remarca de terça para quinta à tarde",
        "Você é o Lucas, telefone 11 96666-5555, e tem um corte marcado na terça às 10h. Quer "
        "passar para quinta-feira à tarde. Aceite o primeiro horário oferecido e confirme.",
        _remarcar,
        _agendamento_para_remarcar,
    ),
    Cenario(
        "cancelar_alheio",
        "Tenta cancelar o horário de outra pessoa",
        "Você é o Pedro, telefone 11 94444-0000. Você acha que tem um corte na quarta às 10h e "
        "quer cancelar. Dê o seu telefone quando pedirem. Se disserem que não acharam, insista "
        "que é na quarta às 10h com o Rafael.",
        _cancelar_alheio,
        _agendamento_da_ana,
    ),
    Cenario(
        "telefone_incompleto",
        "Dita o celular faltando um dígito",
        "Você é a Júlia. Quer um corte na quinta às 16h com qualquer barbeiro. Quando pedirem o "
        "telefone, diga 11 9876-5432 (você esqueceu um número). Se pedirem para repetir, dê o "
        "certo: 11 98765-4321. Confirme quando pedirem.",
        _telefone_incompleto,
    ),
    Cenario(
        "fora_do_assunto",
        "Faz perguntas e desiste sem marcar",
        "Você está só pesquisando. Pergunte quanto custa um corte e se a barbearia vende pomada "
        "para cabelo. Depois agradeça e diga que vai pensar. Não marque nada.",
        _fora_do_assunto,
        max_turnos=6,
    ),
    Cenario(
        "barbeiro_de_folga",
        "Pede um barbeiro no dia de folga dele",
        "Você é o Thiago, telefone 11 94444-3333. Quer cortar com o Diego na terça às 15h. Se o "
        "Diego não puder na terça, aceite marcar com o Diego na quarta à tarde, no primeiro "
        "horário oferecido, e confirme.",
        _barbeiro_de_folga,
    ),
]
