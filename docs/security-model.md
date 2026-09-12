# Модель угроз

## Активы

- **Домашняя директория хоста.** Не должна быть доступна модели.
- **Секреты хоста** (`.ssh`, `.aws`, `.env`, токены). Не должны
  утекать через чтение или запись.
- **Целостность `workspace/`.** Записи вне разрешённых путей быть не
  должно; существующие файлы не должны меняться без подтверждения.
- **Целостность весов модели.** Подмена снапшота Ollama должна быть
  обнаружена.
- **Устойчивость хоста.** Модель не должна уронить систему.

## Акторы

- **Пользователь.** Доверенный, но не всеведущий: может не заметить
  подозрительный diff.
- **Модель.** Не доверяем. Может быть подсказана инъекцией или сама
  ошибиться.
- **Содержимое `workspace/`.** Не доверяем. Файл может содержать
  инструкции, адресованные модели.
- **Внешние API.** Не доверяем. Ответ может содержать инъекцию.
- **Цепочка поставки.** PyPI, Docker Hub, GitHub — не доверяем.

## Защита

### Сеть

| Угроза | Защита |
|---|---|
| Модель обращается в интернет | `internal: true`; в `internal-net` нет маршрута наружу |
| Данные утекают через `api_call` | Прокси знает только фиксированные маршруты; хост нельзя подставить |
| SSRF через редирект | `follow_redirects=False` |
| Обход маршрута через `@` в URL | Хост берётся из `ROUTES`, не из запроса |
| Доступ к прокси из чужого контейнера | `X-Proxy-Secret` |
| DoS через большой ответ | `MAX_REQ_BODY`, `MAX_RESP_BODY` |

### Файловая система

| Угроза | Защита |
|---|---|
| `../../../etc/passwd` | Запрет `..` в пути + `realpath` + проверка префикса |
| Symlink на `/etc` | `os.path.realpath` разворачивает всю цепочку |
| Гомоглифы (`а` кириллическая vs `a` латинская) | NFKC-нормализация до сравнения |
| Null-byte в пути | Явная проверка `\x00` |
| Запись скрипта `.sh` | `WRITE_EXT_BLOCK`; скрипты сохраняются как `.txt` |
| Запись `.bashrc` / `Makefile` / `package.json` | Чёрный список persistence и CI-файлов |
| Файл с опасной полезной нагрузкой под `.txt` | `scan_payload` по регуляркам `curl|sh`, `chmod +x`, fork bomb, `eval(`, `subprocess.` |
| DoS через каталог с миллионами файлов | `islice` + `MAX_LIST_ENTRIES` |
| DoS через огромный файл | `MAX_READ_BYTES` (200 КБ) |
| DoS через гигантский `propose_write` | `MAX_WRITE_BYTES` (1 МБ) |

### Контекст и инъекции

| Угроза | Защита |
|---|---|
| «Ignore previous instructions» в файле | `<tool_result trust="untrusted">` + правило в system prompt |
| XML-теги ролей в данных | `neutralize_data_block` экранирует расширенный набор тегов: system/assistant/user/tool/tool_result/tool_use/tool_uses/tool_call/tool_calls/tool_response/tool_responses/tool_output/tool_outputs/instruction/function_call/function_calls/function_result/function_results/result/results/response/output/prompt/context/thought. Обычные HTML-теги на ролевые префиксы (`<toolbar>`, `<toolbox>`, `<systemd>`) не экранируются благодаря `\b` в `_TAG_RE`. |
| Тройные бэктики в данных | Заменяются на `'''` |
| Служебная метка «truncated» в теле | Метаданные — в атрибутах тега, не в теле |
| Самоинъекция через свой же записанный файл | `_written_paths` с каноническими путями, read-after-write block |
| Инъекция через имя файла в `source=` | `_escape_attr` |
| Обфускация через невидимые символы | Удаление zero-width, bidi, variation selectors, interlinear annotation, Mongolian vowel separator |
| Гомоглифы в тексте инъекции | Транслитерация кириллица/греческий/fullwidth → ASCII |
| Обфускация в `scan_payload` через гомоглиф | Тот же `normalize` применяется к содержимому |

### Запись

| Угроза | Защита |
|---|---|
| Программный вызов `confirm(True)` | `ConfirmSession.apply()` требует nonce, `secrets.compare_digest` |
| TOCTOU между показом и записью | Повторный `check_write` **после** подтверждения |
| Полузаписанный файл при сбое | `mkstemp` + `os.replace` (атомарно) |
| Смена umask и неожиданные права | Явный `os.chmod(0o644)` |

### Цепочка поставки

| Угроза | Защита |
|---|---|
| Подмена `uv` installer | Версия зафиксирована, SHA256 из того же GitHub release |
| MITM на apt-репозитории Docker | Fingerprint GPG сверяется с официальным |
| Подмена PyPI-пакета | `uv.lock` с хешами + `uv sync --locked` + cooldown 7 дней |
| Свежий вредоносный релиз | `exclude-newer = "7 days"` в `pyproject.toml` |
| Подмена тега Docker-образа | Опциональный digest-пиннинг |
| Подмена весов модели | Снапшот + sha256-манифест при промоушене |
| Подмена тега модели | `HARNESS_MODEL_DIGEST` (опционально) |
| Мутабельный `alpine:3.19` в sync-model | `ALPINE_IMAGE` override + предупреждение |
| Членство в `docker` как root | Не добавляемся; команды через `sudo docker` |

## Что осознанно не защищено

- **Отложенное исполнение.** Файл `.txt` с `sleep 3600 && rm -rf` не
  блокируется: он не `.sh`.
- **Пользователь, читающий diff невнимательно.** Если вы ввели nonce,
  не посмотрев diff — файл записан.
- **Компрометация Docker daemon.** Если атакующий уже root на хосте —
  харнесс не даёт дополнительной защиты.
- **ML-классификатор инъекций.** Сознательно не включён.
- **TOCTOU в `_tool_list_dir`.** Для single-user локальной системы
  не критично.

## Что сделать при чувствительных данных

1. **Включить digest-пиннинг базовых образов** (раздел A в
   инструкции).
2. **Задать `HARNESS_MODEL_DIGEST`** в `.env`.
3. **Включить `read_only: true` на `ollama-runner`** (см. ниже).
4. **Запустить Docker в rootless-режиме** или с userns-remap.
5. **Разместить `workspace/` на отдельном разделе/диске.**
6. **Регулярно проверять `logs/audit.jsonl`** на неожиданные
   `propose_write`.

### Дополнительно: `read_only` на `ollama-runner`

По умолчанию контейнер writable: Ollama может писать в `/root/.cache`,
`/root/.config` и подобные пути вне тома моделей. Чтобы включить
hardening:

```yaml
ollama-runner:
  read_only: true
  tmpfs:
    - /tmp:size=1g
    - /root/.cache:size=512m
    - /root/.config:size=64m
```

После правки — `docker compose up -d --force-recreate ollama-runner`
и проверка, что модель отвечает:

```bash
docker compose exec ollama-runner ollama list
```

Если Ollama пишет в неожиданное место — она вернёт ошибку, и
можно добавить соответствующий tmpfs. Тестируйте перед включением
в production.
