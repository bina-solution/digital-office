# =============================================================================
# Stage 1: Build the incoming-documents webapp (Vite + React + TS + Tailwind).
# =============================================================================
FROM node:20-alpine AS webapp-builder
WORKDIR /webapp
COPY app/webapp/package*.json ./
RUN npm install --no-audit --no-fund
COPY app/webapp/ ./
RUN npm run build

# =============================================================================
# Stage 2: Python runtime
# =============================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FLASK_DEBUG=False \
    LOG_LEVEL=INFO \
    PORT=8080 \
    PYTHONPATH=/app \
    INCOMING_DOCS_WEBAPP_DIST=/app/incoming_documents_dist

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/
# Drop the webapp source — only the built dist is needed at runtime.
RUN rm -rf /app/webapp

COPY --from=webapp-builder /webapp/dist /app/incoming_documents_dist

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:application"]
