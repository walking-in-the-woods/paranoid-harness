# Установка

Инструкция по развёртыванию вынесена в отдельные документы, чтобы
держать её синхронной с текущей версией `setup.sh`. Здесь — только
контекст.

## Что понадобится

- Ubuntu 22.04 / 24.04 LTS (или Debian-совместимая) — для Linux;
  Windows 10 2004+ с WSL2 — для Windows
- `sudo`
- ~12 ГБ свободного места на диске: ~5 ГБ на модель `qwen3:8b`,
  ~2 ГБ на Docker-образы (python-slim + venv для `model-gateway`,
  nginx-alpine для `gateway-tls`, образы Ollama), ~5 ГБ запас на
  модели, кэш и временные файлы
- Docker 24+ с Compose v2
- На хосте: `openssl` ≥ 1.1.1 и `sha256sum` — для генерации
  сертификатов и токенов
- `python3` — только для опциональной digest-верификации модели
  (`HARNESS_MODEL_DIGEST`), если её включаете
- Python 3.12 (для юнит-тестов на хосте через `uv`)
- `uv` — ставится скриптом `install-machine.sh`

## Что разворачивается

- **`ollama-runner`** — модель, без доступа в интернет
  (`internal-net`).
- **`ollama-updater`** — контейнер загрузки моделей. Профиль
  `updater`, запускается только при обновлении модели. Образ
  подключается к `external-net`, но контейнер создаётся только при
  `docker compose --profile updater up`; в штатном режиме
  `docker compose up` контейнер `ollama-updater` не запускается, и
  его присутствие в `external-net` неактивно.
- **`gateway-tls`** — nginx с mTLS-терминацией. Принимает соединения
  от клиентов, пробрасывает сертификат в `model-gateway`.
- **`model-gateway`** — FastAPI-гейтвей: аутентификация по mTLS +
  токен, профили клиентов, rate limiting, audit в `logs/gateway.jsonl`.
- **`api-proxy`** — единственный **постоянно работающий** контейнер
  с выходом в интернет. `ollama-updater` тоже использует
  `external-net`, но только в режиме профиля `updater` (см. выше) —
  то есть в штатном режиме наружу смотрит лишь `api-proxy`.
- **`harness`** — REPL и агент.

Пять Docker-сетей: `gateway-net`, `gateway-internal-net`,
`internal-net`, `proxy-net`, `external-net`. Разделение trust
boundary: клиенты видят только `gateway-tls`; `ollama-runner`
доступен только `model-gateway`; интернет-маршрут есть у
`api-proxy` (постоянно) и у образа `ollama-updater` (при запуске по
профилю `updater`).

## Проверка целостности setup.sh

`bootstrap.sh` **не сверяет** sha256 `setup.sh` автоматически по
умолчанию — он делает `bash -n` и grep по опасным конструкциям.
Сверка хеша — ваша ответственность:

```bash
sha256sum setup.sh
# сравните вручную с ожидаемым хешем из документации к релизу
```

**Опциональная автоматическая проверка:**

```bash
./scripts/bootstrap.sh --verify-sha256=<ожидаемый-хеш>
```

**Формат хеша:** 64 hex-символа в нижнем регистре, без префикса
`sha256:`.

## Четыре шага установки

1. **Подготовка машины.** `install-machine.sh` ставит Docker и `uv`.
   Идемпотентен, fingerprint Docker GPG сверяется с официальным.
2. **Клонирование.** `git clone` из репозитория. `setup.sh` —
   альтернативный путь для air-gapped.
3. **Bootstrap.** `./scripts/bootstrap.sh` — создаёт `.env`,
   генерирует `uv.lock`, генерирует CA и клиентские сертификаты,
   генерирует токены клиентов и заполняет `config/gateway_clients.yaml`,
   собирает образы, загружает модель, поднимает все сервисы. В конце
   fail-closed проверяет, что в `.env` и `gateway_clients.yaml` не
   осталось плейсхолдеров.
4. **Работа.** `docker compose exec harness python -m harness.main`.

**После первого запуска** перенести `certs/ca.key` в offline-хранилище:
он нужен только для выдачи новых сертификатов, но не для работы.

## Проверка после установки

```bash
# 1. Изоляция harness
sudo docker compose exec harness python -c \
  "import socket; socket.create_connection(('1.1.1.1',53),timeout=2)"
# ожидается ошибка

# 2. Модель загружена
sudo docker compose exec ollama-runner ollama list

# 3. mTLS-гейтвей отвечает
sudo docker compose exec gateway-tls wget -qO- http://127.0.0.1:8081/health

# 4. Все self-tests и unit-тесты
./scripts/verify-project.sh
```

## Опционально: для машины с секретами

1. **Digest-пиннинг базовых образов** — до первого запуска.
   `bash scripts/pin-images.sh --update` заменит теги в Dockerfiles.
   См. `docs/operations.md`.
2. **Digest-пиннинг модели** — задайте `HARNESS_MODEL_DIGEST` в
   `.env`. Как получить digest — см. `docs/operations.md`.
   Помните про ограничение: digest защищает от последующей подмены
   тега, но не от компрометации реестра при первом pull.
3. **`read_only: true` на `ollama-runner`** — см.
   `docs/design-notes.md`, раздел capabilities.
4. **Offline-хранение `certs/ca.key`** — после генерации клиентских
   сертификатов.
