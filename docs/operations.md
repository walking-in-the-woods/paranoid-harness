# Эксплуатация

Что делать после установки: бэкапы, ротация, обновления, восстановление.

## Что бэкапить

| Что | Зачем | Как часто |
|---|---|---|
| `workspace/` | Ваши данные и результаты | По важности данных |
| `config/fs_policy.yaml` | Политики доступа | После каждой правки |
| `.env` | Секреты, UID/GID, имя модели | После изменения |
| `uv.lock`, `pyproject.toml` | Воспроизводимость окружения | При обновлении зависимостей |
| `ollama-models-verified.sha256` | Манифест модели | После `sync-model.sh` |
| `logs/audit.jsonl` | История операций | Опционально, для форензики |

## Что **не** бэкапить

- `ollama-models-verified` — восстанавливается через `sync-model.sh`.
- `ollama-models-staging` — временный том updater'а.
- `__pycache__`, `.pytest_cache` — кэши.

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
./setup.sh
cd harness-project

# 3. Распаковать бэкап
tar xzf ~/harness-backup-2026-09-11.tgz

# 4. Bootstrap
./bootstrap.sh
```

## Ротация `audit.jsonl`

**Ручная ротация:**

```bash
cd harness-project/logs
mv audit.jsonl audit-$(date +%F).jsonl
gzip audit-*.jsonl
```

**Автоматическая ротация через `logrotate`:**

Готовый шаблон лежит в `config/logrotate.harness`. Установка:

```bash
sed "s|@PROJECT_PATH@|$(pwd)|; s|@UID@|$(id -u)|; s|@GID@|$(id -g)|" \
  config/logrotate.harness | sudo tee /etc/logrotate.d/harness

sudo logrotate -d /etc/logrotate.d/harness
```

**Почему `copytruncate`:** `AuditLog` пишет через `open(..., "a")`,
не удерживая файловый дескриптор между вызовами.

### Известные ограничения audit-лога

- **Пути в логе не редактируются.** `_redact_args` скрывает
  `content`, `body`, `params`. Но `path` остаётся как есть.
- **`fsync` только для критичных событий.** `apply_result`,
  `session_start`, `session_end`, `propose_write`,
  `user_prompt_blocked`, `ollama_error` пишутся с `fsync`.
- **Ротация не автоматизирована в compose.** Шаблон в
  `config/logrotate.harness` нужно установить вручную.

## Обновление модели

```bash
cd harness-project
./scripts/sync-model.sh
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

ALPINE_IMAGE=alpine@sha256:<digest> ./scripts/sync-model.sh
```

## Смена `PROXY_SECRET`

Секрет читается на импорте модуля — **пересборка обязательна**.

```bash
NEW=$(openssl rand -hex 32)
sed -i "s|^PROXY_SECRET=.*|PROXY_SECRET=$NEW|" .env
sudo docker compose build api-proxy
sudo docker compose up -d --force-recreate api-proxy harness
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
du -h logs/audit.jsonl
df -h .
sudo docker compose exec ollama-runner ollama list
```

**Anomaly-детекция на audit-логе:**

```bash
jq -r 'select(.event=="propose_write") | .path' logs/audit.jsonl | sort | uniq -c
jq 'select(.event=="user_prompt_blocked")' logs/audit.jsonl
```

## Восстановление после сбоя

**Харнесс не стартует:**

```bash
sudo docker compose logs harness
sudo docker compose config
```

**Модель не загружается:**

```bash
sudo docker compose exec ollama-runner ollama list
./scripts/sync-model.sh qwen3:8b
```

**Потерян `.env`:**

```bash
cp .env.example .env
# вписать PROXY_SECRET (тот же, что был — иначе пересобрать api-proxy)
# вписать UID, GID
```

**Потерян `uv.lock`:**

```bash
export PATH="$HOME/.local/bin:$PATH"
uv lock
uv sync --locked
```

## Что делать перед длительным простоем

1. Сохранить бэкап `workspace/` и `.env`.
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
2. Сохранить `logs/audit.jsonl` для анализа.
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
6. Пересоздать окружение с чистого `setup.sh`, восстановить только
   `workspace/` и `config/`.
