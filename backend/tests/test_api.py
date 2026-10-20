from datetime import datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from app import main
from app.agenda.service import agendar, buscar_servico
from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app, mascarar
from app.models import Canal, Conversa, Mensagem, Papel


@pytest.fixture
async def http(monkeypatch):
    monkeypatch.setattr(settings, "livekit_api_key", "APIteste")
    monkeypatch.setattr(settings, "livekit_api_secret", "segredo-de-teste-com-32-caracteres!!")
    monkeypatch.setattr(settings, "livekit_url", "wss://teste.livekit.cloud")
    main._ligacoes.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://teste") as c:
        yield c


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("11988887777", "(11) 9••••-7777"),
        ("meu telefone é 11 98765-4321, ok?", "meu telefone é (11) 9••••-4321, ok?"),
        ("(21) 3333-4444", "(21) 3•••-4444"),
        ("dia 20 às 14:00", "dia 20 às 14:00"),
    ],
)
def test_phones_are_masked_but_dates_survive(texto, esperado):
    assert mascarar(texto) == esperado


async def test_call_token_joins_one_room_and_dispatches_the_receptionist(http):
    r = await http.post("/api/ligacao")
    assert r.status_code == 200
    corpo = r.json()
    claims = jwt.decode(corpo["token"], "segredo-de-teste-com-32-caracteres!!", algorithms=["HS256"])
    assert claims["video"]["room"] == corpo["sala"] and claims["video"]["roomJoin"] is True
    assert claims["roomConfig"]["agents"][0]["agentName"] == "recepcionista"
    assert corpo["url"] == "wss://teste.livekit.cloud"


async def test_calls_are_rate_limited_per_ip(http):
    for _ in range(main.LIGACOES_POR_IP):
        assert (await http.post("/api/ligacao")).status_code == 200
    r = await http.post("/api/ligacao")
    assert r.status_code == 429 and "Tente de novo" in r.json()["detail"]


async def test_agenda_masks_phones(http):
    amanha = datetime.now(settings.tz).date() + timedelta(days=1)
    while amanha.weekday() not in (1, 2, 3, 4):  # a weekday every barber works
        amanha += timedelta(days=1)
    async with SessionLocal() as s:
        await agendar(s, nome="ana", telefone="11988887777", servico=await buscar_servico(s, "corte"),
                      inicio=datetime.combine(amanha, datetime.min.time(), settings.tz).replace(hour=15))
    r = await http.get("/api/agenda", params={"dia": amanha.isoformat(), "dias": 1})
    assert [(a["cliente"], a["telefone"], a["servico"]) for a in r.json()] == [("Ana", "(11) 9••••-7777", "Corte")]


async def test_dashboard_hides_eval_conversations_and_masks_transcripts(http):
    agora = datetime.now(settings.tz)
    async with SessionLocal() as s:
        voz = Conversa(canal=Canal.voz, iniciada_em=agora, duracao_s=60)
        teste = Conversa(canal=Canal.eval, iniciada_em=agora)
        muda = Conversa(canal=Canal.voz, iniciada_em=agora)  # mic denied: nobody spoke
        s.add_all([voz, teste, muda])
        await s.flush()
        s.add(Mensagem(conversa_id=voz.id, papel=Papel.cliente, conteudo="é 11 98765-4321"))
        await s.commit()

    lista = (await http.get("/api/conversas")).json()
    assert [c["id"] for c in lista] == [str(voz.id)] and lista[0]["falas"] == 1
    detalhe = (await http.get(f"/api/conversas/{voz.id}")).json()
    assert detalhe["mensagens"][0]["texto"] == "é (11) 9••••-4321"
    assert (await http.get(f"/api/conversas/{teste.id}")).status_code == 404
