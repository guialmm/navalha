"""Run the receptionist against simulated customers and check the database.

    python -m evals.rodar                      # every scenario, 3 runs each
    python -m evals.rodar remarcar --vezes 5   # one scenario

Uses its own database (navalha_eval), rebuilt before each conversation, and
writes a JSON report to evals/resultados/.
"""

import os

os.environ["DATABASE_URL"] = os.environ.get(
    "EVAL_DATABASE_URL", "postgresql+asyncpg://navalha:navalha@localhost:5434/navalha_eval"
)

import argparse  # noqa: E402
import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

from google import genai  # noqa: E402
from google.genai import errors, types  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app import models  # noqa: E402, F401
from app.agente.texto import DESCULPA, AgenteTexto  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Canal, Mensagem  # noqa: E402
from app.seed import popular  # noqa: E402
from evals.cenarios import AGORA, CENARIOS, Cenario  # noqa: E402

MODELOS_CLIENTE = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
FIM = "FIM"
RESULTADOS = Path(__file__).parent / "resultados"


def instrucoes_cliente(persona: str) -> str:
    return f"""Você é um cliente ligando para a Barbearia Navalha. Hoje é segunda, 19/10/2026.
{persona}
Fale como numa ligação: frases curtas e naturais, em português do Brasil, uma coisa por vez.
Responda só ao que a recepcionista perguntar; não adiante todos os dados de uma vez.
Quando a conversa terminar (objetivo cumprido, impossível, ou você se despediu),
responda apenas: {FIM}"""


async def resetar() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with SessionLocal() as session:
        popular(session)
        await session.commit()


async def falar_como_cliente(client: genai.Client, persona: str, historico: list[types.Content]) -> str:
    modelos = list(MODELOS_CLIENTE)
    for tentativa in range(8):
        if not modelos:
            raise RuntimeError("cliente simulado sem cota hoje")
        try:
            r = await client.aio.models.generate_content(
                model=modelos[0],
                contents=historico,
                config=types.GenerateContentConfig(
                    system_instruction=instrucoes_cliente(persona),
                    temperature=0.7,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            return (r.text or FIM).strip()
        except errors.APIError as exc:
            if exc.code == 429 and "PerDay" in str(exc):
                modelos.pop(0)
                continue
            if exc.code not in (429, 500, 503):
                raise
            await asyncio.sleep(10 * (tentativa + 1))
    return FIM


async def conversar(client: genai.Client, cenario: Cenario) -> dict:
    await resetar()
    if cenario.preparar:
        async with SessionLocal() as session:
            await cenario.preparar(session)

    agente = AgenteTexto(client, SessionLocal, canal=Canal.eval, agora=lambda: AGORA)
    # The customer's model sees the receptionist as "user" and itself as "model".
    visao_cliente = [types.Content(role="user", parts=[types.Part(text="Barbearia Navalha, tudo bem? Como posso te ajudar?")])]
    transcricao = []
    inicio = time.monotonic()
    for _ in range(cenario.max_turnos):
        fala = await falar_como_cliente(client, cenario.persona, visao_cliente)
        if fala.strip().upper().startswith(FIM):
            break
        transcricao.append({"cliente": fala})
        visao_cliente.append(types.Content(role="model", parts=[types.Part(text=fala)]))
        resposta = await agente.responder(fala)
        transcricao.append({"agente": resposta})
        visao_cliente.append(types.Content(role="user", parts=[types.Part(text=resposta)]))
    await agente.encerrar()

    # If the receptionist had no model to answer with, the run says nothing about her.
    if any(t.get("agente") == DESCULPA for t in transcricao):
        return {"cenario": cenario.id, "passou": None, "detalhe": "inconclusivo: sem cota do Gemini no meio da conversa",
                "turnos": len(transcricao) // 2, "transcricao": transcricao}

    async with SessionLocal() as session:
        passou, detalhe = await cenario.checar(session)
        ferramentas = [
            f"{m.ferramenta}: {m.conteudo}"
            for m in (await session.scalars(select(Mensagem).where(Mensagem.ferramenta.is_not(None)).order_by(Mensagem.id))).all()
        ]
    return {
        "cenario": cenario.id,
        "passou": passou,
        "detalhe": detalhe,
        "turnos": len(transcricao) // 2,
        "segundos": round(time.monotonic() - inicio, 1),
        "tokens_agente": agente.tokens_entrada + agente.tokens_saida,
        "ferramentas": ferramentas,
        "transcricao": transcricao,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.rodar")
    parser.add_argument("cenarios", nargs="*", help="ids (default: todos)")
    parser.add_argument("--vezes", type=int, default=3)
    args = parser.parse_args()
    escolhidos = [c for c in CENARIOS if not args.cenarios or c.id in args.cenarios]

    client = genai.Client(api_key=settings.gemini_api_key)
    resultados = []
    try:
        for cenario in escolhidos:
            for n in range(args.vezes):
                r = await conversar(client, cenario)
                resultados.append(r)
                marca = {True: "✓", False: "✗", None: "?"}[r["passou"]]
                print(f"{marca} {cenario.id} #{n + 1} ({r['turnos']} turnos): {r['detalhe']}", flush=True)
    finally:
        await engine.dispose()

    validos = [r for r in resultados if r["passou"] is not None]
    print("\ncenário                 acertos")
    for cenario in escolhidos:
        rs = [r for r in validos if r["cenario"] == cenario.id]
        print(f"{cenario.id:<22} {sum(r['passou'] for r in rs)}/{len(rs)}")
    print(f"{'total':<22} {sum(r['passou'] for r in validos)}/{len(validos)}")
    if len(validos) < len(resultados):
        print(f"({len(resultados) - len(validos)} conversa(s) inconclusiva(s) por falta de cota, fora da conta)")

    RESULTADOS.mkdir(exist_ok=True)
    arquivo = RESULTADOS / f"{datetime.now():%Y%m%d-%H%M}.json"
    arquivo.write_text(json.dumps(resultados, ensure_ascii=False, indent=2))
    print(f"relatório: {arquivo}")


if __name__ == "__main__":
    asyncio.run(main())
