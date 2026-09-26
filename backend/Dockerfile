FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 failurelens
WORKDIR /app

COPY backend /app/backend
COPY evaluation /app/evaluation
RUN python -m pip install --upgrade pip \
    && python -m pip install /app/backend

ENV FAILURELENS_DATABASE_URL=postgresql+psycopg://failurelens:failurelens@db:5432/failurelens \
    FAILURELENS_ARTIFACT_ROOT=/var/lib/failurelens/artifacts \
    FAILURELENS_EVALUATION_METRICS_PATH=/app/evaluation/reports/latest/metrics.json

RUN mkdir -p /var/lib/failurelens/artifacts && chown -R failurelens:failurelens /var/lib/failurelens /app
USER failurelens

EXPOSE 8000
CMD ["sh", "-c", "cd /app/backend && alembic upgrade head && exec uvicorn failurelens.api:app --host 0.0.0.0 --port 8000"]
