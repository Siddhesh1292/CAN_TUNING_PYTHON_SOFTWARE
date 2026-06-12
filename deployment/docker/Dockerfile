# ── Stage 1: dependencies ─────────────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY deployment/docker/requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends curl libffi8 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app && useradd -r -g app -d /app app

WORKDIR /app

COPY --from=builder /install /usr/local

# Copy all app source (preserves the exact structure the imports expect)
COPY --chown=app:app app.py           ./
COPY --chown=app:app can_tuner3.py    ./
COPY --chown=app:app waveshare_can.py ./
COPY --chown=app:app templates/       ./templates/
COPY --chown=app:app static/          ./static/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_ENV=production \
    PORT=5000

USER app
EXPOSE 5000

# Healthcheck matches /health route in app.py
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:5000/health || exit 1

# 2 workers × 4 threads — suitable for t3.small (2 vCPU / 2 GB)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
