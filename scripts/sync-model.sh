#!/usr/bin/env bash
# sync-model.sh — загрузка модели, снапшот, верификация, промоушен.
#
# ════════════════════════════════════════════════════════════════════════════
# ЧТО ДЕЛАЕТ ЭТОТ СКРИПТ
# ════════════════════════════════════════════════════════════════════════════
#
# Digest-верификация:
#   digest берётся из `ollama list --json` (поле "digest"), а НЕ из
#   `ollama show --modelfile` — последний содержит несколько sha256
#   (слои, template, параметры) и head -n1 даёт НЕ digest модели.
#
# ОГРАНИЧЕНИЕ digest-верификации:
#   Если и ожидаемый, и фактический digest получены через `ollama
#   list --json` из одного источника, проверка защищает только от
#   ПОСЛЕДУЮЩЕЙ подмены тега. При первом pull компрометация реестра
#   Ollama приведёт к совпадению digest на вредоносной версии.
#   Для защиты от этого ожидаемый digest должен приходить из
#   out-of-band канала (сайт проекта, подписанный релиз). См.
#   docs/operations.md.
#
# Аргументы:
#   $1 — имя модели (опционально; иначе из .env).
#
# Переменные окружения:
#   ALPINE_IMAGE — образ для временного контейнера промоушена.
#                  По умолчанию alpine:3.19 (по тегу — тег мутабельный).
#                  Для production задайте digest:
#                  ALPINE_IMAGE=alpine@sha256:<digest> ./scripts/sync-model.sh
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "[!] .env не найден. Скопируйте .env.example в .env." >&2
  exit 1
fi

MODEL="${1:-$(grep -E '^HARNESS_MODEL=' .env | cut -d= -f2 | tr -d ' ')}"
MODEL_DIGEST="$(grep -E '^HARNESS_MODEL_DIGEST=' .env | cut -d= -f2- | tr -d ' ' || true)"
ALPINE_IMAGE="${ALPINE_IMAGE:-alpine:3.19}"

if [[ -z "$MODEL" ]]; then
  echo "usage: $0 <model-name>   e.g. $0 qwen3:8b" >&2
  exit 2
fi

# python3 нужен для парсинга JSON при digest-верификации.
if [[ -n "$MODEL_DIGEST" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "[!] python3 не найден, но задан HARNESS_MODEL_DIGEST." >&2
    echo "    Установите python3 или очистите HARNESS_MODEL_DIGEST в .env." >&2
    exit 1
  fi
fi

# Предупреждение о мутабельном теге alpine.
if [[ "$ALPINE_IMAGE" != *"@sha256:"* ]]; then
  echo "[i] ALPINE_IMAGE=$ALPINE_IMAGE — используется по тегу." >&2
  echo "    Тег мутабельный. Для production задайте digest:" >&2
  echo "      docker pull $ALPINE_IMAGE" >&2
  echo "      docker inspect --format='{{index .RepoDigests 0}}' $ALPINE_IMAGE" >&2
  echo "      ALPINE_IMAGE=alpine@sha256:<digest> $0" >&2
fi

# Автодетект docker: Docker Desktop в WSL работает без sudo,
# на Linux обычно через sudo.
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi

echo "[*] Starting updater container..."
$DOCKER compose --profile updater up -d ollama-updater

echo "[*] Pulling model: $MODEL"
$DOCKER exec ollama-updater ollama pull "$MODEL"

if [[ -n "$MODEL_DIGEST" ]]; then
  echo "[*] Verifying model digest (source: ollama list --json)..."

  actual_digest=$(
    $DOCKER exec ollama-updater ollama list --json 2>/dev/null \
      | python3 -c '
import json, sys
target = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
# Разные версии Ollama: либо список, либо {"models": [...]}
models = data.get("models", data) if isinstance(data, dict) else data
for m in models:
    name = m.get("name") or m.get("model") or ""
    if name == target:
        print(m.get("digest", ""))
        break
' "$MODEL"
  )

  if [[ -z "$actual_digest" ]]; then
    echo "[!] Не удалось получить digest модели '$MODEL' через ollama list." >&2
    echo "    Проверьте, что контейнер ollama-updater запущен и модель скачана." >&2
    exit 1
  fi

  norm_expected="${MODEL_DIGEST#sha256:}"
  norm_actual="${actual_digest#sha256:}"

  if [[ "$norm_expected" != "$norm_actual" ]]; then
    echo "[!] Digest модели НЕ совпал:" >&2
    echo "    ожидался: $MODEL_DIGEST" >&2
    echo "    получен:  $actual_digest" >&2
    echo "    Возможна подмена тега в реестре. Промоушен прерван." >&2
    exit 1
  fi
  echo "[+] Digest совпал: $actual_digest"
else
  echo "[i] HARNESS_MODEL_DIGEST не задан — верификация пропущена."
  echo "    Для paranoid-режима задайте digest в .env (см. .env.example)."
fi

echo "[*] Freezing model snapshot..."
$DOCKER exec ollama-updater sh -c \
  'cd /root/.ollama && rm -f /tmp/snapshot.tgz && tar czf /tmp/snapshot.tgz .'
$DOCKER cp ollama-updater:/tmp/snapshot.tgz /tmp/ollama-snapshot.tgz

SHA=$(sha256sum /tmp/ollama-snapshot.tgz | awk '{print $1}')
echo "[+] Snapshot SHA256: $SHA"
echo "$SHA  ollama-snapshot.tgz" > ollama-models-verified.sha256

echo "[*] Promoting snapshot into runner volume (with hash manifest)..."
$DOCKER run --rm \
  -v ollama-models-verified:/dst \
  -v /tmp/ollama-snapshot.tgz:/snapshot.tgz:ro \
  "$ALPINE_IMAGE" sh -euc '
    rm -rf /dst/* /dst/.[!.]* 2>/dev/null || true
    tar xzf /snapshot.tgz -C /dst
    cd /dst
    find . -type f -exec sha256sum {} \; | sort > .snapshot.sha256
    echo "[+] Files extracted: $(wc -l < .snapshot.sha256)"
  '

echo "[*] Restarting ollama-runner with new model set..."
$DOCKER compose up -d --force-recreate ollama-runner

echo "[*] Stopping updater..."
$DOCKER compose --profile updater down ollama-updater

echo "[+] Done. Model '$MODEL' is now available."
