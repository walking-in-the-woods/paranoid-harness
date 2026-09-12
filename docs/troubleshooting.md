# Диагностика

## Модель не отвечает

**Симптом:** `[ollama error] ...` или пустой ответ.

**Проверьте:**

```bash
# ollama-runner жив
sudo docker compose ps ollama-runner

# модель загружена
sudo docker compose exec ollama-runner ollama list

# healthcheck
sudo docker inspect --format='{{.State.Health.Status}}' ollama-runner
```

**Частые причины:**

| Причина | Решение |
|---|---|
| Модель не загружена | `./scripts/sync-model.sh qwen3:8b` |
| `HARNESS_MODEL` в `.env` не совпадает с загруженной | Поправить `.env`, перезапустить `harness` |
| Модель не влезает в RAM | Уменьшить размер: `qwen3:1.7b` вместо `qwen3:8b` |
| `ollama-runner` не стартовал | `sudo docker compose logs ollama-runner` |

## Модель не вызывает инструменты

**Симптом:** модель отвечает текстом, но не читает файлы и не
предлагает запись.

**Причина:** модель не поддерживает tool calling или слишком мала.

**Проверка:**

```bash
sudo docker compose exec ollama-runner ollama show qwen3:8b | grep -i tools
```

**Работающие модели:** `qwen3:1.7b` и выше, `llama3.1:8b`,
`mistral-nemo`, `granite3.3:8b`, `hermes3:8b`, `command-r`.

**Не работают для tool calling:** `qwen3:0.6b` (слишком мала),
`llama2`, `gemma2`, `phi-3-mini`.

## `ACCESS DENIED: not in whitelist`

**Что произошло:** модель обратилась к пути, которого нет в
`whitelist`.

**Проверьте `config/fs_policy.yaml`:**

```yaml
whitelist:
  - "**"                 # по умолчанию — всё видно
```

Пустой `whitelist: []` означает «ничего не разрешено» — это не то же
самое, что «разрешить всё». Если у вас узкий whitelist, добавьте
нужный glob. Перезапускать контейнер не нужно — новый REPL подхватит
изменения.

## `ACCESS DENIED: in blacklist`

**Что произошло:** путь прошёл whitelist, но попал в blacklist.

**Частая причина:** попытка прочитать `pyproject.toml`, `Makefile`,
`.github/workflows/*`, `package.json` — они в чёрном списке по
умолчанию (persistence/CI-файлы).

**Что делать:**

- Если файл нужен только для чтения — можно вынести его из чёрного
  списка точечно:
  ```yaml
  blacklist:
    - "**/.git/**"
    # - "**/pyproject.toml"   # закомментировано
  ```
- Если нужно записать — потребуется ещё и правка `WRITE_EXT_BLOCK`
  в `harness/fs_guard.py` и пересборка образа.

## `REJECTED: path not in writable list`

**Что произошло:** модель предложила запись вне `writable`.

**По умолчанию разрешены:**

```
notes/**, output/**, drafts/**, docs/**, *.md, *.txt
```

**Решение:** попросите модель переписать в `output/` или `notes/`:

```
перепиши резюме в output/summary.md
```

## `REJECTED: extension '.py' blocked`

**Что произошло:** модель предлагает записать `.py`, `.js`, `.sh` и
другой исполняемый файл.

**Почему так:** защита от отложенного исполнения. Скрипты не пишутся
автоматически, потому что вы можете запустить их и не заметить
подвоха.

**Решение:** попросите сохранить как `.txt`:

```
сохрани этот скрипт как output/script.txt, я запущу вручную
```

## `[CANCELLED] Код не совпал`

**Что произошло:** введён неверный nonce.

**Ничего не сломалось.** Файл не записан, состояние не изменилось.
Можно попросить модель ещё раз или отменить задачу.

## `[DENIED]` после ввода правильного кода

**Что произошло:** между показом diff и записью изменилось состояние
системы (TOCTOU). Возможные причины:

- Файл успел создаться параллельно.
- Права на директорию изменились.
- Кто-то изменил `config/fs_policy.yaml`.

**Решение:** проверить, что в `workspace/output/` ничего не появилось
извне, и повторить.

## `ERROR: file too large`

**Лимит:** 200 КБ на чтение (`MAX_READ_BYTES`).

**Что делать:**

- Разбить файл на части.
- Поднять лимит в `harness/agent_loop.py`, пересобрать `harness`.

## `502 upstream error` при `api_call`

**Что произошло:** внешний API недоступен или отвечает медленно.

**Проверьте вручную:**

```bash
curl -sS "https://api.open-meteo.com/v1/forecast?latitude=55.75&longitude=37.62&current=temperature_2m" | head
```

Если curl тоже не работает — проблема на стороне сервиса, не ваша.
Список маршрутов: `api_proxy/proxy.py` → `ROUTES`.

## `api proxy not configured`

**Что произошло:** `API_PROXY_URL` или `PROXY_SECRET` пустые.

**Проверьте:**

```bash
grep -E '^(PROXY_SECRET|API_PROXY_URL)' .env
sudo docker compose exec harness env | grep -E 'PROXY|API_PROXY'
```

**Решение:** заполнить `.env`, перезапустить `harness` и `api-proxy`.

## Permission denied при записи в `workspace/`

**Что произошло:** UID/GID в контейнере не совпадают с владельцем
`./workspace` на хосте.

**Проверьте:**

```bash
id -u; id -g
grep -E '^(UID|GID)' .env
ls -ld workspace
```

**Решение:** подставить реальные `id -u` и `id -g` в `.env`,
перезапустить `harness`:

```bash
sudo docker compose up -d --force-recreate harness
```

## Контейнер harness падает при старте

**Проверьте логи:**

```bash
sudo docker compose logs harness
```

**Частые причины:**

| Сообщение | Решение |
|---|---|
| `[fatal] policy not found: /config/fs_policy.yaml` | Проверить, что `./config/` существует и смонтирован |
| `cannot initialize fs guard: workspace root does not exist` | Проверить, что `./workspace/` существует |
| `Permission denied` в логах | Совпадают ли UID/GID (см. выше) |

## `audit.jsonl` растёт без остановки

**Причина:** каждый `tool_call` и каждый `propose_write` пишутся в
лог.

**Решение:** периодическая ротация:

```bash
# Раз в неделю
mv logs/audit.jsonl logs/audit-$(date +%F).jsonl
gzip logs/audit-*.jsonl
```

**Долгосрочно:** установите `config/logrotate.harness` в
`/etc/logrotate.d/harness`. См. `docs/operations.md`.

## Модель вернула `<tool_result>` как текст

**Симптом:** в ответе модели видно `<tool_result ...>`.

**Причина:** модель не распознала tool-сообщение (не поддерживает
tool calling), либо формат изменён в новой версии Ollama.

**Решение:**

1. Проверить версию Ollama.
2. Проверить модель на tool calling (см. выше).
3. Запустить smoke-тест: `pytest tests/smoke -m smoke -v -s`.

## Копирование файла не видно модели

**Что проверить:**

```bash
ls -la workspace/input/
sudo docker compose exec harness ls -la /workspace/input/
```

Если `ls` внутри контейнера не показывает файл — проблема с
bind-mount:

```bash
sudo docker inspect harness | grep -A2 Mounts
```

Ожидается строка `Source: .../workspace`, `Destination: /workspace`.

## Digest модели не совпадает

**Симптом:** `sync-model.sh` возвращает
`[!] Digest модели НЕ совпал`.

**Проверьте:**

```bash
# Digest загруженной модели:
sudo docker exec ollama-updater ollama list --json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
    m=[x for x in (d.get('models') or d) if x.get('name')=='qwen3:8b'][0]; \
    print(m['digest'])"

# Что задано в .env:
grep HARNESS_MODEL_DIGEST .env
```

Значения должны совпадать (префикс `sha256:` можно опустить).
Если не совпадают — либо скачалась другая версия модели, либо
подмена в реестре. Скачайте заново или уберите проверку из `.env`.

## `python3 не найден, но задан HARNESS_MODEL_DIGEST`

**Что произошло:** `sync-model.sh` требует `python3` для парсинга
JSON при digest-верификации.

**Решение:**

- Установить `python3`: `sudo apt install -y python3`
- Либо очистить `HARNESS_MODEL_DIGEST` в `.env`, если проверка не
  нужна.

## Docker GPG fingerprint не совпал

**Симптом:** `install-machine.sh` возвращает
`[!] Fingerprint GPG Docker не совпал` — либо на этапе установки
(fail-closed, установка прервана), либо при уже существующем keyring
(warn + ask).

**Причина:** либо скачался не тот ключ (MITM/подмена), либо сеть
вернула не ту страницу. Проверьте вручную:

```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  gpg --show-keys --with-fingerprint | tr -s ' '
```

Ожидаемый fingerprint:
`9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88`.

Если он отличается — **не продолжайте**. Проверьте, что
`download.docker.com` открывается правильно, что DNS не подменён,
что сертификат TLS валиден.

## Что смотреть в первую очередь

1. `logs/audit.jsonl` — что модель вызывала и с какими аргументами.
2. `sudo docker compose logs harness` — ошибки Python.
3. `sudo docker compose logs api-proxy` — если проблема с `api_call`.
4. `sudo docker compose logs ollama-runner` — если проблема с моделью.
