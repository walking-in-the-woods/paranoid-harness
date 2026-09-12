# Установка Local AI Harness на Linux

От нуля до работающего харнесса. Четыре шага, три скрипта, никаких
ручных правок конфигов.

**Вне этого документа** — текст `setup.sh`, создающий файлы проекта.
Публикуется отдельно; здесь описано, куда его положить и что с ним
делать.

---

## Требования

- Ubuntu 22.04 / 24.04 LTS или Debian-совместимая система
- Права `sudo`
- ~10 ГБ свободного места на диске
- 5 минут на первый запуск (плюс время на скачивание модели)

Опционально:

- NVIDIA Container Toolkit — если планируете использовать GPU
- Python 3.12 на хосте — если планируете запускать юнит-тесты без
  контейнера (в обычном сценарии не нужно)

---

## Что получится

После установки:

- Модель Ollama работает **без доступа к интернету** (Docker-сеть
  `internal: true`).
- Файловые операции — только в пределах `./workspace` с белым/чёрным
  списками.
- Одна запись на сессию, с подтверждением одноразовым кодом.
- Единственный сетевой канал модели — `api_call` через локальный
  прокси с whitelist'ом.
- Audit-лог в `./logs/audit.jsonl`.
- Цепочка поставки: `uv` — версия + SHA256, Python — `uv.lock` +
  cooldown, базовые образы — опционально digest, модели —
  sha256-манифест (и опционально digest-проверка).

---

## Прочитайте до старта

1. **Для машины с корпоративными секретами** включите digest-пиннинг
   базовых образов (раздел A) **до первого запуска**. Для локального
   эксперимента можно пропустить.

2. **Сверьте хеш `setup.sh`** перед запуском. Ожидаемый хеш этой
   версии публикуется рядом со скриптом. Если не совпал — не
   запускайте.

3. **Не удаляйте `[tool.uv] exclude-newer`** из `pyproject.toml`.
   Это cooldown 7 дней — защита от свежих вредоносных релизов PyPI.

4. **Не добавляйтесь в группу `docker`.** Все команды идут через
   `sudo docker`. Членство в группе эквивалентно root-доступу на
   хосте.

5. **Опционально: автоматическая сверка sha256 `setup.sh`.**
   Запустите `./bootstrap.sh --verify-sha256=<хеш>` — при
   несовпадении скрипт упадёт. Это надёжнее, чем ручная сверка.

---

## Шаг 1. Подготовка машины (один раз)

Сохраните `install-machine.sh` на машине, сделайте исполняемым,
запустите.

```bash
chmod +x install-machine.sh
./install-machine.sh
source ~/.bashrc
```

**Что делает скрипт:**

- Проверяет, установлен ли Docker (`command -v docker`), и его версию.
  Если версия ≥ 24 — установка пропускается.
- Проверяет наличие `docker compose plugin`. Если нет — устанавливает
  вместе с Docker.
- Проверяет GPG-ключ Docker в `/etc/apt/keyrings/docker.gpg`, если он
  уже есть — сверяет fingerprint с официальным (warn + ask).
- Устанавливает Docker из официального репозитория: скачивает
  GPG-ключ, **сверяет fingerprint** с официальным
  (`9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88`), только потом
  добавляет apt-репозиторий. Fail-closed при установке.
- Проверяет наличие и версию `uv`. **Не откатывает более новые
  версии** — сравнение через `sort -V`.
- Устанавливает `uv` с пиннингом версии (`0.12.12`) и **проверкой
  SHA256** для скачанного tarball. Tarball и `.sha256` берутся из
  того же GitHub release.
- Временные файлы создаются через `mktemp` — защита от symlink-атаки
  в `/tmp` на многопользовательских машинах.

**Скрипт идемпотентен.** Повторный запуск не сломает установку.

---

## Шаг 2. Создание файлов проекта

Возьмите `setup.sh` из отдельного документа. **Сверьте хеш**:

```bash
sha256sum setup.sh
# Сравните вывод с ожидаемым хешем из документации к релизу.
# Только если совпал:
./setup.sh
cd harness-project
```

`setup.sh` создаёт дерево и все файлы проекта. **Сетевых вызовов не
делает** — только пишет на диск.

**Что создаётся:** см. заголовок `setup.sh` — там полное дерево с
описанием каждого файла.

**Проверка перед запуском** (если получили скрипт не от себя):

```bash
bash -n setup.sh                                              # синтаксис
grep -nE '(curl|wget|nc |/dev/tcp|eval|base64 -d)' setup.sh   # потенциально опасное
```

Если `grep` ничего не нашёл — скрипт чист.

---

## Шаг 3. Bootstrap проекта

Скопируйте `scripts/bootstrap.sh` внутрь `harness-project/` (или
запускайте из родительской директории — скрипт сам находит `.env`).
Запустите:

```bash
cd harness-project
cp scripts/bootstrap.sh .
chmod +x bootstrap.sh
./bootstrap.sh
```

**Что делает bootstrap за один запуск:**

1. Проверяет `../setup.sh` (если найден): `bash -n` + grep по
   опасным конструкциям (`curl`, `wget`, `nc`, `/dev/tcp`, `eval`,
   `base64 -d`, `rm -rf`, `dd if=`, `mkfs`). Опционально — sha256-сверка
   через `--verify-sha256=<hash>`.
2. Создаёт `.env`: генерирует `PROXY_SECRET`, подставляет реальные
   `UID`/`GID`.
3. Единоразово переходит на `uv.lock` с **cooldown 7 дней**
   (`exclude-newer`). Это защита от свежих вредоносных релизов PyPI.
4. Прогоняет юнит-тесты (без модели).
5. Собирает Docker-образы.
6. Скачивает модель через изолированный `ollama-updater`, снимает
   снапшот, считает SHA256, промоутит в volume раннера.
   Опционально сверяет digest, если задан `HARNESS_MODEL_DIGEST`.
7. Поднимает `ollama-runner`, `api-proxy`, `harness`.

**Если что-то падает** — проверьте `logs/audit.jsonl` и
`sudo docker compose logs`. См. `docs/troubleshooting.md`.

---

## Шаг 4. Работа

```bash
sudo docker compose exec harness python -m harness.main
```

Внутри REPL:

- `/quit` — выход
- `/reset` — новая сессия (обнуляет лимит записей и read-after-write
  block)

Пример:

```
>>> прочитай input/report.md и напиши краткое резюме в output/summary.md
```

При предложении записи харнесс покажет diff и одноразовый
6-символьный код. Файл создаётся только при точном вводе кода.

**Куда класть файлы:** `harness-project/workspace/input/` — ваши
исходники; результат — в `harness-project/workspace/output/`. См.
`docs/usage.md`.

---

## Проверка после установки

```bash
# 1. Изоляция: из контейнера harness нет выхода наружу
sudo docker compose exec harness python -c \
  "import socket; socket.create_connection(('1.1.1.1',53),timeout=2)"
# Ожидается: Network is unreachable / Name or service not known

# 2. Модель загружена
sudo docker compose exec ollama-runner ollama list

# 3. Юнит-тесты (без модели)
pytest tests/ --ignore=tests/smoke -v

# 4. Smoke с моделью (опционально, требует загруженной модели)
OLLAMA_HOST=http://127.0.0.1:11434 \
SMOKE_MODEL=qwen3:1.7b \
SMOKE_TOOL_CAPABLE=true \
  pytest tests/smoke -m smoke -v -s
```

---

## Раздел A. Digest-пиннинг образов (для машин с секретами)

Теги мутабельны: если upstream перезапишет образ под тем же тегом,
вы получите другой код. Digest фиксирует точное содержимое.

```bash
# Получить digest текущих образов:
docker pull ollama/ollama:latest
docker inspect --format='{{index .RepoDigests 0}}' ollama/ollama:latest

docker pull python:3.12-slim
docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim

docker pull alpine:3.19
docker inspect --format='{{index .RepoDigests 0}}' alpine:3.19
```

**Что заменить:**

- `docker-compose.yml` — оба вхождения `ollama/ollama:latest` (в
  `ollama-runner` и `ollama-updater`) → `ollama/ollama@sha256:<digest>`.
- `harness/Dockerfile` и `api_proxy/Dockerfile` — `FROM python:3.12-slim`
  → `FROM python:3.12-slim@sha256:<digest>`.
- Для `sync-model.sh` — задайте `ALPINE_IMAGE=alpine@sha256:<digest>`
  в окружении при запуске (или в `.env`). Контейнер получает rw на
  `ollama-models-verified`, поэтому его пиннинг особенно важен.

Обновлять при выходе новой версии — вручную: `docker pull`,
`docker inspect`, заменить digest.

---

## Раздел B. Digest-пиннинг модели

Если задан `HARNESS_MODEL_DIGEST` в `.env`, `sync-model.sh`
проверит digest скачанной модели до промоушена.

**Как получить digest:**

```bash
docker exec ollama-updater ollama list --json | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
    m=[x for x in (d.get('models') or d) if x.get('name')=='qwen3:8b'][0]; \
    print(m['digest'])"
```

Значение `sha256:<hex>` в поле `digest` — то, что нужно записать
в `HARNESS_MODEL_DIGEST` (можно с префиксом `sha256:` или без).

**Что происходит при несовпадении:** скрипт печатает ожидаемый и
полученный digest и завершается с кодом 1 до промоушена в
runner-volume. Модель не попадает в раннер.

**Ограничение:** digest-верификация защищает от **последующей**
подмены тега. При первом pull компрометация реестра Ollama приведёт
к совпадению digest на вредоносной версии. См. `docs/operations.md`,
раздел «Ограничения digest-верификации».

---

## Раздел C. Rootless Docker (опционально)

Альтернатива `sudo docker` — демон и контейнеры без root в user
namespace.

```bash
sudo apt install -y uidmap dbus-user-session
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER"
dockerd-rootless-setuptool.sh install
systemctl --user start docker
systemctl --user enable docker
sudo loginctl enable-linger "$USER"
docker context use rootless
```

**Ограничения:** GPU-поддержка в rootless сложнее (нужен проброс
`--device` и настройка subordinate UID). Для сценариев с GPU проще
остаться на rootful + `sudo docker`.

---

## Раздел D. Userns-remap (опционально)

Если rootless не подходит, но хочется снизить blast radius:

```json
// /etc/docker/daemon.json
{ "userns-remap": "default" }
```

Затем `sudo systemctl restart docker`. UID контейнера мапится в
непривилегированный диапазон на хосте.

---

## Раздел E. `read_only` на `ollama-runner` (paranoid)

По умолчанию `ollama-runner` writable: Ollama может писать в
`/root/.cache`, `/root/.config` и подобные пути вне тома моделей.
Чтобы включить hardening:

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
sudo docker compose exec ollama-runner ollama list
```

Если Ollama пишет в неожиданное место — она вернёт ошибку, и
можно добавить соответствующий tmpfs. Тестируйте перед включением
в production.

---

## Раздел F. Logrotate для `audit.jsonl`

Готовый шаблон лежит в `config/logrotate.harness`. Установка:

```bash
cd harness-project
sed "s|@PROJECT_PATH@|$(pwd)|; s|@UID@|$(id -u)|; s|@GID@|$(id -g)|" \
  config/logrotate.harness | sudo tee /etc/logrotate.d/harness

# Проверка конфига:
sudo logrotate -d /etc/logrotate.d/harness
```

См. `docs/operations.md`, раздел «Ротация audit.jsonl».

---

## Проверка целостности setup.sh

`bootstrap.sh` **не сверяет** sha256 `setup.sh` автоматически по
умолчанию. Сверка хеша — ваша ответственность:

```bash
sha256sum setup.sh
# сравните вручную с ожидаемым хешем из документации к релизу
```

**Где взять ожидаемый хеш:**

- Публикуется вместе с `setup.sh` в разделе релиза.
- Если публикация не содержит хеша — запросите у распространителя
  или зафиксируйте сами после первой проверки.

**Опциональная автоматическая проверка:**

```bash
./bootstrap.sh --verify-sha256=<ожидаемый-хеш>
```

**Формат хеша:** 64 hex-символа в нижнем регистре, без префикса
`sha256:`. При несовпадении скрипт падает до продолжения.

---

## Диагностика

| Симптом | Решение |
|---|---|
| `command not found: uv` | `source ~/.bashrc` или откройте новый терминал |
| `Cannot connect to the Docker daemon` | `sudo systemctl status docker` |
| `docker compose` не найден | Установите `docker-compose-plugin` (шаг 1) |
| `Permission denied` при записи в `workspace/` | Проверьте, что `UID`/`GID` в `.env` = `id -u` / `id -g` |
| `model not found` | `./scripts/sync-model.sh qwen3:8b` |
| `502 upstream error` при `api_call` | Публичный API недоступен — не ваша сеть |
| `symlink`-тест падает на Windows | Ожидаемо, на Linux проходит |
| Модель не вызывает инструменты | Нужна `qwen3 ≥1.7b`, `llama3.1`, `mistral-nemo` |
| `[!] Digest модели НЕ совпал` | Сверьте `HARNESS_MODEL` и `HARNESS_MODEL_DIGEST` в `.env` |
| `python3 не найден, но задан HARNESS_MODEL_DIGEST` | `sudo apt install -y python3` или очистите `HARNESS_MODEL_DIGEST` |
| `[!] Fingerprint GPG Docker не совпал` | MITM/подмена сети. Проверьте вручную (см. раздел «Диагностика» в docs/troubleshooting.md) |

Полная диагностика — `docs/troubleshooting.md`.

---

## Коротко о защите

- **Модель без интернета:** Docker-сеть `internal: true`, исходящий
  трафик блокируется ядром. Единственный канал — `api_call` через
  прокси с whitelist'ом и `X-Proxy-Secret`.
- **Работа только в `./workspace`:** не делайте её симлинком на
  `$HOME`.
- **Запись — только с вашего подтверждения:** одна на сессию, с
  diff и одноразовым кодом. Записанные в сессии файлы нельзя
  прочитать в той же сессии.
- **Скрипты читаемы:** `install-machine.sh` — два `curl` (Docker GPG,
  uv release) с проверкой SHA256 и fingerprint. `setup.sh` — без
  сетевых вызовов. `bootstrap.sh` проверяет `setup.sh` и содержит
  пояснение про ложные срабатывания grep.
- **Цепочка поставки закрыта:** `uv` — версия + SHA256; PyPI —
  `uv.lock` + cooldown 7 дней; образы — опционально digest; модели —
  sha256-манифест + опционально digest; `.env` — в `.gitignore`;
  `body`/`params` — редактируются в audit.

---

## Полный путь

```bash
# 1. Машина (один раз)
chmod +x install-machine.sh && ./install-machine.sh
source ~/.bashrc

# 2. Файлы проекта (сверьте хеш setup.sh)
sha256sum setup.sh                    # сравните с ожидаемым вручную
./setup.sh && cd harness-project

# 3. Bootstrap (опционально с автопроверкой хеша)
cp scripts/bootstrap.sh .
chmod +x bootstrap.sh
./bootstrap.sh --verify-sha256=<ожидаемый-хеш>   # или без флага

# 4. Работа
sudo docker compose exec harness python -m harness.main
```

Правок `.env`, `docker-compose.yml` руками не требуется. Для
изменения политики доступа — один файл `config/fs_policy.yaml`,
перезапуск не нужен.
