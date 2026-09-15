#!/usr/bin/env bash
# bootstrap.sh — одноразовая инициализация проекта после setup.sh
# или git clone.
#
# ════════════════════════════════════════════════════════════════════════════
# ЧТО ДЕЛАЕТ ЭТОТ СКРИПТ
# ════════════════════════════════════════════════════════════════════════════
#
# Файловая структура проекта к моменту запуска создана скриптом
# setup.sh или git clone.
#
# Шаги:
#   1. Проверка setup.sh (если найден): bash -n, grep, sha256.
#   2. Создание .env из .env.example.
#   3. Python env через uv (единоразово).
#   4. Юнит-тесты (без модели).
#   5. Генерация сертификатов (gateway-certs.sh).
#   6. Генерация токенов клиентов гейтвея и заполнение
#      config/gateway_clients.yaml реальными SHA256-хешами.
#   7. Сборка образов (docker-compose.yml).
#   8. Модель: sync-model.sh (загрузка + снапшот + промоушен).
#   9. Запуск всех сервисов (docker-compose.yml).
#  10. Fail-closed проверка плейсхолдеров через
#      scripts/check-file-excludes-pattern.sh (rc=0/1/2).
#
# ── Pre-check обязательных файлов ──────────────────────────────────────────
#
# Перед началом работы проверяется наличие всех файлов, к которым
# bootstrap обращается: три helper-скрипта (gateway-certs.sh,
# sync-model.sh, check-file-excludes-pattern.sh), docker-compose.yml,
# .env.example и config/gateway_clients.yaml.
#
# Список ручной: шесть элементов читаются явно, а парсинг `$0` через
# regex сломался бы на `bash ./scripts/X.sh` или
# `bash "${PWD}/scripts/X.sh"`. Если добавляете новый вызов
# `bash scripts/X.sh` или прямое чтение файла, добавьте в этот список.
#
# Не входит в список `harness/requirements.txt` и
# `requirements-dev.txt`: шаг 3 выполняется только при первом запуске
# (`[[ ! -f pyproject.toml ]]`), сообщение uv при отсутствии файла
# внятное. Список из семи-восьми элементов теряет наглядность.
#
# ── Вызовы вспомогательных скриптов ────────────────────────────────────────
#
# Все вызовы — через `bash scripts/X`. Это не полагается на
# executable-бит в рабочей копии: при `git config core.fileMode=false`
# (типично для Windows/WSL) или при клоне без бита `./scripts/X`
# упал бы с Permission denied. `bash` от бита не зависит и не
# изменяет права рабочей копии (в отличие от chmod).
#
# ── Клиенты гейтвея ────────────────────────────────────────────────────────
#
# Проект поставляется с двумя клиентами: `harness` (агент с tools) и
# `webui` (chat-only). Дополнительные клиенты (интеграции со сторонними
# приложениями и т.п.) добавляются вручную:
#
#   1. В config/gateway_clients.yaml — новый блок clients с полем
#      name: "<имя>". Значение token_sha256 оставить placeholder'ом
#      REPLACE_WITH_<PREFIX>_HASH.
#   2. В .env.example — новая строка <PREFIX>_GATEWAY_TOKEN=replace-...
#   3. В CLIENTS=() ниже — добавить имя.
#
# Правило формирования PREFIX из имени:
#
#   PREFIX = name.upper().replace("-", "_")
#
#   harness           → HARNESS           → HARNESS_GATEWAY_TOKEN,
#                                            REPLACE_WITH_HARNESS_HASH
#   webui             → WEBUI             → WEBUI_GATEWAY_TOKEN,
#                                            REPLACE_WITH_WEBUI_HASH
#   libreoffice-tool  → LIBREOFFICE_TOOL  → LIBREOFFICE_TOOL_GATEWAY_TOKEN,
#                                            REPLACE_WITH_LIBREOFFICE_TOOL_HASH
#
# Имена с дефисом работают благодаря tr '[:lower:]-' '[:upper:]_'.
# Достаточно, чтобы .env.example и gateway_clients.yaml следовали той
# же формуле — тогда sed найдёт и заменит.
#
# ── Формула token→hash ─────────────────────────────────────────────────────
#
#   token = openssl rand -hex 32
#   hash  = sha256sum от token
#
# Эта формула продублирована в scripts/gateway-tokens.sh (для ручной
# ротации) и inline ниже (шаг 6). При изменении формулы — править
# оба места.
#
# Флаги:
#   --verify-sha256=<hash>
#       Ожидаемый SHA256 setup.sh. Формат: 64 hex-символа в нижнем
#       регистре, без префикса "sha256:".
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")/.."

# ── Клиенты ────────────────────────────────────────────────────────────────
# Порядок не критичен. Имена должны совпадать с name: в
# config/gateway_clients.yaml и с PREFIX в .env.example (см. правило
# в шапке).
CLIENTS=(harness webui)

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
  fi

  SUSPICIOUS=$(grep -nE \
    '(^|[;&|]|\s)(sudo\s+)?(curl|wget|nc|/dev/tcp|eval|base64\s+-d|rm\s+-rf|dd\s+if=|mkfs)' \
    ../setup.sh || true)

  if [[ -n "$SUSPICIOUS" ]]; then
    echo "[!] В setup.sh найдены потенциально опасные конструкции:"
    echo "$SUSPICIOUS"
    echo "[i] Просмотрите вывод и подтвердите, если всё ок."
    # read -rp требует tty; в неинтерактивном окружении (CI, Ansible)
    # /dev/tty отсутствует — read вернёт ненулевой код, ans=n, скрипт
    # упадёт. Это осознанный fail-closed.
    # 2>/dev/null подавляет диагностику bash `/dev/tty: No such device`.
    read -rp "Продолжить? [y/N] " ans < /dev/tty 2>/dev/null || ans="n"
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

# --- Требования --------------------------------------------------------------
for tool in openssl sha256sum; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "[!] Не найден обязательный инструмент: $tool" >&2
    exit 1
  fi
done

# Проверяем наличие всех файлов, к которым обращается bootstrap.
# Список ручной — шесть элементов читаются явно. Если добавляете
# новый вызов `bash scripts/X.sh` или прямое чтение файла, добавьте
# в этот список.
#
# Раньше проверялись только helper-скрипты; docker-compose.yml,
# .env.example и config/gateway_clients.yaml читаются напрямую —
# без pre-check их отсутствие давало неточный диагноз.
for required in \
    docker-compose.yml \
    .env.example \
    config/gateway_clients.yaml \
    scripts/gateway-certs.sh \
    scripts/sync-model.sh \
    scripts/check-file-excludes-pattern.sh; do
  if [[ ! -f "${required}" ]]; then
    echo "[!] Не найден обязательный файл: ${required}" >&2
    echo "    Проверьте целостность клона (git status, ls)." >&2
    exit 1
  fi
done

# --- 2. .env -----------------------------------------------------------------
if [[ ! -f .env ]]; then
  cp .env.example .env
  sed -i "s|^PROXY_SECRET=.*|PROXY_SECRET=$(openssl rand -hex 32)|" .env
  sed -i "s|^GATEWAY_HMAC_KEY=.*|GATEWAY_HMAC_KEY=$(openssl rand -hex 32)|" .env
  sed -i "s|^UID=.*|UID=$(id -u)|" .env
  sed -i "s|^GID=.*|GID=$(id -g)|" .env
  echo "[+] .env создан: PROXY_SECRET, GATEWAY_HMAC_KEY сгенерированы."
else
  echo "[=] .env уже существует — используется как есть."
fi

# Проверяем, что обязательные переменные заданы непустыми.
for var in PROXY_SECRET GATEWAY_HMAC_KEY OLLAMA_IMAGE; do
  if ! grep -qE "^${var}=.+" .env; then
    echo "[!] .env: переменная ${var} не задана или пуста." >&2
    echo "    Обновите .env по образцу .env.example." >&2
    exit 1
  fi
done

# --- 3. Python env через uv --------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"

if [[ ! -f pyproject.toml ]]; then
  echo "[*] Переход на uv.lock (единоразово)..."
  uv init --name harness --python 3.12 --no-readme

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

# --- 5. Генерация сертификатов ----------------------------------------------
if [[ ! -f certs/ca.crt ]] || [[ ! -f certs/server.crt ]]; then
  echo "[*] Генерация CA и сертификатов..."
  bash scripts/gateway-certs.sh certs "${CLIENTS[@]}"
  echo "[+] Сертификаты в ./certs/. ca.key перенесите offline."
else
  echo "[=] Сертификаты уже существуют в ./certs/."
  # Догоняем недостающие клиентские сертификаты (например, добавили
  # клиента в CLIENTS после первого запуска). Скрипт сам skip'ает
  # существующие.
  bash scripts/gateway-certs.sh certs "${CLIENTS[@]}" >/dev/null
fi

# --- 6. Токены клиентов и заполнение gateway_clients.yaml -------------------
echo "[*] Токены клиентов гейтвея..."

for client in "${CLIENTS[@]}"; do
  prefix="$(printf '%s' "${client}" | tr '[:lower:]-' '[:upper:]_')"
  env_var="${prefix}_GATEWAY_TOKEN"
  placeholder="REPLACE_WITH_${prefix}_HASH"

  # Для ERE-проверки экранируем метасимволы, допустимые в имени
  # клиента (gateway-certs.sh разрешает [A-Za-z0-9._-], из них
  # метасимвол ERE — только `.`).
  client_ere="$(printf '%s' "${client}" | sed 's/\./\\./g')"

  # Проверяем, что клиент объявлен в YAML. Имя может быть в двойных
  # кавычках, одинарных или без кавычек; допускается inline-комментарий
  # после значения.
  if ! grep -qE "^[[:space:]]*-[[:space:]]*name:[[:space:]]*['\"]?${client_ere}['\"]?([[:space:]]*#.*)?[[:space:]]*$" \
        config/gateway_clients.yaml; then
    echo "[!] Клиент ${client} не найден в config/gateway_clients.yaml." >&2
    echo "    Добавьте блок clients с name: \"${client}\" и" >&2
    echo "    token_sha256: \"${placeholder}\"." >&2
    exit 1
  fi

  env_current="$(grep -E "^${env_var}=" .env | cut -d= -f2- || true)"
  yaml_has_placeholder=false
  if grep -q "${placeholder}" config/gateway_clients.yaml; then
    yaml_has_placeholder=true
  fi

  env_is_placeholder=false
  if [[ -z "$env_current" ]] || [[ "$env_current" == replace-* ]]; then
    env_is_placeholder=true
  fi

  if [[ "$env_is_placeholder" == "false" ]] \
     && [[ "$yaml_has_placeholder" == "false" ]]; then
    echo "[=] ${client}: токен и хеш уже заданы — пропускаю."
    continue
  fi

  # Формула token→hash. Продублирована в scripts/gateway-tokens.sh;
  # при изменении — править оба места (см. шапку скрипта).
  token="$(openssl rand -hex 32)"
  hash="$(printf '%s' "${token}" | sha256sum | awk '{print $1}')"

  # Обновляем или добавляем строку в .env.
  if grep -qE "^${env_var}=" .env; then
    sed -i "s|^${env_var}=.*|${env_var}=${token}|" .env
  else
    printf '\n%s=%s\n' "${env_var}" "${token}" >> .env
  fi

  # Заменяем placeholder на реальный SHA256 в YAML.
  sed -i "s|${placeholder}|${hash}|g" config/gateway_clients.yaml

  echo "[+] ${client}: токен и хеш записаны."
done

# --- 7. Сборка образов -------------------------------------------------------
echo "[*] Сборка образов..."
$DOCKER compose build

# --- 8. Модель ---------------------------------------------------------------
echo "[*] Скачивание модели..."
bash scripts/sync-model.sh

# --- 9. Запуск ---------------------------------------------------------------
echo "[*] Запуск ollama-runner, model-gateway, gateway-tls, api-proxy, harness..."
$DOCKER compose up -d ollama-runner model-gateway gateway-tls api-proxy harness

# --- 10. Fail-closed проверка плейсхолдеров ---------------------------------
# Если sed не нашёл паттерн, плейсхолдер остаётся, sed молча выходит
# с кодом 0, и система не работает при старте. Эта проверка ловит
# весь класс таких ошибок.
#
# Helper scripts/check-file-excludes-pattern.sh:
#   rc=0 — паттерн НЕ найден (ОК);
#   rc=1 — паттерн найден (нарушение гигиены, fail);
#   rc=2 — grep сломался (fail).
#
# Конструкция `helper || { fail; exit 1; }` срабатывает на 1 и 2,
# пропускает 0. Своя реализация case здесь не дублируется.
#
# Покрываемые случаи:
#   * `REPLACE_WITH_<...>_HASH` в YAML — placeholder token_sha256.
#     [A-Z0-9_]+ — имена клиентов могут содержать цифры (webui2).
#   * Любая переменная .env со значением, начинающимся с `replace-`.
#     Это ловит как `replace-with-openssl-rand-hex-32` (GATEWAY_HMAC_KEY,
#     *_GATEWAY_TOKEN), так и `replace-me-with-openssl-rand-hex-32`
#     (PROXY_SECRET).
bash scripts/check-file-excludes-pattern.sh \
    .env \
    '^[A-Z_][A-Z0-9_]*=replace-' \
  || { echo "[!] В .env остались плейсхолдеры." >&2
       echo "    Проверьте, что все обязательные переменные заполнены." >&2
       exit 1; }

bash scripts/check-file-excludes-pattern.sh \
    config/gateway_clients.yaml \
    'REPLACE_WITH_[A-Z0-9_]+_HASH' \
  || { echo "[!] В config/gateway_clients.yaml остались placeholder'ы." >&2
       echo "    Проверьте, что имя клиента в CLIENTS() соответствует" >&2
       echo "    PREFIX = name.upper().replace('-','_') в .env и YAML." >&2
       exit 1; }

echo
echo "[+] Bootstrap завершён. Для работы:"
echo "    $DOCKER compose exec harness python -m harness.main"
echo
echo "[i] Проверка изоляции (должно завершиться ошибкой):"
echo "    $DOCKER compose exec harness python -c \"import socket; socket.create_connection(('1.1.1.1',53),timeout=2)\""
