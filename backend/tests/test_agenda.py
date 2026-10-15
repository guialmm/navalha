import asyncio
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.agenda.service import (
    ErroAgenda,
    HorarioIndisponivel,
    agendamentos_do_cliente,
    agendar,
    buscar_barbeiro,
    buscar_servico,
    cancelar,
    horarios_livres,
    normalizar_telefone,
    remarcar,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Agendamento, StatusAgendamento

TZ = settings.tz
TERCA = date(2026, 10, 20)  # Rafael and Bruno 9-12 and 13-19; Diego off
AGORA = datetime(2026, 10, 19, 18, 0, tzinfo=TZ)  # Monday evening, before Tuesday opens


def as_(h: int, m: int = 0, dia: date = TERCA) -> datetime:
    return datetime.combine(dia, time(h, m), TZ)


async def marcar(session, inicio, servico="Corte", barbeiro=None, telefone="11 98888-7777", nome="ana"):
    return await agendar(
        session,
        nome=nome,
        telefone=telefone,
        servico=await buscar_servico(session, servico),
        inicio=inicio,
        barbeiro=await buscar_barbeiro(session, barbeiro),
        agora=AGORA,
    )


async def test_free_slots_follow_shifts_lunch_and_service_length(session):
    corte_barba = await buscar_servico(session, "corte e barba")  # 60 min
    rafael = await buscar_barbeiro(session, "Rafael")
    livres = [h.inicio for h in await horarios_livres(session, TERCA, corte_barba, rafael, agora=AGORA)]

    assert livres[0] == as_(9) and as_(11) in livres
    assert as_(11, 15) not in livres  # would run into lunch at 12:00
    assert as_(12) not in livres and as_(12, 30) not in livres
    assert as_(13) in livres and livres[-1] == as_(18)


async def test_booked_time_disappears_only_for_that_barber(session):
    await marcar(session, as_(10), barbeiro="Rafael")
    corte = await buscar_servico(session, "corte")
    rafael = await buscar_barbeiro(session, "rafael")
    so_rafael = {h.inicio for h in await horarios_livres(session, TERCA, corte, rafael, agora=AGORA)}
    assert as_(10) not in so_rafael and as_(9, 45) not in so_rafael and as_(10, 30) in so_rafael

    qualquer = {h.inicio: h.barbeiro for h in await horarios_livres(session, TERCA, corte, agora=AGORA)}
    assert qualquer[as_(10)] == "Bruno"  # still free with someone else


async def test_no_slots_too_soon_in_the_past_or_on_a_day_off(session):
    corte = await buscar_servico(session, "corte")
    quase = datetime(2026, 10, 20, 9, 50, tzinfo=TZ)
    livres = [h.inicio for h in await horarios_livres(session, TERCA, corte, agora=quase)]
    assert livres[0] == as_(10, 30)  # 30 minutes' notice
    with pytest.raises(ErroAgenda, match="já passou"):
        await horarios_livres(session, date(2026, 10, 18), corte, agora=AGORA)
    with pytest.raises(ErroAgenda, match="próximos 30 dias"):
        await horarios_livres(session, TERCA + timedelta(days=40), corte, agora=AGORA)
    domingo = date(2026, 10, 25)
    assert await horarios_livres(session, domingo, corte, agora=AGORA) == []


async def test_booking_picks_a_free_barber_and_normalizes_the_customer(session):
    a = await marcar(session, as_(15), telefone="+55 (11) 98888-7777", nome="  joão silva ")
    assert (a.cliente_nome, a.cliente_telefone, a.barbeiro.nome) == ("João Silva", "11988887777", "Rafael")
    assert a.fim == as_(15, 30)
    b = await marcar(session, as_(15), telefone="21 3333-4444")
    assert b.barbeiro.nome == "Bruno"


async def test_taken_time_is_refused_with_the_nearest_alternatives(session):
    await marcar(session, as_(10), barbeiro="Rafael")
    with pytest.raises(HorarioIndisponivel) as exc:
        await marcar(session, as_(10), barbeiro="Rafael", telefone="21 99999-0000")
    assert "Rafael" in str(exc.value)
    assert [h.inicio for h in exc.value.alternativas] == [as_(9, 30), as_(10, 30), as_(9, 15)]


async def test_time_outside_the_grid_or_shift_is_refused(session):
    with pytest.raises(HorarioIndisponivel):
        await marcar(session, as_(10, 7))  # not on the 15-minute grid
    with pytest.raises(HorarioIndisponivel):
        await marcar(session, as_(20))  # after closing


async def test_two_calls_racing_for_the_last_slot_only_one_wins(monkeypatch):
    """Every call passes the availability check before any of them writes:
    only the exclusion constraint can stop the duplicates."""
    import app.agenda.service as agenda

    async with SessionLocal() as s:
        for h in range(9, 19):  # fill Bruno's day so Rafael's 10:00 is the only fight
            if h != 12:
                await marcar(s, as_(h), barbeiro="Bruno", telefone=f"11 9{h:02d}00-0000")
                await marcar(s, as_(h, 30), barbeiro="Bruno", telefone=f"11 9{h:02d}11-0000")

    barreira = asyncio.Barrier(5)
    original = agenda._escolher_barbeiro

    async def checa_e_espera(*args, **kwargs):
        escolhido = await original(*args, **kwargs)
        await barreira.wait()  # all five saw the slot as free
        return escolhido

    monkeypatch.setattr(agenda, "_escolher_barbeiro", checa_e_espera)

    async def ligacao(telefone):
        async with SessionLocal() as s:
            try:
                return await marcar(s, as_(10), barbeiro="Rafael", telefone=telefone)
            except HorarioIndisponivel as exc:
                return exc

    resultados = await asyncio.gather(*(ligacao(f"31 9{n:04d}-1111") for n in range(5)))
    venceram = [r for r in resultados if isinstance(r, Agendamento)]
    assert len(venceram) == 1
    perderam = [r for r in resultados if r not in venceram]
    assert all("acabou de ser ocupado" in str(r) for r in perderam)
    # The losers still get something to offer the customer instead of a dead end.
    assert all(r.alternativas and as_(10) not in [h.inicio for h in r.alternativas] for r in perderam)


async def test_exclusion_constraint_holds_even_without_the_service_layer(session):
    from sqlalchemy.exc import IntegrityError

    a = await marcar(session, as_(10), barbeiro="Rafael")
    session.add(
        Agendamento(
            cliente_nome="X", cliente_telefone="11999990000", servico_id=a.servico_id,
            barbeiro_id=a.barbeiro_id, inicio=as_(10, 15), fim=as_(10, 45),
        )
    )
    with pytest.raises(IntegrityError, match="sem_conflito"):
        await session.commit()


async def test_cancel_frees_the_slot_and_requires_the_same_phone(session):
    a = await marcar(session, as_(10), barbeiro="Rafael")
    with pytest.raises(ErroAgenda, match="Não encontrei"):
        await cancelar(session, a.id, "21 99999-0000", agora=AGORA)
    await cancelar(session, a.id, "(11) 98888-7777", agora=AGORA)
    assert a.status == StatusAgendamento.cancelado
    b = await marcar(session, as_(10), barbeiro="Rafael", telefone="21 99999-0000")
    assert b.id != a.id
    with pytest.raises(ErroAgenda, match="Não encontrei"):  # cancelling twice
        await cancelar(session, a.id, "11 98888-7777", agora=AGORA)


async def test_started_appointment_cannot_be_cancelled(session):
    a = await marcar(session, as_(10))
    with pytest.raises(ErroAgenda, match="já começou"):
        await cancelar(session, a.id, "11988887777", agora=as_(10, 5))


async def test_reschedule_moves_the_booking_and_keeps_it_if_the_new_time_is_taken(session):
    a = await marcar(session, as_(10), barbeiro="Rafael")
    await marcar(session, as_(16), barbeiro="Rafael", telefone="21 99999-0000")

    with pytest.raises(HorarioIndisponivel):
        await remarcar(session, a.id, "11988887777", as_(16), barbeiro=await buscar_barbeiro(session, "Rafael"), agora=AGORA)
    await session.refresh(a)
    assert a.inicio == as_(10)  # untouched

    movido = await remarcar(session, a.id, "11988887777", as_(10, 15), barbeiro=await buscar_barbeiro(session, "Rafael"), agora=AGORA)
    assert (movido.id, movido.inicio, movido.fim) == (a.id, as_(10, 15), as_(10, 45))  # overlaps its own old slot: fine


async def test_customer_sees_only_future_active_bookings(session):
    a = await marcar(session, as_(10))
    b = await marcar(session, as_(15))
    await marcar(session, as_(11), telefone="21 99999-0000")
    await cancelar(session, b.id, "11988887777", agora=AGORA)
    assert [x.id for x in await agendamentos_do_cliente(session, "11 98888-7777", agora=AGORA)] == [a.id]


async def test_lookup_helpers_understand_spoken_names(session):
    assert (await buscar_servico(session, "corte e barba")).nome == "Corte e barba"
    assert (await buscar_servico(session, "SOBRANCELHA")).nome == "Sobrancelha"
    with pytest.raises(ErroAgenda, match="Os serviços são"):
        await buscar_servico(session, "luzes")
    assert await buscar_barbeiro(session, "tanto faz") is None
    assert (await buscar_barbeiro(session, "diego")).nome == "Diego"
    with pytest.raises(ErroAgenda, match="Os barbeiros são"):
        await buscar_barbeiro(session, "Carlos")


@pytest.mark.parametrize("bruto,limpo", [("(11) 98888-7777", "11988887777"), ("+55 21 3333-4444", "2133334444")])
def test_phone_normalization(bruto, limpo):
    assert normalizar_telefone(bruto) == limpo


def test_phone_without_area_code_is_refused():
    with pytest.raises(ErroAgenda, match="DDD"):
        normalizar_telefone("98888-7777")
