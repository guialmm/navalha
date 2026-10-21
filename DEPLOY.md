# Deploy

Tudo no plano gratuito. Ordem: banco → agente de voz → API → site.

| Parte | Onde | Observação |
|---|---|---|
| Banco | Neon, região **AWS São Paulo (sa-east-1)** | perto do agente, que roda no Brasil |
| Agente de voz | LiveKit Cloud (`backend/Dockerfile`) | 1.000 min/mês, 5 ligações simultâneas |
| API | Render (`render.yaml`, `backend/Dockerfile.api`) | dorme após 15 min sem uso; acorda em ~30 s |
| Site | Vercel (`frontend/`) | `/api` é repassado para a API |

## 1. Banco (Neon)

1. https://console.neon.tech → **New project** → nome `navalha`, região **AWS São Paulo**.
2. **Connect** → copie a connection string (`postgresql://...`).

## 2. Agente de voz (LiveKit Cloud)

Com o `.env` da raiz preenchido (`GEMINI_API_KEY` e `LIVEKIT_*`) e o
[LiveKit CLI](https://docs.livekit.io/home/cli/) instalado:

```bash
backend/scripts/deploy_agente.sh "postgresql://...connection string do Neon..."
```

O script cria as tabelas, cadastra a barbearia de exemplo e publica o agente.
Na primeira vez ele cria o `livekit.toml` (sem segredos; pode ir para o git);
nas seguintes, atualiza os segredos e publica uma versão nova.

## 3. API (Render)

1. https://dashboard.render.com → **New → Blueprint** → repositório `guialmm/navalha`.
2. Preencha `DATABASE_URL` (a do Neon), `LIVEKIT_URL`, `LIVEKIT_API_KEY` e `LIVEKIT_API_SECRET`.
3. **Apply**. Ao subir, a API roda as migrations e o seed (que não duplica nada).

## 4. Site (Vercel)

1. https://vercel.com/new → importe `guialmm/navalha`.
2. **Root Directory**: `frontend`.
3. **Environment Variables**: `API_URL` = endereço do Render (`https://navalha-api-xxxx.onrender.com`).
4. **Deploy**.

## Depois

- Coloque o link do site no topo do README.
- O site chama a API pelo próprio domínio (`/api/...`), então não há CORS a configurar.
- Limites da demo: 5 ligações por visitante a cada 10 min e 30 por dia
  (`ligacoes_por_dia` em `backend/app/core/config.py`).
