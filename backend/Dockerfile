# Voice worker, built and hosted by LiveKit Cloud (`lk agent deploy`).
# LiveKit injects LIVEKIT_URL/API_KEY/API_SECRET at runtime; GEMINI_API_KEY and
# DATABASE_URL come from the agent's secrets.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 agente
COPY requirements.txt requirements-voz.txt ./
RUN pip install --no-cache-dir -r requirements-voz.txt
COPY app ./app
USER agente
# Silero's model is fetched at build time, not on the first call.
RUN python -m app.voz.agente download-files
CMD ["python", "-m", "app.voz.agente", "start"]
