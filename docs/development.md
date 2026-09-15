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
| `test_gateway.py` | Auth (mTLS + token), проверка `X-Client-Verify`, профили, clamps, body limit, stream policy, prompt_hash HMAC |
| `test_cert_verifier.py` | Полная валидация client-сертификата: EKU, KU, BC, SAN, sig alg, срок |
| `test_server_cert_check.py` | `check_server_cert`: EKU, SAN, symlink, criticality, срок |

## CI

`.github/workflows/ci.yml`. Три job'а, все на `ubuntu-latest`, Python 3.12:

### `static-checks`

Линтеры, static-checks, self-tests. Выполняется на каждый push/PR.

1. `Ensure scripts are executable` — `chmod 0755 scripts/*.sh scripts/*.py`.
2. `Syntax check` — `python -m py_compile` для Python-модулей,
   `bash -n` для shell-скриптов.
3. `Check image pinning` — `scripts/check-image-pinning.py`. Проверяет
   все четыре Dockerfile (`model_gateway`, `gateway_tls`, `api_proxy`,
   `harness`) и `docker-compose.yml`. В ветках `main`/`release-*` с
   `--strict` (warning → error).
4. `Verify cert generation` — `scripts/gateway-certs.sh`, проверка
   SAN и EKU у клиентских сертификатов.
5. `Import check` — импорт `model_gateway/gateway.py` и
   `cert_verify.py` с валидным конфигом и негативный тест без
   `GATEWAY_CONFIG`.
6. `Import cert_verify alone`.
7. `Verify check-smoke-cleanup.sh has single ls line`.
8. `Verify docs/development.md hygiene`.
9. `Run self-tests` — `scripts/run-self-tests.sh`, все
   `scripts/self-test-*.sh`. Проверка реального `ci.yml` на
   запрещённые имена файлов включена в `self-test-filename-pattern.sh`.
10. `Verify CI uses runner` — `check-workflow-uses-runner.py`.
11. `Verify ${OLDPWD} not used`.

### `tests`

Unit-тесты (`tests/ --ignore=tests/smoke`). Зависимости —
`harness/requirements.txt` + `requirements-dev.txt`. Smoke-тесты
отключены: требуют запущенной Ollama.

### `docker-smoke`

Реальная сборка `gateway-tls` и его запуск с самоподписанными
сертификатами. Проверки:

- `cap_add` = `{CHOWN, SETUID, SETGID}` в `docker compose config`;
- `nginx -t` в собранном контейнере;
- `/tmp/nginx` создан и принадлежит `nginx`;
- в логах nginx нет `chown`/`mkdir` failure;
- healthcheck `http://127.0.0.1:8081/health` отвечает;
- после `up -d` артефакты `certs-smoke/` и
  `docker-compose.smoke.yml` не остаются (шаг с `if: always()`).

### Локально

Полный эквивалент CI (кроме `docker-smoke`):

```bash
./scripts/verify-project.sh
```

Скрипт запускает 10 секций: ci.yml hygiene, проверка инварианта
workflow, self-tests через bash, `-f`/`-r` в self-tests, spot-check
символов `gateway.py`, symlink-тесты через pytest, `import re`
через ast, все self-tests, chmod, unit-тесты pytest.

## Self-tests

Каждая нетривиальная проверка в CI сопровождается self-test'ом,
который подтверждает срабатывание на негативном входе. Проверка
без self-test'а считается непроверенной.

Self-tests лежат в `scripts/self-test-*.sh` и запускаются через
`scripts/run-self-tests.sh`. Runner обнаруживает их автоматически
(`find` по имени), добавление нового self-test'а не требует правки
runner'а или CI.

Правило «текст = код»: если в описании правки сказано «проверено
локально» — прилагается запускаемая команда или self-test. Фраза
без артефакта не считается проверкой.

Исторические прецеденты, из-за которых правило введено:

* флаг `--strict` в `check-image-pinning.py` не активировался
  (путаница `args` / `sys.argv[1:]`);
* регексп для однобуквенных имён требовал лишнюю кавычку и всегда
  возвращал `OK`.

Оба — проверки, которые молча проходили. Self-test устраняет класс.

## Формат отчёта о работе

Ответ на замечания аудита строится по шаблону:

1. **Что меняю** — список правок с обоснованием.
2. **Артефакты** — код или diff документов, только изменённые
   фрагменты.
3. **Проверка** — для каждой правки запускаемая команда + ожидаемый
   вывод. Если правка — это проверка, прилагается самопроверка:
   сценарий, где проверка срабатывает, и где не срабатывает.
4. **Итог** — одна-две строки, без рефлексии.

Не входят в формат:

* раздел «Что остаётся» — остаточные риски в `docs/security-model.md`,
  один источник;
* раздел «Процессуально» — рефлексия не является артефактом;
* раздел «Что это даёт по сравнению с предыдущим» — читатель видит
  diff.

Снапшот кода — все новые и изменённые файлы кода проекта, целиком.
Если заявлено «полный снапшот», значит все файлы, без отсылок.
Документация (`docs/*.md`) — отдельный слой: изменения видны в
истории git; при необходимости прикладываются конкретные
добавленные разделы.

## Стиль имён

Правило проекта:

* **Файлы, функции, классы, публичные переменные** — говорящие имена.
  `check_server_cert`, `CertVerifier`, `prompt_hash_hmac_key`.
* **Однобуквенные** (`i`, `j`, `k`, `n`) — только счётчики циклов
  в 1–3 строках, где контекст однозначен.
* **Короткие аббревиатуры** (`msg`, `req`, `resp`, `cfg`) — допустимы
  в узких контекстах, если общеприняты.
* **Однобуквенные параметры публичных функций запрещены.** Внутри
  однострочного comprehension — допустимо.
* **Имена файлов-тестов и CI-кейсов** — говорящие. `A`, `B`, `case1`
  не используются: при чтении логов CI должно быть понятно, какой
  сценарий упал.

Однобуквенные имена в нетривиальном контексте — блокер merge'а.

## Известные ограничения

* **mTLS-handshake в smoke** — smoke проверяет старт nginx, но не
  end-to-end mTLS-подключение клиента. TODO: добавить
  `openssl s_client` с клиентским сертификатом.
* **Heredoc в Dockerfile** — `check-image-pinning.py` матчит `FROM`
  внутри `RUN <<EOF`. В проекте heredoc не используется.
* **Паттерн `[A-Ja-j]`** — частичная эвристика для исторических
  кейсов A–J; расширение до `[A-Za-z]` даёт ложные срабатывания на
  `$HOME/x`. Компромисс задокументирован в комментарии CI-шага.
* **BSD sed** — `pin-images.sh --update` использует `sed -i
  --follow-symlinks` (GNU sed ≥ 4.2). macOS не поддерживается.
* **Env-валидация при импорте** — `gateway.py` вызывает `load_config`
  на уровне модуля. Fail-fast, осознанно.

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
- **`gateway.py`** — профили, clamps, аудит. При изменении профилей —
  добавить тест в `test_gateway.py`.
- **`cert_verify.py`** — верификация сертификатов. Расширяя проверки —
  добавить тест в `test_cert_verifier.py` или
  `test_server_cert_check.py`.
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
# 1. Все self-tests и unit-тесты
./scripts/verify-project.sh

# 2. Синтаксис всех shell-скриптов
for f in scripts/*.sh; do bash -n "$f" || echo "FAIL: $f"; done

# 3. Compose валиден
sudo docker compose config >/dev/null && echo "compose OK"
```

## Что не делать

- **Не полагаться на эвристики `InjectionGuard` как на основную
  защиту.**
- **Не расширять `SYSTEM_PROMPT`** — он минимальный намеренно.
- **Не добавлять ML-классификатор инъекций** — см. `design-notes.md`.
- **Не заменять `sudo docker` на группу `docker`.**
