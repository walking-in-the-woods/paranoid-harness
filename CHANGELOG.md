# Changelog

| Версия | Тема |
|---|---|
| v0.1 | Initial |
| v0.2 | Hardening |
| v0.3 | Tests & CI |
| v0.4 | Real APIs & Polish |
| v0.5 | Polish |
| v0.6 | Truncation metadata as attributes |
| v0.7 | Idempotent installs, newer models, DRY |
| v0.8 | Security fixes after audit |
| v0.9 | Audit round 2 fixes |
| v0.10 | Audit round 3 fixes |
| v0.11 | Switch to GitHub repository |
| v0.12 | mTLS gateway, hardened CI, self-test suite |
| v0.13 | Post-release audit fixes (rounds 1–4) |

## v0.13 — Post-release audit fixes (rounds 1–4)

Серия правок по итогам четырёх итераций аудита после сборки v0.12.
Блокеры сняты, инварианты сохранены, добавлены defense-in-depth
проверки и уточнены формулировки.

### Added

- **`X-Client-Verify == "SUCCESS"` в `_authenticate`.** Defense-in-depth
  перед верификацией подписи сертификата: отсекает обход nginx
  (прямое подключение к `model-gateway` из соседнего контейнера в
  `internal-net`). nginx выставляет заголовок `$ssl_client_verify`;
  без nginx он отсутствует, запрос отвергается с 403 `mtls_not_verified`.
  Тесты `test_gateway.py` обновлены: `post_harness`, `post_webui`,
  `test_wrong_token_rejected` содержат `X-Client-Verify: SUCCESS`.
- **`test_missing_x_client_verify_rejected`** — новый тест, проверяет
  403 при отсутствии заголовка.
- **`_read_body_limited` в `api_proxy/proxy.py`.** Stream-based чтение
  тела с лимитом: Content-Length проверяется первым как дешёвый
  барьер, chunked-запросы без Content-Length считаются по мере
  чтения. Устраняет буферизацию тела в память до проверки размера.
- **`log.warning` в `_parse_tool_call`.** Три точки отказа логируют
  усечённый `repr(tc)[:200]` — диагностика malformed tool_call без
  риска раздуть лог. См. `docs/design-notes.md`, раздел «Остаточные
  риски».
- **`docs/design-notes.md`** — раздел «Остаточные риски» с записью
  про `log.warning` вне `_redact_args`.

### Fixed

- **CI self-reference.** Шаг «Verify no single-letter test filenames»
  вызывал `self-test-filename-pattern.sh` напрямую и детектировался
  собственным чекером `check-workflow-uses-runner.py` (возврат 1 на
  каждом прогоне CI). Шаг удалён; проверка реального `ci.yml`
  перенесена в `self-test-filename-pattern.sh`. `verify-project.sh`
  секция 2 переписана на `check-workflow-uses-runner.py` — секция
  теперь проверяет инвариант workflow, а не конкретный шаг.
- **`_stream_passthrough` — гарантированное освобождение семафоров.**
  `build_request` и `send` обёрнуты в `try/except BaseException` с
  `await on_done()`. Ранее ловился только `httpx.RequestError`;
  `ValueError` из `build_request` или `CancelledError` оставляли
  семафоры висеть → отказ в обслуживании честных клиентов.
- **`_parse_tool_call` — устойчив к malformed входу от модели.**
  Guard против `function=None`, нестрокового `name`, `tc` без поля
  `function`. Возврат `("", {})` вместо `TypeError`. `_dispatch`
  превращает в `"ERROR: unknown tool ''"` — модель получает
  обратную связь.
- **`global_auth_fail_per_minute: 10` несоразмерен профилю harness.**
  Per-IP лимитер вызывается до `verifier.verify`, а значит считает
  **все** попытки аутентификации, не только неудачные. Значение 10
  конфликтовало с `requests_per_minute: 120` для harness → 429
  после 10-го запроса в минуту. Поднято до 200 (×1.67 headroom к
  пиковой нагрузке harness). Комментарии в `config/gateway_clients.yaml`,
  `docs/security-model.md`, `docs/architecture.md` раскрывают
  семантику.

### Changed

- **`_extract_token` — docstring про недостижимость Bearer-fallback.**
  `gateway_tls/nginx.conf` выставляет `proxy_set_header Authorization ""`;
  fallback на `Authorization: Bearer` работает только при прямом
  подключении к `model-gateway` (отладочная конфигурация без nginx);
  в production-развёртывании он недостижим.
- **`_tool_propose_write` — статичное сообщение об отказе.**
  Regex-паттерн `p.pattern` больше не попадает в контекст модели:
  знание конкретной эвристики упрощало бы её обфускацию. Модель
  получает только факт отказа.
- **`test_missing_real_ip_rejected` — полный docstring.** Порядок
  проверок в `_authenticate` (шесть шагов, включая
  `_auth_fail_limiter.allow → 429`) задокументирован в docstring
  теста.
- **Удалён неиспользуемый импорт** `from datetime import datetime, timezone`
  в `model_gateway/gateway.py` (весь тайминг — через
  `time.strftime`/`time.gmtime`).

### Docs

- `docs/install.md` — уточнено: `ollama-updater` использует
  `external-net` только при `--profile updater up`; в штатном режиме
  контейнер не создаётся.
- `docs/security-model.md` — расширен список ролевых тегов
  (`tool_results`); уточнена формулировка про per-IP лимитер.
- `docs/architecture.md` — формулировка per-IP лимитера уточнена.
- `docs/development.md` — нумерация CI-шагов сдвинута после удаления
  шага «Verify no single-letter test filenames».
- `docs/reference/gateway.md` — раздел «Аутентификация» описывает
  обязательную проверку `X-Client-Verify == "SUCCESS"` до верификации
  подписи.
- `README.md` — уточнено, что `verify-project.sh` не покрывает
  `docker-smoke`, `Check image pinning` (применение к реальным
  Dockerfiles), `Verify cert generation`.

### Tests

- `test_missing_real_ip_rejected` — ассерт `== 500` (было `in (403, 500)`).
- `test_huge_body_rejected` — ассерт `== 413` (было `in (413, 422)`);
  middleware `_content_length_guard` срабатывает до routing.
- `tests/test_gateway.py` — docstring модуля уточнён: перечислены
  три исключения из правила «`X-Client-Verify` передаётся во всех
  тестах».

### Migration notes

- **Breaking (YAML):** `limits.global_auth_fail_per_minute`
  рекомендуется установить в 200 (или больше). Старое значение 10
  работало, но давало 429 на harness при нагрузке > 10 req/min.
- **Breaking (nginx):** клиенты, полагавшиеся на
  `Authorization: Bearer`, больше не могут использовать этот путь
  через `gateway-tls` — заголовок обнуляется на входе. Используйте
  `X-Gateway-Token`. Исключение — прямое подключение к
  `model-gateway` без nginx (отладочная конфигурация).

## v0.12 — mTLS gateway, hardened CI, self-test suite

### Added

- **`model_gateway/`** — тонкий FastAPI-гейтвей к Ollama:
  - аутентификация по mTLS (`X-Client-Cert` от nginx) + токен
    клиента (SHA256 в `config/gateway_clients.yaml`);
  - верификация подписи клиентского сертификата через
    `cryptography` — полный набор проверок (EKU=clientAuth,
    KeyUsage, BasicConstraints CA:FALSE, SignatureAlgorithm,
    SAN critical с ровно одним DNS);
  - проверка `X-Client-Verify` от nginx как defense-in-depth;
  - per-client профили: `tools_enabled`, `allowed_tools`,
    `forced_system_prompt`, `model_allowlist`, `requests_per_minute`,
    `max_concurrent`, `allow_stream`;
  - раздельные `_apply_profile_chat` и `_apply_profile_generate` —
    `/api/generate` не получает `messages`;
  - clamp `num_predict`, `num_ctx`, `keep_alive`; лимит тела запроса
    1 МБ; per-IP rate limit до аутентификации;
  - аудит в `logs/gateway.jsonl` — без содержимого промптов, с
    HMAC-SHA256 `prompt_hash` (length-prefix).
- **`gateway_tls/`** — nginx с TLS-терминацией и обязательным
  клиентским сертификатом. Пробрасывает сертификат в
  `X-Client-Cert`, статус верификации — в `X-Client-Verify`, IP — в
  `X-Real-IP`.
- **`.github/workflows/ci.yml`** — три job'а: `static-checks`,
  `tests`, `docker-smoke`.
- **`scripts/`** — `gateway-certs.sh`, `gateway-tokens.sh`,
  `pin-images.sh`, `verify-project.sh`, четыре чекера, два
  Python-чекера, runner self-test'ов, восемь self-test'ов.
- **`tests/`** — `test_gateway.py`, `test_cert_verifier.py`,
  `test_server_cert_check.py`.
- **`docs/reference/gateway.md`** — обзор API `model-gateway`.

### Changed

- **`docker-compose.yml`** — пять сетей (`gateway-net`,
  `gateway-internal-net`, `internal-net`, `proxy-net`,
  `external-net`). Появились сервисы `gateway-tls` и `model-gateway`.
- **`harness/agent_loop.py`** — `HarnessAgent` принимает `client=`
  (инъекция для тестов), в production строит mTLS-клиент через
  `_make_ollama_client`.
- **`harness/main.py`** — `load_config` читает `gateway_*` из env.
- **`scripts/bootstrap.sh`** — генерирует сертификаты и токены,
  заполняет `config/gateway_clients.yaml`, поднимает все пять
  сервисов.
- **`mkdocs.yml`** — `docs/reference/gateway.md` в навигации.
- **`docs/`** — добавлены разделы про mTLS, prompt_hash, criticality,
  self-tests, capabilities, strict-режим CI.
- **`README.md`** — обновлён под новую архитектуру.

## v0.11 — Switch to GitHub repository

### Changed

- **Инструкции по установке** переведены с `setup.sh` на `git clone`
  из <https://github.com/walking-in-the-woods/paranoid-harness>.
  `setup.sh` остаётся в репозитории как вспомогательный инструмент
  для генерации структуры без сети, но документация на него больше
  не опирается.
- `README.md`: добавлена ссылка на репозиторий и раздел «Быстрый
  старт» с `git clone`.
- `INSTALL-LINUX.md`: шаг 2 «Создание файлов проекта» заменён на
  «Клонирование репозитория». Разделы про `--verify-sha256` и
  sha256 `setup.sh` сохранены с пометкой «только для пути через
  setup.sh».
- `INSTALL-WINDOWS.md`: аналогичные изменения.

## v0.10 — Audit round 3 fixes

### Fixed

- **Smoke-тесты: thinking mode qwen3.** Добавлен параметр
  `think=False` в `test_sentinel_pong`, `test_json_mode_structured`,
  `test_who_are_you_ascii`. `harness/requirements.txt`:
  `ollama>=0.4.8`.
- **Формулировка про GPG fingerprint.** Исправлена в
  `install-machine.sh` и `docs/design-notes.md`.
- **`_TAG_RE`: fidelity для обычных HTML-тегов.** Добавлен `\b`
  после группы альтернатив; варианты `tool_*` перечислены явно.
- **`_tool_list_dir`: формат вывода.** Убран завершающий пробел.
- **Read-after-write: end-to-end тесты.** Добавлены
  `test_read_after_write_end_to_end` и
  `test_read_after_write_end_to_end_via_main_flow`.

### Added

- `_TAG_RE` расширен: помимо `system`/`assistant`/`user`/`tool`,
  экранируются `function_call`, `function_calls`, `function_results`,
  `tool_use`, `tool_uses`, `tool_call`, `tool_calls`, `tool_response`,
  `tool_responses`, `tool_output`, `tool_outputs`, `result`, `results`,
  `response`, `output`, `prompt`, `context`, `thought`.
- `_INVISIBLE` расширен: variation selectors, directional isolates,
  interlinear annotation, Mongolian vowel separator.
- `sync-model.sh`: переменная `ALPINE_IMAGE`.
- `bootstrap.sh`: `--verify-sha256=<hash>`.
- `config/logrotate.harness`.

### Changed

- `.env.example` и `docs/operations.md`: уточнение про
  `HARNESS_MODEL_DIGEST`.
- `docker-compose.yml`: комментарии про compose v2.
- `harness/agent_loop.py`: комментарий про микро-TOCTOU.
- `docs/design-notes.md`: раздел про `chmod 0o644`.

## v0.9 — Audit round 2 fixes

### Security

- Digest модели: парсинг через `ollama list --json`.
- Fingerprint Docker GPG: сравнение через `tr -s ' '`.
- `whitelist: []` = «ничего не разрешено».

### Added

- Проверка `docker compose plugin` в `install-machine.sh`.
- `mktemp` для временных файлов.
- `--no-readme` для `uv init`.
- Тесты `test_empty_whitelist_denies_all`,
  `test_missing_whitelist_key_uses_default`.

### Changed

- `fsync` в `audit.jsonl` только для критичных событий.
- `_tool_list_dir` использует уже разрешённый `p` для `source=`.
- Версия uv нормализуется через regex.

## v0.8 — Security fixes after audit

- Read-after-write: канонические пути (`canonical_rel`).
- Digest-верификация модели (`HARNESS_MODEL_DIGEST`).
- `.venv/` в `.gitignore`.
- `fsync` в audit.
- Fingerprint Docker GPG в `install-machine.sh`.
- Расширенный grep в `bootstrap.sh`.
- `ollama-updater` с `read_only: true`.
- `_wrap_tool_result(attrs: dict)`.
- `source=` во всех tool-результатах канонический.

## v0.7 — Idempotent installs, newer models, DRY

- `install-machine.sh` идемпотентен.
- Модели: `qwen2.5` → `qwen3`.
- Тестовые модели в `.env`.
- `_wrap_tool_result` — единая сборка конверта.
- `bootstrap.sh` делегирует модель в `sync-model.sh`.
- `docs/` + `mkdocs.yml`.

## v0.6 — Truncation metadata as attributes

- Метка усечения в атрибутах `<tool_result>`.

## v0.5 — Polish

- `lstrip` → `removeprefix`.
- `_redact_args` скрывает `params`.
- `itertools.islice` в `_tool_list_dir`.

## v0.4 — Real APIs & Polish

- Реальные публичные API в `ROUTES`.
- `tests/test_proxy.py`.

## v0.3 — Tests & CI

- Юнит-тесты + smoke. GitHub Actions matrix. `AuditLog`.

## v0.2 — Hardening

- `FileSystemGuard`, `InjectionGuard`, `ConfirmSession`.
- `sync-model.sh` + sha256-манифест.

## v0.1 — Initial

- Изоляция сетей, tool calling, container hardening.
