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
    main._hoje.clear()
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
        muda = Conversa(canal=Canal.voz, iniciada_em=agora)  # mic denied: only the greeting
        s.add_all([voz, teste, muda])
        await s.flush()
        s.add(Mensagem(conversa_id=muda.id, papel=Papel.agente, conteudo="Barbearia Navalha, tudo bem?"))
        s.add(Mensagem(conversa_id=voz.id, papel=Papel.cliente, conteudo="é 11 98765-4321"))
        s.add(Mensagem(conversa_id=voz.id, papel=Papel.agente, conteudo="Certo, vou anotar [interrompida]"))
        await s.commit()

    lista = (await http.get("/api/conversas")).json()
    assert [c["id"] for c in lista] == [str(voz.id)] and lista[0]["falas"] == 2
    detalhe = (await http.get(f"/api/conversas/{voz.id}")).json()
    assert detalhe["mensagens"][0]["texto"] == "é (11) 9••••-4321"
    assert (detalhe["mensagens"][1]["texto"], detalhe["mensagens"][1]["interrompida"]) == ("Certo, vou anotar", True)
    assert (await http.get(f"/api/conversas/{teste.id}")).status_code == 404


async def test_daily_cap_protects_the_free_voice_minutes(http, monkeypatch):
    monkeypatch.setattr(settings, "ligacoes_por_dia", 2)
    for ip in ("1.1.1.1", "2.2.2.2"):
        assert (await http.post("/api/ligacao", headers={"x-forwarded-for": ip})).status_code == 200
    r = await http.post("/api/ligacao", headers={"x-forwarded-for": "3.3.3.3"})
    assert r.status_code == 429 and "Volte amanhã" in r.json()["detail"]


async def test_rate_limit_uses_the_visitor_ip_behind_the_proxy(http):
    for _ in range(main.LIGACOES_POR_IP):
        await http.post("/api/ligacao", headers={"x-forwarded-for": "9.9.9.9, 76.76.21.21"})
    assert (await http.post("/api/ligacao", headers={"x-forwarded-for": "9.9.9.9"})).status_code == 429
    assert (await http.post("/api/ligacao", headers={"x-forwarded-for": "8.8.8.8"})).status_code == 200


async def test_summary_counts_only_real_calls(http):
    agora = datetime.now(settings.tz)
    async with SessionLocal() as s:
        boas = [Conversa(canal=Canal.voz, iniciada_em=agora, latencia_media_ms=ms, custo_usd=c) for ms, c in ((1000, 0.1), (2000, 0.3))]
        muda = Conversa(canal=Canal.voz, iniciada_em=agora, latencia_media_ms=9000, custo_usd=5)
        teste = Conversa(canal=Canal.eval, iniciada_em=agora, latencia_media_ms=9000)
        s.add_all([*boas, muda, teste])
        await s.flush()
        for c in (*boas, teste):
            s.add(Mensagem(conversa_id=c.id, papel=Papel.cliente, conteudo="oi"))
        await s.commit()
    r = (await http.get("/api/resumo")).json()
    assert r == {"ligacoes": 2, "agendamentos_pela_ia": 0, "latencia_media_ms": 1500, "custo_medio_usd": 0.2}
