# syntax=docker/dockerfile:1

# ---------- etapa de build ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --upgrade pip && pip install --prefix=/install .

# ---------- etapa de ejecución ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libgl1 libgomp1 ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 catfinder

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --from=builder --chown=catfinder:catfinder /build/app ./app
RUN mkdir -p /app/config /app/captures /app/models \
    && chown -R catfinder:catfinder /app

USER catfinder
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"

CMD ["python", "-m", "app"]
