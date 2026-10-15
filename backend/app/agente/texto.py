"""The receptionist over text: same tools and instructions as the voice agent.

Used by the tests, the evals and a terminal chat. The voice agent swaps this
loop for LiveKit + Gemini Live but calls the very same `Ferramentas`.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal

from google import genai
from google.genai import errors, types
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agente.ferramentas import DECLARACOES, Ferramentas
from app.agente.instrucoes import instrucoes
from app.core.config import settings
from app.models import Canal, Conversa, Mensagem, Papel

log = logging.getLogger(__name__)

MAX_PASSOS = 6  # tool rounds per customer message before giving up
TRANSITORIOS = {429, 500, 503, 504}
DESCULPA = "Desculpe, tive um problema aqui. Pode repetir, por favor?"


def custo_usd(entrada: int, saida: int) -> Decimal:
    """What the conversation would cost on the paid tier (the demo runs on the free one)."""
    por_milhao = Decimal(1_000_000)
    return (
        Decimal(entrada) * Decimal(str(settings.preco_entrada_usd_mtok))
        + Decimal(saida) * Decimal(str(settings.preco_saida_usd_mtok))
    ) / por_milhao


class AgenteTexto:
    def __init__(
        self,
        client: genai.Client,
        sessions: async_sessionmaker[AsyncSession],
        *,
        modelos: list[str] | None = None,
        canal: Canal = Canal.texto,
        agora: Callable[[], datetime] = lambda: datetime.now(settings.tz),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.client = client
        self.sessions = sessions
        self.modelos = modelos or settings.gemini_modelos_texto
        self.canal = canal
        self.agora = agora
        self.sleep = sleep
        self.historico: list[types.Content] = []
        self.conversa_id = None
        self.ferramentas: Ferramentas | None = None
        self.tokens_entrada = self.tokens_saida = 0
        self.modelo_usado: str | None = None
        self._inicio = 0.0

    async def iniciar(self) -> None:
        async with self.sessions() as session:
            conversa = Conversa(canal=self.canal, iniciada_em=self.agora())
            session.add(conversa)
            await session.commit()
            self.conversa_id = conversa.id
        self.ferramentas = Ferramentas(self.sessions, self.conversa_id, self.agora)
        self._inicio = time.monotonic()

    async def _registrar(self, papel: Papel, conteudo: str, latencia_ms: int | None = None) -> None:
        async with self.sessions() as session:
            session.add(Mensagem(conversa_id=self.conversa_id, papel=papel, conteudo=conteudo, latencia_ms=latencia_ms))
            await session.commit()

    def _config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=instrucoes(self.agora()),
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=d["name"], description=d["description"], parameters_json_schema=d["parameters"]
                        )
                        for d in DECLARACOES
                    ]
                )
            ],
            temperature=0.3,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    async def _gerar(self) -> types.GenerateContentResponse:
        ultimo = None
        for rodada in range(4):
            for modelo in self.modelos:
                try:
                    r = await self.client.aio.models.generate_content(
                        model=modelo, contents=self.historico, config=self._config()
                    )
                except errors.APIError as exc:
                    if exc.code in TRANSITORIOS or exc.code == 404:
                        ultimo = exc
                        continue
                    raise
                self.modelo_usado = modelo
                if u := r.usage_metadata:
                    self.tokens_entrada += u.prompt_token_count or 0
                    self.tokens_saida += (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
                return r
            await self.sleep(min(5 * 2**rodada, 40) + random.uniform(0, 2))
        raise ultimo or RuntimeError("sem resposta")

    async def _chamar(self, nome: str, args: dict) -> dict:
        funcao = getattr(self.ferramentas, nome, None) if nome in {d["name"] for d in DECLARACOES} else None
        if funcao is None:
            return {"erro": f"Ferramenta {nome} não existe."}
        try:
            return await funcao(**args)
        except TypeError:  # missing or unexpected arguments
            return {"erro": f"Argumentos inválidos para {nome}: {sorted(args)}."}

    async def responder(self, texto: str) -> str:
        if self.conversa_id is None:
            await self.iniciar()
        await self._registrar(Papel.cliente, texto)
        self.historico.append(types.Content(role="user", parts=[types.Part(text=texto)]))
        inicio = time.monotonic()
        try:
            for _ in range(MAX_PASSOS):
                r = await self._gerar()
                conteudo = r.candidates[0].content if r.candidates else None
                chamadas = r.function_calls or []
                if conteudo is not None:
                    self.historico.append(conteudo)
                if not chamadas:
                    resposta = (r.text or "").strip() or DESCULPA
                    await self._registrar(Papel.agente, resposta, int((time.monotonic() - inicio) * 1000))
                    return resposta
                respostas = []
                for chamada in chamadas:
                    resultado = await self._chamar(chamada.name, dict(chamada.args or {}))
                    respostas.append(
                        types.Part(function_response=types.FunctionResponse(id=chamada.id, name=chamada.name, response=resultado))
                    )
                self.historico.append(types.Content(role="user", parts=respostas))
        except errors.APIError as exc:
            log.warning("gemini falhou: %s", exc)
        await self._registrar(Papel.agente, DESCULPA)
        return DESCULPA

    async def encerrar(self) -> None:
        async with self.sessions() as session:
            conversa = await session.get(Conversa, self.conversa_id)
            conversa.encerrada_em = self.agora()
            conversa.duracao_s = int(time.monotonic() - self._inicio)
            conversa.modelo = self.modelo_usado
            conversa.tokens_entrada = self.tokens_entrada
            conversa.tokens_saida = self.tokens_saida
            conversa.custo_usd = custo_usd(self.tokens_entrada, self.tokens_saida)
            await session.commit()
