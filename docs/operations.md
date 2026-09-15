# Эксплуатация

Что делать после установки: бэкапы, ротация, обновления, восстановление.

## Что бэкапить

| Что | Зачем | Как часто |
|---|---|---|
| `workspace/` | Ваши данные и результаты | По важности данных |
| `config/fs_policy.yaml` | Политики доступа | После каждой правки |
| `config/gateway_clients.yaml` | Токены и профили клиентов гейтвея | После изменения |
| `.env` | Секреты, UID/GID, имя модели | После изменения |
| `uv.lock`, `pyproject.toml` | Воспроизводимость окружения | При обновлении зависимостей |
| `ollama-models-verified.sha256` | Манифест модели | После `sync-model.sh` |
| `logs/audit.jsonl`, `logs/gateway.jsonl` | История операций | Опционально, для форензики |

**`certs/` в бэкап не входит.** CA и клиентские сертификаты
восстанавливаются заново (`gateway-certs.sh`); `ca.key` хранится
отдельно в offline-хранилище.

## Что **не** бэкапить

- `ollama-models-verified` — восстанавливается через `sync-model.sh`.
- `ollama-models-staging` — временный том updater'а.
- `__pycache__`, `.pytest_cache` — кэши.
- `certs/` — генерируется `gateway-certs.sh`.

## Бэкап

```bash
cd harness-project

tar czf ~/harness-backup-$(date +%F).tgz \
  workspace/ \
  config/ \
  .env \
  uv.lock \
  pyproject.toml \
  ollama-models-verified.sha256
```

## Восстановление на новой машине

```bash
# 1. Установить Docker и uv
./install-machine.sh
source ~/.bashrc

# 2. Развернуть файлы проекта
git clone https://github.com/walking-in-the-woods/paranoid-harness.git
cd paranoid-harness

# 3. Распаковать бэкап
tar xzf ~/harness-backup-2026-09-11.tgz

# 4. Bootstrap
./scripts/bootstrap.sh
```

## Ротация audit-логов

Ротируются два файла: `logs/audit.jsonl` (harness) и
`logs/gateway.jsonl` (model-gateway).

**Ручная ротация:**

```bash
cd harness-project/logs
mv audit.jsonl audit-$(date +%F).jsonl
mv gateway.jsonl gateway-$(date +%F).jsonl
gzip *.jsonl
```

**Автоматическая ротация через `logrotate`:**

Готовый шаблон лежит в `config/logrotate.harness`. Установка:

```bash
sed "s|@PROJECT_PATH@|$(pwd)|; s|@UID@|$(id -u)|; s|@GID@|$(id -g)|" \
  config/logrotate.harness | sudo tee /etc/logrotate.d/harness

sudo logrotate -d /etc/logrotate.d/harness
```

**Почему `copytruncate` для audit.jsonl:** `AuditLog` пишет через
`open(..., "a")`, не удерживая файловый дескриптор между вызовами.

**Почему `create` без `copytruncate` для gateway.jsonl:** `AuditWriter`
открывает файл на каждый `write`, не удерживает дескриптор.
Ротация без `copytruncate` не теряет данные.

### Известные ограничения audit-логов

- **Пути в логе не редактируются.** `_redact_args` скрывает
  `content`, `body`, `params`. Но `path` остаётся как есть.
- **`fsync` только для критичных событий.** В `audit.jsonl`:
  `apply_result`, `session_start`, `session_end`, `propose_write`,
  `user_prompt_blocked`, `ollama_error`. В `gateway.jsonl`:
  `gateway_start`, `gateway_stop`, `request_rejected`, `rate_limited`,
  `upstream_error`.
- **Ротация не автоматизирована в compose.** Шаблон в
  `config/logrotate.harness` нужно установить вручную.

## Обновление модели

```bash
cd harness-project
bash scripts/sync-model.sh
```

Скрипт:

1. Поднимает `ollama-updater`.
2. `ollama pull`.
3. Если `HARNESS_MODEL_DIGEST` задан — сверяет digest.
4. Создаёт `.tgz`-снапшот, считает SHA256.
5. Промоутит в runner-volume с манифестом.
6. Перезапускает `ollama-runner`, останавливает updater.

### Digest-верификация модели

Если в `.env` задан `HARNESS_MODEL_DIGEST=sha256:<hex>`, `sync-model.sh`
сверяет digest скачанной модели до промоушена.

**Как получить digest:**

```bash
docker exec ollama-updater ollama list --json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
    m=[x for x in (d.get('models') or d) if x.get('name')=='qwen3:8b'][0]; \
    print(m['digest'])"
```

### Ограничения digest-верификации

Проверка `HARNESS_MODEL_DIGEST` защищает от **последующей** подмены
тега. Она не даёт гарантии подлинности при **первом** pull.

Почему: если вы берёте ожидаемый digest из того же источника, что и
сам pull, компрометация реестра приведёт к совпадению digest на
вредоносной версии.

**Что делать для защиты от компрометации реестра:**

1. Использовать **out-of-band** источник ожидаемого digest.
2. Первый `sync-model.sh` выполнять в доверенном окружении.
3. После первого pull сохранять `ollama-models-verified.sha256` и
   `HARNESS_MODEL_DIGEST`.

### Мутабельность `alpine:3.19` в sync-model

`sync-model.sh` использует временный контейнер для промоушена.
По умолчанию — `alpine:3.19` **по тегу**. Для production задайте
`ALPINE_IMAGE=alpine@sha256:<digest>`.

```bash
docker pull alpine:3.19
docker inspect --format='{{index .RepoDigests 0}}' alpine:3.19

ALPINE_IMAGE=alpine@sha256:<digest> bash scripts/sync-model.sh
```

## Смена `PROXY_SECRET`

`PROXY_SECRET` читается контейнерами `api-proxy` и `harness` на
импорте/старте. `harness` передаёт его в `api-proxy` через заголовок
`X-Proxy-Secret`. Пересборка `api-proxy` и перезапуск `harness`
обязательны.

```bash
NEW=$(openssl rand -hex 32)
sed -i "s|^PROXY_SECRET=.*|PROXY_SECRET=$NEW|" .env
sudo docker compose build api-proxy
sudo docker compose up -d --force-recreate api-proxy harness
```

## Смена `GATEWAY_HMAC_KEY`

`GATEWAY_HMAC_KEY` используется `model-gateway` для `prompt_hash` в
`logs/gateway.jsonl`. Старые записи после смены ключа больше не
коррелируются по хешу — это ожидаемо. Пересборка не нужна — только
перезапуск контейнера.

```bash
sed -i "s|^GATEWAY_HMAC_KEY=.*|GATEWAY_HMAC_KEY=$(openssl rand -hex 32)|" .env
sudo docker compose up -d --force-recreate model-gateway
```

## Смена `OLLAMA_IMAGE`

`OLLAMA_IMAGE` в `.env` — образ для `ollama-runner` и
`ollama-updater`. Для paranoid-режима задайте digest:

```bash
docker pull ollama/ollama:latest
docker inspect --format='{{index .RepoDigests 0}}' ollama/ollama:latest
# OLLAMA_IMAGE=ollama/ollama@sha256:<hex> в .env
sudo docker compose up -d --force-recreate ollama-runner
```

## Обновление зависимостей Python

```bash
export PATH="$HOME/.local/bin:$PATH"
uv add "httpx>=0.28.0"
uv lock
uv sync --locked
uv run pytest tests/ --ignore=tests/smoke -v
```

## Обновление самого харнесса

```bash
# 1. Бэкап
tar czf ~/harness-before-upgrade-$(date +%F).tgz \
  workspace/ config/ .env uv.lock

# 2. Сравнить новую и старую версию setup.sh
diff <(cat старый-setup.sh) <(cat новый-setup.sh)

# 3. Если только файлы кода изменились — скопировать, пересобрать, перезапустить.
```

## Мониторинг

```bash
sudo docker compose logs --since 1h | grep -i error
du -h logs/audit.jsonl logs/gateway.jsonl
df -h .
sudo docker compose exec ollama-runner ollama list
```

**Anomaly-детекция на audit-логе:**

```bash
jq -r 'select(.event=="propose_write") | .path' logs/audit.jsonl | sort | uniq -c
jq 'select(.event=="user_prompt_blocked")' logs/audit.jsonl
```

**Anomaly-детекция на gateway-логе:**

```bash
jq -r 'select(.event=="request") | .client' logs/gateway.jsonl | sort | uniq -c
jq 'select(.event=="rate_limited")' logs/gateway.jsonl
jq 'select(.event=="auth_fail")' logs/gateway.jsonl
jq 'select(.event=="response" and .duration_ms > 30000)' logs/gateway.jsonl
```

## Восстановление после сбоя

**Харнесс не стартует:**

```bash
sudo docker compose logs harness
sudo docker compose config
```

**Model-gateway не стартует:**

```bash
sudo docker compose logs model-gateway
# Частая причина: пустой или неполный config/gateway_clients.yaml
# или отсутствие /certs/ca.crt. Проверьте:
ls -la certs/
grep -c "token_sha256" config/gateway_clients.yaml
```

**Gateway-tls не стартует:**

```bash
sudo docker compose logs gateway-tls
# Частая причина: /certs/server.key не смонтирован или права 0600
# без root у master. Проверьте:
ls -la certs/server.key
```

**Модель не загружается:**

```bash
sudo docker compose exec ollama-runner ollama list
bash scripts/sync-model.sh qwen3:8b
```

**Потерян `.env`:**

```bash
cp .env.example .env
# вписать PROXY_SECRET, GATEWAY_HMAC_KEY (те же, что были — иначе
# пересобрать api-proxy и перезапустить model-gateway)
# вписать UID, GID
# вписать HARNESS_GATEWAY_TOKEN, WEBUI_GATEWAY_TOKEN
```

**Потерян `uv.lock`:**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv lock
uv sync --locked
```

## Что делать перед длительным простоем

1. Сохранить бэкап `workspace/`, `config/`, `.env`.
2. Зафиксировать версию модели.
3. Остановить контейнеры (не удалять volume):
   ```bash
   sudo docker compose down
   ```

## Что делать при подозрении на компрометацию

1. **Немедленно** остановить харнесс:
   ```bash
   sudo docker compose down
   ```
2. Сохранить `logs/audit.jsonl` и `logs/gateway.jsonl` для анализа.
3. Проверить `workspace/output/` и `workspace/notes/`.
4. Проверить целостность моделей:
   ```bash
   cat ollama-models-verified.sha256
   sudo docker run --rm -v ollama-models-verified:/m:ro \
     alpine sh -c 'cd /m && sha256sum -c .snapshot.sha256'
   ```
5. Проверить целостность `uv.lock`:
   ```bash
   git diff uv.lock
   ```
6. Если подозревается компрометация CA:
   - `sudo docker compose stop model-gateway gateway-tls`
   - удалить `certs/ca.*`
   - перегенерировать: `bash scripts/gateway-certs.sh certs harness webui`
   - ротировать токены: очистить `token_sha256` в YAML и в `.env`,
     запустить `bash scripts/bootstrap.sh`
   - `sudo docker compose up -d`
7. Пересоздать окружение с чистого клона, восстановить только
   `workspace/`, `config/`, `.env`.

## Требования к инструментам

* `openssl` ≥ 1.1.1 (`-addext` в `req -x509`, SAN в x509 v3).
  Ubuntu 20.04+, Debian 11+, macOS 11+ подходят.
* GNU sed ≥ 4.2 (`sed -i --follow-symlinks` в `pin-images.sh`).
  macOS не поддерживается.
* bash ≥ 4.4 (guard на пустой ассоциативный массив в
  `verify-project.sh`).
* Python ≥ 3.10 (`requires-python = ">=3.12"` в `model_gateway`;
  unit-тесты работают на 3.10+).
* `python3` — только для опциональной digest-верификации модели.

## CI: strict-режим для release-ветки

Шаг `Check image pinning` в CI:

* **Всегда** (включая dev): error на `REPLACE_WITH_PINNED_DIGEST`
  и на `:latest`.
* **Warning** (dev): теги без digest.

Для release-ветки (`main`/`release-*`) `--strict` переводит
warning в error.

## Проверка SAN в выпущенных сертификатах

```bash
openssl x509 -in certs/harness.crt -noout -ext subjectAltName
# X509v3 Subject Alternative Name: critical
#     DNS:harness
```

Если SAN отсутствует или CN ≠ SAN — сертификат не пройдёт
верификацию в гейтвее. Перегенерируйте через
`bash scripts/gateway-certs.sh`.

## Проверка server.crt перед деплоем

```bash
openssl x509 -in certs/server.crt -noout -text \
  | grep -E "Subject Alternative Name|Extended Key Usage" -A1
```

Гейтвей при старте проверяет: expiry, EKU=serverAuth, SAN содержит
`gateway-tls`. Несоответствие → отказ старта.
