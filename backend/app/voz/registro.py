"""Writes a voice call to the database as it happens.

LiveKit events fire on the worker's event loop and must not block the audio,
so each write is a fire-and-forget task; `encerrar` waits for them all before
closing the call with duration, tokens, cost and latency.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models import Conversa, Mensagem, Papel

log = logging.getLogger("navalha.voz")


def custo_voz_usd(entrada: int, saida: int) -> Decimal:
    """Paid-tier equivalent for native-audio tokens (the demo uses the free tier)."""
    return (
        Decimal(entrada) * Decimal(str(settings.preco_voz_entrada_usd_mtok))
        + Decimal(saida) * Decimal(str(settings.preco_voz_saida_usd_mtok))
    ) / Decimal(1_000_000)


class RegistroVoz:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], conversa_id: uuid.UUID):
        self.sessions = sessions
        self.conversa_id = conversa_id
        self.inicio = time.monotonic()
        self.tokens_entrada = 0
        self.tokens_saida = 0
        self.latencias_ms: list[int] = []
        self._cliente_parou_em: float | None = None
        self._latencia_pendente: int | None = None
        self._tarefas: set[asyncio.Task] = set()

    def _depois(self, coro) -> None:
        tarefa = asyncio.create_task(coro)
        self._tarefas.add(tarefa)
        tarefa.add_done_callback(self._tarefas.discard)

    def cliente_parou(self, quando: float) -> None:
        self._cliente_parou_em = quando

    def agente_comecou(self, quando: float) -> None:
        """Latency the customer feels: their last word → the agent's first word.
        Only counted when the agent is answering a turn that actually ended."""
        if self._cliente_parou_em is not None and quando >= self._cliente_parou_em:
            self._latencia_pendente = int((quando - self._cliente_parou_em) * 1000)
            self.latencias_ms.append(self._latencia_pendente)
        self._cliente_parou_em = None

    def fala(self, papel: Papel, texto: str, *, interrompida: bool = False) -> None:
        latencia = None
        if papel == Papel.agente:
            # The agent's message is logged when it finishes speaking; attach the
            # latency measured when it started.
            latencia, self._latencia_pendente = self._latencia_pendente, None

        async def gravar():
            async with self.sessions() as session:
                session.add(
                    Mensagem(
                        conversa_id=self.conversa_id,
                        papel=papel,
                        conteudo=texto + (" [interrompida]" if interrompida else ""),
                        latencia_ms=latencia,
                    )
                )
                await session.commit()

        self._depois(gravar())

    def uso(self, model_usage) -> None:
        """LiveKit sends the running totals for the whole session, not deltas."""
        self.tokens_entrada = sum(getattr(u, "input_tokens", 0) for u in model_usage)
        self.tokens_saida = sum(getattr(u, "output_tokens", 0) for u in model_usage)

    async def encerrar(self) -> None:
        try:
            await self._encerrar()
        except Exception:
            log.exception("falha ao fechar a conversa %s", self.conversa_id)

    async def _encerrar(self) -> None:
        if self._tarefas:
            await asyncio.gather(*self._tarefas, return_exceptions=True)
        async with self.sessions() as session:
            conversa = await session.get(Conversa, self.conversa_id)
            conversa.encerrada_em = datetime.now(settings.tz)
            conversa.duracao_s = int(time.monotonic() - self.inicio)
            conversa.tokens_entrada = self.tokens_entrada
            conversa.tokens_saida = self.tokens_saida
            conversa.custo_usd = custo_voz_usd(self.tokens_entrada, self.tokens_saida)
            if self.latencias_ms:
                conversa.latencia_media_ms = sum(self.latencias_ms) // len(self.latencias_ms)
            await session.commit()
        log.info("conversa %s encerrada: %ss, %s respostas", self.conversa_id, conversa.duracao_s, len(self.latencias_ms))
