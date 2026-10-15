"""Talk to the receptionist in the terminal: python -m app.agente.chat"""

import asyncio

from google import genai

from app.agente.texto import AgenteTexto
from app.core.config import settings
from app.core.db import SessionLocal, engine


async def main() -> None:
    agente = AgenteTexto(genai.Client(api_key=settings.gemini_api_key), SessionLocal)
    print("Barbearia Navalha — digite 'sair' para encerrar.\n")
    try:
        while (texto := await asyncio.to_thread(input, "você: ")).strip().lower() != "sair":
            print(f"recepção: {await agente.responder(texto)}\n")
    finally:
        if agente.conversa_id:
            await agente.encerrar()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
