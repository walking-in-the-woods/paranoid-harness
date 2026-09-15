#!/usr/bin/env bash
# Генерация токенов клиентов гейтвея для ручной ротации.
#
# Печатает токен (отдать клиенту) и SHA256 (вставить в YAML вручную).
#
# ── Формула token→hash ─────────────────────────────────────────────────────
#
#   token = openssl rand -hex 32
#   hash  = sha256sum от token
#
# Эта формула продублирована inline в scripts/bootstrap.sh (шаг 6,
# для автоматического заполнения config/gateway_clients.yaml и .env).
# При изменении формулы — править оба места.
#
# ── Использование ──────────────────────────────────────────────────────────
#
#   bash scripts/gateway-tokens.sh <client> [<client> ...]
#
# Вызов через `bash` — согласован с политикой bootstrap'а: не
# полагаться на executable-бит в рабочей копии (WSL, Windows,
# core.fileMode=false).
#
# Пример:
#   bash scripts/gateway-tokens.sh webui
#
# Для автоматической ротации предпочтительнее bootstrap: он сам
# подставит токен в .env и хеш в YAML. Этот скрипт — для ручных
# случаев (ротация одного клиента без полного перезапуска bootstrap).
set -euo pipefail

gen() {
    local name="$1"
    local token hash
    token=$(openssl rand -hex 32)
    hash=$(printf '%s' "$token" | sha256sum | awk '{print $1}')
    printf '=== %s ===\n' "$name"
    printf 'Token: %s\n' "$token"
    printf 'Hash:  %s\n\n' "$hash"
}

if [[ "$#" -eq 0 ]]; then
    echo "usage: $0 <client-name> [<client-name> ...]" >&2
    exit 2
fi

for name in "$@"; do
    gen "$name"
done
