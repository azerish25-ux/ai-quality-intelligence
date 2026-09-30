FROM python:3.13-slim@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/src/failurelens/provider_proxy.py /app/provider_proxy.py
USER 10001:10001
CMD ["python", "/app/provider_proxy.py"]
