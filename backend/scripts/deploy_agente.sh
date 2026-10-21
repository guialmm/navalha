#!/usr/bin/env bash
# Prepares the production database and publishes the voice agent to LiveKit Cloud.
#
#   backend/scripts/deploy_agente.sh "postgresql://...neon.tech/neondb?sslmode=require"
#
# Reads GEMINI_API_KEY and the LIVEKIT_* values from the repository's .env.
set -euo pipefail

DATABASE_URL="${1:?uso: deploy_agente.sh <connection string do Neon>}"
cd "$(dirname "$0")/.."            # backend/
set -a; source ../.env; set +a      # GEMINI_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

echo "→ criando as tabelas e a barbearia de exemplo no banco de produção"
DATABASE_URL="$DATABASE_URL" .venv/bin/alembic upgrade head
DATABASE_URL="$DATABASE_URL" .venv/bin/python -m app.seed

echo "→ publicando o agente no LiveKit Cloud"
segredos="$(mktemp)"
trap 'rm -f "$segredos"' EXIT
chmod 600 "$segredos"
printf 'GEMINI_API_KEY=%s\nDATABASE_URL=%s\nENV=prod\n' "$GEMINI_API_KEY" "$DATABASE_URL" > "$segredos"

if [ -f livekit.toml ]; then
  lk agent update-secrets --secrets-file "$segredos" . && lk agent deploy .
else
  lk agent create --secrets-file "$segredos" --yes .
fi
echo "✓ agente publicado; acompanhe em https://cloud.livekit.io → Agents"
