# ---- build stage ---------------------------------------------------------
FROM python:3.12.7-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app
# uv.lock НЕ копируется: на чистом клоне файла нет. UV резолвит
# транзитивные зависимости сам с учётом exclude-newer = "7 days" и
# точных == для прямых зависимостей. Результат детерминирован в
# пределах 7-дневного окна. Для полной воспроизводимости bootstrap.sh
# генерирует uv.lock один раз перед сборкой образа, и его можно
# закоммитить.
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# ---- runtime stage -------------------------------------------------------
FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    HOME=/tmp

ARG RUNTIME_UID=1000
ARG RUNTIME_GID=1000
RUN groupadd -g "${RUNTIME_GID}" gateway && \
    useradd -u "${RUNTIME_UID}" -g "${RUNTIME_GID}" \
            -M -d /app -s /usr/sbin/nologin gateway

# COPY --chown создаёт /app с правильным владельцем: WORKDIR
# до COPY не выставлен, иначе /app был бы root:root.
COPY --from=builder --chown=gateway:gateway /app /app
COPY --chown=gateway:gateway gateway.py cert_verify.py /app/

WORKDIR /app
USER gateway

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).read()" || exit 1

# --h11-max-incomplete-event-size: X-Client-Cert (~3 KB URL-encoded
# 4096-bit RSA + другие заголовки от nginx). Дефолт h11 — 16 KB;
# 32 KB даёт запас при длинных SAN.
CMD ["uvicorn", "gateway:app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--no-access-log", "--workers", "1", \
     "--h11-max-incomplete-event-size", "32768"]
