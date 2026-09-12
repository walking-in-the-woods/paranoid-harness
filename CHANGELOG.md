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

## v0.10 — Audit round 3 fixes

### Fixed
- **Формулировка про GPG fingerprint.** Предыдущее объяснение было
  инвертировано: GnuPG `--with-fingerprint` печатает fingerprint
  именно с декоративным двойным пробелом между 4-й и 5-й группами,
  а не наоборот. Сравнение через `tr -s ' '` нормализует оба
  варианта — код работал, объяснение было неверным. Исправлено в
  этом changelog, в комментарии `install-machine.sh` и в
  `docs/design-notes.md`.
- **`_TAG_RE`: fidelity для обычных HTML-тегов.** Добавлен `\b` после
  группы альтернатив — `<toolbar>`, `<toolbox>`, `<systemd>`, `<tools>`
  больше не экранируются как ролевые теги. Поскольку `_` — word-символ,
  `tool\b` не матчит `tool_call`: все `tool_*`-варианты (`tool_call`,
  `tool_calls`, `tool_response`, `tool_responses`, `tool_output`,
  `tool_outputs`, `tool_use`, `tool_uses`, `tool_result`, `tool_results`)
  перечислены явно. Сознательный over-reach сохранён для `<user-agent>`
  и `<response-time>` — эти теги по-прежнему матчатся, но это
  безопаснее under-aggressive. Тесты:
  `test_neutralize_does_not_overreach_html_tags` и
  `test_neutralize_still_covers_tool_call_variants`.
- **`_tool_list_dir`: формат вывода.** Литерал `'DIR '` с завершающим
  пробелом давал два пробела для директорий (`DIR  docs`) и один для
  файлов (`FILE readme.md`). Асимметрия ломала точное сравнение в
  тестах и снижала читаемость tool_result для модели. Убран
  завершающий пробел. Тесты, зависевшие от старого формата,
  актуализированы: `test_list_dir_basic` разделён на два листинга
  (`list_dir` нерекурсивный), `test_read_file_written_in_session_blocked`
  теперь создаёт файл перед `mark_written` (в реальном потоке файл
  гарантированно создан после `[OK]` от `ConfirmSession.apply`).
- **Read-after-write: end-to-end тест.** Предыдущие тесты проверяли
  канонизацию в изоляции (вручную вызывали `mark_written(canonical)`).
  Добавлены `test_read_after_write_end_to_end` и
  `test_read_after_write_end_to_end_via_main_flow`, которые
  проходят полный поток `propose_write → mark_written(canonical) →
  read_file`.

### Added
- `_TAG_RE` расширен: помимо ролевых тегов OpenAI-стиля
  (`system`/`assistant`/`user`/`tool`), экранируются также
  `function_call`, `function_calls`, `function_results`, `tool_use`,
  `tool_uses`, `tool_call`, `tool_calls`, `tool_response`,
  `tool_responses`, `tool_output`, `tool_outputs`, `result`,
  `results`, `response`, `output`, `prompt`, `context`, `thought` —
  маркеры, используемые разными линейками моделей.
- `_INVISIBLE` расширен: `U+FE00–FE0F` (variation selectors),
  `U+E0100–E01EF` (variation selectors supplement),
  `U+2066–2069` (directional isolates, входят в `U+2060–206F`),
  `U+FFF9–FFFB` (interlinear annotation), `U+180E` (Mongolian vowel
  separator).
- `sync-model.sh`: переменная `ALPINE_IMAGE` с дефолтом `alpine:3.19`.
  Для production рекомендуется `ALPINE_IMAGE=alpine@sha256:<digest>`.
  **Компромисс usability vs security:** дефолт остаётся мутабельным
  (тег `alpine:3.19`), потому что жёсткий digest требует ручного
  обновления при каждом релизе Alpine. При использовании тега
  скрипт печатает предупреждение в stderr с инструкцией по
  получению digest. Это не «закрытие» проблемы, а сознательный
  выбор в пользу удобства с явным сигналом пользователю.
- `sync-model.sh`: проверка наличия `python3` при заданном
  `HARNESS_MODEL_DIGEST` (для парсинга JSON).
- `install-machine.sh`: проверка GPG fingerprint существующего
  keyring выполняется независимо от того, ставим ли мы Docker;
  добавлена проверка `command -v gpg`.
- `bootstrap.sh`: опциональный флаг `--verify-sha256=<hash>` —
  падает при несовпадении хеша `setup.sh`. Формат: 64 hex-символа в
  нижнем регистре, без префикса `sha256:`.
- `config/logrotate.harness` — конфиг logrotate для
  `logs/audit.jsonl`.

### Changed
- `.env.example` и `docs/operations.md`: явное указание, что
  `HARNESS_MODEL_DIGEST` защищает только от последующей подмены
  тега, но не от компрометации реестра при первом pull.
- `docs/operations.md`: раздел «Известные ограничения audit-лога».
- `docs/security-model.md`: раздел «Что сделать при чувствительных
  данных» переупорядочен; добавлен пункт про `read_only: true` на
  `ollama-runner` с инструкцией по проверке.
- `docker-compose.yml`: комментарий про `mem_limit`/`cpus` (compose
  v2, не v3) и про отсутствие `read_only` у `ollama-runner`.
- `harness/agent_loop.py`: комментарий про микро-TOCTOU в
  `_tool_list_dir` (single-user — не критично).
- `docs/design-notes.md`: раздел про `chmod 0o644` — почему жёстко,
  и почему не параметризовано.

## v0.9 — Audit round 2 fixes

### Security
- **Digest модели: парсинг исправлен.** `ollama show --modelfile | grep
  sha256: | head -n1` давал не тот sha256. Теперь digest берётся из
  `ollama list --json` (поле `digest`).
- **Fingerprint Docker GPG.** Сравнение через `tr -s ' '`.
- **`whitelist: []` — семантика.** Пустой список = «ничего не
  разрешено», не «разрешить всё».

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
