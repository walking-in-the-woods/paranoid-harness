# Разработка

## Тесты

```bash
# Юнит-тесты (без модели)
pytest tests/ --ignore=tests/smoke -v

# Smoke (нужна запущенная Ollama)
OLLAMA_HOST=http://127.0.0.1:11434 \
SMOKE_MODEL=qwen3:1.7b \
SMOKE_TOOL_CAPABLE=true \
  pytest tests/smoke -m smoke -v -s
```

| Файл | Что покрывает |
|---|---|
| `test_glob_to_regex.py` | Семантика `*`, `**`, `?` |
| `test_fs_guard.py` | Path traversal, symlink, NFKC, списки, расширения, семантика пустого whitelist |
| `test_injection_guard.py` | Нормализация, детекция, `neutralize_data_block` (расширенный набор тегов), `scan_payload` |
| `test_confirm.py` | Nonce, diff, атомарная запись, forbidden path, mode 0o644 |
| `test_audit.py` | JSONL-формат, устойчивость к ошибкам ФС, durable и non-durable события |
| `test_agent_tools.py` | Все tool-функции, `_redact_args`, `_wrap_tool_result`, `canonical_rel`, read-after-write (включая end-to-end) |
| `test_proxy.py` | Route→URL, auth, `follow_redirects`, лимит тела |

## CI

`.github/workflows/ci.yml`:

- **unit-tests** — без модели, ~10 мин.
- **smoke-test** — matrix `qwen3:0.6b` (без tool) + `qwen3:1.7b` (с tool).

Модели для тестов читаются из repo variables с фолбэком на дефолт.

## Стиль

- Docstring — на русском, имена и код — на английском.
- Инварианты — в комментариях там, где их легко потерять при
  рефакторинге.
- Новый тест-инвариант добавляется вместе с правкой, которая его
  вводит.

## Куда смотреть, если меняете

- **`agent_loop.py`** — поведение инструментов, формат `<tool_result>`,
  лимиты. После правок — прогнать smoke с `qwen3:1.7b`.
- **`fs_guard.py`** — политики путей и расширений. После правок —
  убедиться, что `_glob_to_regex` тесты проходят.
- **`injection_guard.py`** — эвристики и нейтрализация. Не убирать
  `neutralize_data_block` без замены. Расширяя `_TAG_RE`, добавляйте
  тесты в `test_neutralize_escapes_extended_tag_set`.
- **`confirm.py`** — nonce и атомарность. `chmod 0o644` — намеренно.
- **`audit.py`** — не добавлять `fsync` для информационных событий.
- **`scripts/sync-model.sh`** — при добавлении новых зависимостей
  (например, `jq`) добавляйте проверку `command -v` в начале скрипта.

## Локальная сборка документации

```bash
pip install mkdocs-material "mkdocstrings[python]"
mkdocs serve
# http://127.0.0.1:8000
```

## Проверка перед коммитом

```bash
# 1. Юнит-тесты
pytest tests/ --ignore=tests/smoke -v

# 2. Синтаксис всех shell-скриптов
for f in scripts/*.sh; do bash -n "$f" || echo "FAIL: $f"; done

# 3. Compose валиден
sudo docker compose config >/dev/null && echo "compose OK"

# 4. Если менялся injection_guard.py — тесты на расширенный набор тегов
pytest tests/test_injection_guard.py -v
```

## Что не делать

- **Не полагаться на эвристики `InjectionGuard` как на основную
  защиту.**
- **Не расширять `SYSTEM_PROMPT`** — он минимальный намеренно.
- **Не добавлять ML-классификатор инъекций** — см. `design-notes.md`.
- **Не заменять `sudo docker` на группу `docker`.**
