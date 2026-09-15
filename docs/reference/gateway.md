# model-gateway

Тонкий mTLS-гейтвей к Ollama. Исходники:

- `model_gateway/gateway.py` — FastAPI-приложение: конфиг,
  аутентификация, эндпоинты, аудит.
- `model_gateway/cert_verify.py` — верификация клиентских
  сертификатов и проверка `server.crt`.

Страница рукописная: `mkdocstrings` не используется. Причина —
`gateway.py` на уровне модуля вызывает `load_config(CONFIG_PATH)`,
что требует env-переменных и валидного конфига. Импорт модуля вне
запущенного контейнера падает с `ConfigError`. Это осознанный
fail-fast (см. `docs/design-notes.md`, раздел «Валидация
конфигурации при импорте»); для просмотра API используйте исходники.

---

## Конфигурация

### `load_config(path: str) -> GatewayConfig`

Загружает YAML-конфиг (`config/gateway_clients.yaml`), валидирует
все поля и читает обязательные env-переменные.

**Обязательные env-переменные:**

| Переменная | Назначение |
|---|---|
| `GATEWAY_CONFIG` | Путь к YAML-конфигу клиентов. По умолчанию `/config/gateway_clients.yaml`. |
| `GATEWAY_HMAC_KEY` | HMAC-ключ для `prompt_hash` (≥32 символа). |
| `GATEWAY_CA_CERT` | Путь к PEM-сертификату CA для верификации клиентов. |

**Опциональные env-переменные:**

| Переменная | Назначение | Дефолт |
|---|---|---|
| `GATEWAY_AUDIT_PATH` | Путь к `gateway.jsonl` | `/logs/gateway.jsonl` |
| `GATEWAY_SERVER_CERT` | Путь к `server.crt` (проверяется при старте) | `/certs/server.crt` |
| `GATEWAY_SERVER_SAN` | Обязательный SAN DNS server-сертификата | `gateway-tls` |
| `GATEWAY_SERVER_EXTRA_SANS` | Допустимые дополнительные DNS-SAN | `localhost` |
| `GATEWAY_SERVER_IPS` | Допустимые IP-SAN | `127.0.0.1` |
| `GATEWAY_REQUIRE_SERVER_CERT` | `1`/`0`, обязателен ли `server.crt` | `1` |

При невалидном конфиге — `ConfigError` с указанием поля. При
отсутствии файла — `ConfigError("GATEWAY_CONFIG file not found: ...")`.

### `GatewayConfig`

Frozen dataclass. Ключевые поля:

- `upstream_base_url` — URL Ollama (`http://ollama-runner:11434`).
- `model_allowlist` — `frozenset[str]` разрешённых моделей.
- `clients` — `tuple[ClientProfile, ...]`.
- `server_cert` — `ServerCertPolicy`.
- `prompt_hash_hmac_key` — bytes.
- `audit_path`, `ca_cert_path` — `Path`.

### `ClientProfile`

Один профиль клиента: `name`, `token_sha256`, `tools_enabled`,
`allowed_tools`, `forced_system_prompt`, `requests_per_minute`,
`max_concurrent`, `allow_stream`, `audit_label`.

### `ServerCertPolicy`

Параметры проверки `server.crt`: `cert_path`, `required`,
`required_san`, `allowed_extra_sans`, `allowed_ips`.

### `ClientState`, `PerIpRateLimiter`, `AuditWriter`

- `ClientState` — per-client семафор и sliding-window rate limit.
- `PerIpRateLimiter` — глобальный rate limiter по IP для
  auth-fail-попыток (`MAX_BUCKETS=512`, LRU-вытеснение).
- `AuditWriter` — JSONL-аудит с `fsync` для критичных событий.

---

## Верификация сертификатов

### `CertVerifier`

Полная проверка клиентского сертификата:

1. Подпись CA над `tbs_certificate_bytes` (RSA или ECDSA).
2. Срок действия (обе границы).
3. `BasicConstraints: critical, CA:FALSE`.
4. `KeyUsage: critical, digitalSignature`; без `keyCertSign`,
   без `crlSign`.
5. `ExtendedKeyUsage: critical, clientAuth`.
6. `SignatureAlgorithm` — SHA-256/384/512.
7. `SAN: critical`, ровно один DNS = имя клиента.

Возвращает строку SAN клиента или `None` (любая проверка не прошла).
При старте проверяется срок CA.

### `check_server_cert(cert_path, ...)`

Проверка `server.crt` при старте. Симметричная политика:
BC/KU/EKU/SAN critical, EKU=serverAuth, SAN содержит `gateway-tls`.
Symlink (dangling или на не-файл) — отказ при `required=True`.

---

## Аутентификация

Заголовки от `gateway-tls` (nginx):

- `X-Client-Cert` — URL-encoded PEM клиентского сертификата.
- `X-Client-Verify` — статус верификации в nginx. **Обязателен**:
  гейтвей проверяет `== "SUCCESS"` до верификации подписи
  сертификата (defense-in-depth). Заголовок выставляет только nginx;
  при прямом подключении к `model-gateway` в обход nginx он
  отсутствует, и запрос отвергается с 403 `mtls_not_verified`.
- `X-Real-IP` — IP клиента (`$remote_addr`).

Заголовок от клиента:

- `X-Gateway-Token` или `Authorization: Bearer <token>`.

Порядок: rate-limit по IP → проверка `X-Client-Verify == "SUCCESS"`
→ верификация сертификата → поиск профиля по SAN → сравнение SHA256
токена (`secrets.compare_digest`).

---

## Эндпоинты

| Endpoint | Метод | Аутентификация | Назначение |
|---|---|---|---|
| `/health` | GET | нет | Liveness. |
| `/ready` | GET | да | Readiness: upstream доступен. |
| `/api/tags` | GET | да | Список моделей, отфильтрованный `model_allowlist`. |
| `/api/show` | POST | да | Информация о модели. |
| `/api/chat` | POST | да | Чат. |
| `/api/generate` | POST | да | Генерация. |

Профиль применяется одинаково к `/api/chat` и `/api/generate`.
Различие: `/api/chat` использует `messages` и `_apply_profile_chat`,
`/api/generate` — `prompt`/`system` и `_apply_profile_generate`.
Поле `messages` в `/api/generate` не появляется.

---

## Профиль клиента

Что гейтвей применяет на каждый запрос:

- **Модель** — только из `model_allowlist`; иначе 400.
- **Tools**:
  - `tools_enabled: false` → вырезаются `tools`, `functions`,
    `tool_choice`, `tool_calls`, `function_call`, `tool_call_id`,
    `name`.
  - `allowed_tools: [...]` → оставляются только перечисленные;
    tool_calls в истории фильтруются.
- **System prompt**: если `forced_system_prompt` задан, заменяет
  все `system`-сообщения.
- **Options**: `num_predict` clamp до `[1, max_num_predict]`,
  `num_ctx` clamp до `[512, max_num_ctx]`, `keep_alive` — по типам,
  cap `30m`.
- **Stream**: разрешён только при `allow_stream: true`.

---

## Аудит

`logs/gateway.jsonl`. События: `gateway_start`, `gateway_stop`,
`request`, `response`, `auth_fail`, `rate_limited`, `request_rejected`,
`upstream_error`, `tags`, `show`.

`prompt_hash` — HMAC-SHA256 с length-prefix от `(role, content)`
всех сообщений (или `(system, prompt)` для `/api/generate`).
Содержимое промптов не логируется; ключ — `GATEWAY_HMAC_KEY`.

`fsync` — только для критичных событий (`gateway_start`,
`gateway_stop`, `request_rejected`, `rate_limited`, `upstream_error`).

Ротация — через `config/logrotate.harness` (второй блок для
`gateway.jsonl`).
