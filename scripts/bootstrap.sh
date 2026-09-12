#!/usr/bin/env bash
# bootstrap.sh — одноразовая инициализация проекта после setup.sh.
#
# ════════════════════════════════════════════════════════════════════════════
# ЧТО ДЕЛАЕТ ЭТОТ СКРИПТ
# ════════════════════════════════════════════════════════════════════════════
#
# Файловая структура проекта к моменту запуска уже создана скриптом
# setup.sh. Bootstrap работает с существующим деревом:
#
#   harness-project/
#   ├── .env.example        → копируется в .env, генерируется PROXY_SECRET
#   ├── pyproject.toml      → создаётся при первом запуске (uv init)
#   ├── uv.lock             → создаётся при первом запуске (uv lock)
#   ├── docker-compose.yml  → используется как есть
#   ├── harness/            → Python-модули, не меняются bootstrap'ом
#   ├── api_proxy/          → Python-модули, не меняются bootstrap'ом
#   ├── scripts/sync-model.sh → вызывается на шаге 6
#   ├── config/fs_policy.yaml → используется как есть
#   ├── workspace/          → целевая директория модели
#   ├── logs/               → audit.jsonl пишется сюда
#   └── tests/              → прогоняются на шаге 4
#
# Шаги:
#   1. Проверка setup.sh: bash -n, grep по опасным конструкциям,
#      опциональная sha256-сверка (--verify-sha256=<hash>).
#   2. Создание .env: PROXY_SECRET, UID, GID.
#   3. Единоразовый переход на uv.lock с cooldown 7 дней.
#   4. Юнит-тесты (без модели).
#   5. Сборка Docker-образов.
#   6. Модель: делегируется в scripts/sync-model.sh.
#   7. Запуск ollama-runner, api-proxy, harness.
#
# Флаги:
#   --verify-sha256=<hash>
#       Ожидаемый SHA256 setup.sh. Формат: 64 hex-символа в НИЖНЕМ
#       регистре, без префикса "sha256:". Значение должно совпадать
#       с выводом `sha256sum setup.sh | awk '{print $1}'`.
#
#       Пример:
#         ./bootstrap.sh --verify-sha256=a1b2c3d4e5f6...  (полные 64 символа)
#
#       Если задан и не совпадает — скрипт падает до продолжения.
#       Если не задан — печатается предупреждение и пользователь
#       решает сам.
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")/.."

EXPECTED_SETUP_SHA=""
for arg in "$@"; do
  case "$arg" in
    --verify-sha256=*) EXPECTED_SETUP_SHA="${arg#*=}" ;;
    *) echo "[!] Неизвестный флаг: $arg" >&2; exit 2 ;;
  esac
done

# --- 1. Проверка setup.sh ----------------------------------------------------
if [[ -f ../setup.sh ]]; then
  echo "[*] Syntax check ../setup.sh..."
  bash -n ../setup.sh || {
    echo "[!] setup.sh содержит синтаксические ошибки"
    exit 1
  }

  if [[ -n "$EXPECTED_SETUP_SHA" ]]; then
    echo "[*] Verifying sha256 of setup.sh..."
    actual=$(sha256sum ../setup.sh | awk '{print $1}')
    if [[ "$actual" != "$EXPECTED_SETUP_SHA" ]]; then
      echo "[!] SHA256 setup.sh НЕ совпал:" >&2
      echo "    ожидался: $EXPECTED_SETUP_SHA" >&2
      echo "    получен:  $actual" >&2
      exit 1
    fi
    echo "[+] SHA256 setup.sh совпал: $actual"
  else
    echo "[i] sha256 не сверяется (не задан --verify-sha256=<hash>)."
    echo "    Проверьте вручную: sha256sum ../setup.sh"
    echo "    Сравните с ожидаемым хешем из документации."
  fi

  SUSPICIOUS=$(grep -nE \
    '(^|[;&|]|\s)(sudo\s+)?(curl|wget|nc|/dev/tcp|eval|base64\s+-d|rm\s+-rf|dd\s+if=|mkfs)' \
    ../setup.sh || true)

  if [[ -n "$SUSPICIOUS" ]]; then
    echo "[!] В setup.sh найдены потенциально опасные конструкции:"
    echo "$SUSPICIOUS"
    echo "[i] Ожидаемо: setup.sh содержит heredoc-и с исходниками проекта,"
    echo "    а в них — литеральные curl в README и regex в injection_guard.py."
    echo "    Это не команды. Просмотрите вывод и подтвердите, если всё ок."
    read -rp "Продолжить? [y/N] " ans
    [[ "$ans" == "y" ]] || exit 1
  else
    echo "[+] setup.sh чист по grep-паттернам."
  fi
else
  echo "[i] ../setup.sh не найден — проверка пропущена."
fi

# --- Автодетект docker -------------------------------------------------------
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi
echo "[*] Using: $DOCKER"

# --- 2. .env -----------------------------------------------------------------
if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s|^PROXY_SECRET=.*|PROXY_SECRET=$(openssl rand -hex 32)|" .env
  sed -i "s|^UID=.*|UID=$(id -u)|" .env
  sed -i "s|^GID=.*|GID=$(id -g)|" .env
  echo "[+] .env создан: PROXY_SECRET сгенерирован, UID/GID подставлены."
fi

# --- 3. Python env через uv --------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"

if [[ ! -f pyproject.toml ]]; then
  echo "[*] Переход на uv.lock (единоразово)..."
  # --no-readme: не трогать существующий README.md проекта.
  uv init --name harness --python 3.12 --no-readme

  # Cooldown: не резолвить пакеты, опубликованные менее 7 дней назад.
  # НЕ УДАЛЯЙТЕ этот блок — это защита от свежих вредоносных релизов
  # на PyPI.
  cat >> pyproject.toml <<'PYPROJECT_EOF'

[tool.uv]
exclude-newer = "7 days"
PYPROJECT_EOF

  uv add -r harness/requirements.txt
  uv add --dev -r requirements-dev.txt
  uv lock
  echo "[+] uv.lock создан с SHA256-хешами; cooldown = 7 дней."
fi

uv sync --locked

# --- 4. Юнит-тесты (без модели) ----------------------------------------------
echo "[*] Юнит-тесты (без модели)..."
uv run pytest tests/ --ignore=tests/smoke -q

# --- 5. Сборка образов -------------------------------------------------------
echo "[*] Сборка образов..."
$DOCKER compose build

# --- 6. Модель ---------------------------------------------------------------
echo "[*] Скачивание модели..."
./scripts/sync-model.sh

# --- 7. Запуск ---------------------------------------------------------------
echo "[*] Запуск ollama-runner, api-proxy, harness..."
$DOCKER compose up -d ollama-runner api-proxy harness

echo
echo "[+] Bootstrap завершён. Для работы:"
echo "    $DOCKER compose exec harness python -m harness.main"
echo
echo "[i] Проверка изоляции (должно завершиться ошибкой):"
echo "    $DOCKER compose exec harness python -c \"import socket; socket.create_connection(('1.1.1.1',53),timeout=2)\""
