# Local AI Harness

Изолированный локальный агент на Ollama с mTLS-гейтвеем,
multi-client и защитой supply chain. Модель без интернета, файлы —
только в `workspace/`, запись — с подтверждением одноразовым кодом.

**Репозиторий:** <https://github.com/walking-in-the-woods/paranoid-harness>

## Что внутри

- **`harness`** — REPL и агент: tool calling через Ollama, чтение
  файлов, `propose_write` с подтверждением, `api_call` через
  локальный прокси.
- **`model-gateway`** — единая точка входа к модели. mTLS
  (клиентский сертификат + токен), профили клиентов, rate limiting,
  аудит. Позволяет подключать параллельно несколько клиентов (WebUI,
  инструментальные интеграции и т.п.) с разными правами.
- **`gateway-tls`** — nginx с mTLS-терминацией. Обязательный
  клиентский сертификат; пробрасывает его в `model-gateway` для
  криптографической верификации.
- **`ollama-runner`** — сервер Ollama без доступа в интернет.
- **`api-proxy`** — единственный постоянно работающий контейнер с
  выходом в интернет. Named routes с фиксированными хостами.
- **`ollama-updater`** — загрузка моделей. `read_only`,
  изолированный, запускается по профилю `updater`.

Пять Docker-сетей с явным разделением trust boundary:
`gateway-net`, `gateway-internal-net`, `internal-net`, `proxy-net`,
`external-net`.

## Быстрый старт

```bash
git clone https://github.com/walking-in-the-woods/paranoid-harness.git
cd paranoid-harness
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

Bootstrap сгенерирует сертификаты и токены, соберёт образы, скачает
модель и поднимет все сервисы. Дальше:

```bash
sudo docker compose exec harness python -m harness.main
```

Подробно — по инструкции для вашей ОС:

- [Linux](INSTALL-LINUX.md)
- [Windows / WSL2](INSTALL-WINDOWS.md)

## Документация

- [Обзор](docs/index.md)
- [Установка](docs/install.md)
- [Архитектура](docs/architecture.md)
- [Модель угроз](docs/security-model.md)
- [Шпаргалка](docs/cheatsheet.md)
- [Рецепты](docs/cookbook.md)
- [Диагностика](docs/troubleshooting.md)
- [Operations](docs/operations.md)

## Разработка

```bash
./scripts/verify-project.sh
```

10 секций: гигиена `ci.yml` (отсутствие запрещённых имён файлов),
инвариант «CI использует runner» (нет прямых вызовов `self-test-*.sh`),
диагностика `self-test-filename-pattern.sh`, spot-check символов
`gateway.py`, symlink-тесты через pytest, `import re` на уровне модуля,
все self-tests, chmod, unit-тесты.

Не покрывает CI-шаги:

- **`docker-smoke`** — требует Docker.
- **`Check image pinning`** — сам чекер `check-image-pinning.py`
  покрыт self-тестом (`self-test-image-pinning.sh` на синтетических
  файлах), но его применение к **реальным** Dockerfiles проекта
  локально не запускается — этот шаг выполняется только в CI.
- **`Verify cert generation`** — вызывает `scripts/gateway-certs.sh`,
  локально не покрыт.

## Сборка документации локально

```bash
pip install mkdocs-material "mkdocstrings[python]"
mkdocs serve
# http://127.0.0.1:8000
```

## Альтернативный путь: `setup.sh`

Если вы получили `setup.sh` отдельно (без доступа к репозиторию),
он создаёт дерево проекта и все файлы. Публикуется как
самостоятельный артефакт; хеш для проверки целостности — в разделе
«Прочитайте до старта» соответствующей инструкции.

## История

См. [CHANGELOG.md](CHANGELOG.md).
