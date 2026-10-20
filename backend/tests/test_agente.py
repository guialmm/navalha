from datetime import datetime
from types import SimpleNamespace

from google.genai import errors, types
from sqlalchemy import select

import pytest

from app.agente import texto
from app.agente.ferramentas import Ferramentas
from app.agente.texto import DESCULPA, AgenteTexto
from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Agendamento, Conversa, Mensagem, Papel

TZ = settings.tz
AGORA = datetime(2026, 10, 19, 18, 0, tzinfo=TZ)  # Monday evening


@pytest.fixture(autouse=True)
def cotas_zeradas():
    texto.ESGOTADOS.clear()
    yield
    texto.ESGOTADOS.clear()


def ferramentas(conversa_id=None):
    return Ferramentas(SessionLocal, conversa_id, agora=lambda: AGORA)


async def test_listar_horarios_speaks_the_model_language():
    r = await ferramentas().listar_horarios("2026-10-20", "corte", "rafael")
    assert (r["dia_da_semana"], r["servico"], r["barbeiro"]) == ("terça", "Corte", "Rafael")
    assert r["horarios"][0] == {"hora": "09:00", "barbeiro": "Rafael"}
    assert r["fechado"] is False
    domingo = await ferramentas().listar_horarios("2026-10-25", "corte")
    assert domingo["fechado"] is True and domingo["horarios"] == []


async def test_agendar_accepts_spoken_times_and_describes_the_booking():
    r = await ferramentas().agendar("ana", "11 98888-7777", "corte e barba", "2026-10-20", "14h", None)
    assert r["agendado"] | {"agendamento_id": 0} == {
        "agendamento_id": 0, "servico": "Corte e barba", "barbeiro": "Rafael",
        "data": "2026-10-20", "dia_da_semana": "terça", "hora": "14:00", "cliente": "Ana",
    }


async def test_refusals_come_back_as_sentences_with_alternatives_never_exceptions():
    f = ferramentas()
    await f.agendar("ana", "11988887777", "corte", "2026-10-20", "10:00", "Rafael")
    r = await f.agendar("bia", "21988887777", "corte", "2026-10-20", "10:00", "Rafael")
    assert "não está livre com o Rafael" in r["erro"]
    assert {"data": "2026-10-20", "hora": "10:30", "barbeiro": "Rafael"} in r["alternativas"]
    assert "data" in (await f.listar_horarios("amanhã", "corte"))["erro"]
    assert "horário" in (await f.agendar("a", "11988887777", "corte", "2026-10-20", "meio-dia"))["erro"]
    assert "Os serviços são" in (await f.listar_horarios("2026-10-20", "luzes"))["erro"]


async def test_reschedule_and_cancel_need_the_booking_phone():
    f = ferramentas()
    feito = (await f.agendar("ana", "11988887777", "corte", "2026-10-20", "10:00"))["agendado"]
    meus = await f.meus_agendamentos("(11) 98888-7777")
    assert [a["agendamento_id"] for a in meus["agendamentos"]] == [feito["agendamento_id"]]

    assert "Não encontrei" in (await f.cancelar(feito["agendamento_id"], "21999990000"))["erro"]
    movido = await f.remarcar(feito["agendamento_id"], "11988887777", "2026-10-21", "16:30")
    assert (movido["remarcado"]["dia_da_semana"], movido["remarcado"]["hora"]) == ("quarta", "16:30")
    assert "cancelado" in await f.cancelar(feito["agendamento_id"], "11988887777")


async def test_every_tool_call_is_logged_with_arguments_and_result():
    async with SessionLocal() as s:
        conversa = Conversa(canal="texto", iniciada_em=AGORA)
        s.add(conversa)
        await s.commit()
    f = ferramentas(conversa.id)
    await f.agendar("ana", "11988887777", "corte", "2026-10-20", "10:00")
    await f.agendar("bia", "21988887777", "corte", "2026-10-20", "10:00", "Rafael")

    async with SessionLocal() as s:
        log = (await s.scalars(select(Mensagem).order_by(Mensagem.id))).all()
        agendado = await s.scalar(select(Agendamento))
    assert [(m.papel, m.ferramenta, m.conteudo) for m in log] == [
        (Papel.ferramenta, "agendar", "ok"),
        (Papel.ferramenta, "agendar", "Esse horário não está livre com o Rafael."),
    ]
    assert log[1].dados["argumentos"]["nome"] == "bia" and log[1].dados["resultado"]["alternativas"]
    assert agendado.conversa_id == conversa.id  # the booking points back to the call that made it


# --- text agent with a scripted Gemini -------------------------------------------------


def chamada(ferramenta, **args):
    fc = types.FunctionCall(id=f"c-{ferramenta}", name=ferramenta, args=args)
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part(function_call=fc)]))],
        function_calls=[fc],
        text=None,
        usage_metadata=SimpleNamespace(prompt_token_count=1000, candidates_token_count=20, thoughts_token_count=5),
    )


def fala(texto):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part(text=texto)]))],
        function_calls=None,
        text=texto,
        usage_metadata=SimpleNamespace(prompt_token_count=1200, candidates_token_count=30, thoughts_token_count=None),
    )


class FakeGenai:
    def __init__(self, *roteiro):
        self.roteiro = list(roteiro)
        self.modelos: list[str] = []
        self.historicos: list[list] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._gerar))

    async def _gerar(self, *, model, contents, config):
        self.modelos.append(model)
        self.historicos.append(list(contents))
        passo = self.roteiro.pop(0)
        if isinstance(passo, Exception):
            raise passo
        return passo


def agente(fake):
    async def sem_espera(_):
        pass

    return AgenteTexto(fake, SessionLocal, modelos=["novo", "estavel"], agora=lambda: AGORA, sleep=sem_espera)


async def test_agent_runs_tools_then_answers_and_logs_the_conversation():
    fake = FakeGenai(
        chamada("listar_horarios", data="2026-10-20", servico="corte"),
        fala("Tenho 9h, 9h15 ou 9h30. Algum serve?"),
    )
    a = agente(fake)
    resposta = await a.responder("Quero cortar amanhã cedo")
    await a.encerrar()

    assert resposta == "Tenho 9h, 9h15 ou 9h30. Algum serve?"
    # The second model call saw the tool's real result.
    retorno = fake.historicos[1][-1].parts[0].function_response
    assert retorno.name == "listar_horarios" and retorno.response["horarios"][0]["hora"] == "09:00"

    async with SessionLocal() as s:
        conversa = await s.get(Conversa, a.conversa_id)
        papeis = [m.papel for m in (await s.scalars(select(Mensagem).order_by(Mensagem.id))).all()]
    assert papeis == [Papel.cliente, Papel.ferramenta, Papel.agente]
    assert (conversa.tokens_entrada, conversa.tokens_saida, conversa.modelo) == (2200, 55, "novo")
    assert conversa.custo_usd > 0


async def test_unknown_tool_or_bad_arguments_go_back_to_the_model_as_errors():
    fake = FakeGenai(chamada("apagar_banco"), chamada("agendar", nome="Ana"), fala("Pode repetir?"))
    await agente(fake).responder("oi")
    assert "não existe" in fake.historicos[1][-1].parts[0].function_response.response["erro"]
    assert "Argumentos inválidos" in fake.historicos[2][-1].parts[0].function_response.response["erro"]


async def test_overloaded_model_falls_back_and_a_dead_api_gets_an_apology():
    sobrecarga = errors.APIError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
    fake = FakeGenai(sobrecarga, fala("Oi!"))
    assert await agente(fake).responder("oi") == "Oi!"
    assert fake.modelos == ["novo", "estavel"]

    morto = FakeGenai(*[sobrecarga] * 8)
    assert await agente(morto).responder("oi") == DESCULPA


async def test_model_out_of_daily_quota_is_skipped_for_the_rest_of_the_day():
    diario = errors.APIError(429, {"error": {"code": 429, "message": "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier", "status": "RESOURCE_EXHAUSTED"}})
    fake = FakeGenai(diario, fala("Oi!"), fala("De novo!"))
    a = agente(fake)
    assert await a.responder("oi") == "Oi!"
    assert await a.responder("oi de novo") == "De novo!"
    assert fake.modelos == ["novo", "estavel", "estavel"]  # "novo" not tried again today

    texto.ESGOTADOS["estavel"] = texto.date.today()
    sem_cota = FakeGenai()
    assert await agente(sem_cota).responder("oi") == DESCULPA
    assert sem_cota.modelos == []  # gave up at once instead of sleeping


async def test_tool_loop_is_bounded():
    fake = FakeGenai(*[chamada("listar_servicos")] * 6)
    assert await agente(fake).responder("oi") == DESCULPA
