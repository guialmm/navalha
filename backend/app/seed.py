"""Barbearia Navalha (fictional): services, barbers and their shifts.

    python -m app.seed
"""

import asyncio
from datetime import time

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.models import Barbeiro, Expediente, Servico

SERVICOS = [
    ("Corte", 30, 4500),
    ("Barba", 30, 3500),
    ("Corte e barba", 60, 7000),
    ("Pezinho", 15, 1500),
    ("Sobrancelha", 15, 2000),
]
# Tuesday to Saturday, lunch break on weekdays; Rafael also opens on Mondays.
MANHA, TARDE = (time(9), time(12)), (time(13), time(19))
EXPEDIENTES = {
    "Rafael": {0: [TARDE], 1: [MANHA, TARDE], 2: [MANHA, TARDE], 3: [MANHA, TARDE], 4: [MANHA, TARDE], 5: [(time(8), time(14))]},
    "Bruno": {1: [MANHA, TARDE], 2: [MANHA, TARDE], 3: [MANHA, TARDE], 4: [MANHA, TARDE], 5: [(time(8), time(14))]},
    "Diego": {2: [TARDE], 3: [TARDE], 4: [TARDE], 5: [(time(8), time(14))]},
}


def popular(session) -> None:
    session.add_all(Servico(nome=n, duracao_min=d, preco_centavos=p) for n, d, p in SERVICOS)
    for nome, dias in EXPEDIENTES.items():
        session.add(
            Barbeiro(
                nome=nome,
                expedientes=[
                    Expediente(dia_semana=dia, inicio=i, fim=f) for dia, turnos in dias.items() for i, f in turnos
                ],
            )
        )


async def main() -> None:
    async with SessionLocal() as session:
        if await session.scalar(select(Servico.id).limit(1)) is None:
            popular(session)
            await session.commit()
            print("barbearia de exemplo criada")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
