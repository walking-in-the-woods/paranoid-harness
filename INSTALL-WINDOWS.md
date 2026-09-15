# Установка Local AI Harness на Windows через WSL2

От нуля до работающего харнесса на Windows 11 (или 10 с обновлениями).

**Репозиторий:** <https://github.com/walking-in-the-woods/paranoid-harness>

---

## Требования

- Windows 10 версии 2004+ или Windows 11
- WSL версии 0.67.6 или выше (проверьте: `wsl --version`)
- Виртуализация включена в BIOS/UEFI
- ~30 ГБ свободного места на диске C:
- ~10 ГБ оперативной памяти

---

## Что получится

После установки:

- Модель Ollama работает **без доступа к интернету** (Docker-сеть
  `internal: true`).
- Файловые операции — только в пределах `workspace/` с белым/чёрным
  списками.
- Одна запись на сессию, с подтверждением одноразовым кодом.
- Единственный сетевой канал модели — `api_call` через локальный
  прокси с whitelist'ом.
- mTLS-гейтвей к модели: клиентский сертификат + токен.
- Audit-логи в `logs/audit.jsonl` и `logs/gateway.jsonl`.
- Цепочка поставки: `uv` — версия + SHA256, Python — `uv.lock` +
  cooldown, базовые образы — опционально digest, модели —
  sha256-манифест.

---

## Прочитайте до старта

1. **Проект должен жить в Linux-разделе WSL, не на `/mnt/c/`.**
   Доступ к файлам на Windows-диске из WSL замедляется в 10 и более
   раз. Клонируйте в `~/paranoid-harness/`.

2. **Не удаляйте `[tool.uv] exclude-newer`** из `pyproject.toml`.
   Это cooldown 7 дней — защита от свежих вредоносных релизов PyPI.

3. **Добавьте `metadata` в `/etc/wsl.conf`** — иначе файлы на
   `/mnt/c` будут иметь права `777` и часть проверок `fs_guard`
   может работать неожиданно.

4. **MinGW не нужен.** Все скрипты работают в WSL, где уже есть
   `bash`, `sed`, `tar`, `openssl`, `sha256sum`, `curl`.

5. **Опционально: автоматическая сверка sha256 `setup.sh`.** Если
   вы разворачиваете проект из репозитория (`git clone`) — эта
   проверка не нужна, целостность обеспечивается подписью коммитов
   и HTTPS/TLS GitHub. Если скачали `setup.sh` отдельно — запустите
   `./scripts/bootstrap.sh --verify-sha256=<хеш>`.

6. **`certs/ca.key`** после первого запуска перенесите в
   offline-хранилище.

---

## Шаг 1. Подготовка WSL2

### 1.1. Установка WSL2 и Ubuntu

Откройте PowerShell **от имени администратора**:

```powershell
wsl --install -d Ubuntu-24.04
```

После установки система попросит задать имя пользователя и пароль
для Linux. Пароль понадобится для `sudo`.

Проверьте версию:

```powershell
wsl --version
```

Версия WSL должна быть **не ниже 0.67.6**. Если ниже — обновите:

```powershell
wsl --update
```

### 1.2. Включение systemd и metadata

Зайдите в Ubuntu (из меню «Пуск» или командой `wsl`). Проверьте,
работает ли systemd:

```bash
systemctl is-system-running
```

Если ответ `running` — ничего не нужно. Если ответ `offline` или
ошибка — откройте `/etc/wsl.conf`:

```bash
sudo nano /etc/wsl.conf
```

Приведите к виду:

```ini
[boot]
systemd=true

[automount]
options = "metadata,uid=1000,gid=1000,umask=022"

[user]
default=<ваш_linux_пользователь>
```

Замените `<ваш_linux_пользователь>` на реальное имя (узнать:
`whoami`). Опция `metadata` включает хранение Linux-прав в NTFS;
`uid`, `gid` и `umask` задают владельца и права для файлов на
Windows-диске.

Сохраните (`Ctrl+O`, `Enter`, `Ctrl+X`), затем **выйдите из WSL** и
перезапустите его из PowerShell:

```powershell
wsl --shutdown
```

Снова войдите в Ubuntu и проверьте:

```bash
systemctl is-system-running
# ожидается: running

ls -l /mnt/c/
# владелец должен быть вы, а не root
```

### 1.3. Установка Docker Desktop

Скачайте **Docker Desktop for Windows** с официального сайта
docker.com и установите. При установке убедитесь, что стоит галочка
«Use WSL 2 based engine».

После установки:

1. Запустите Docker Desktop из меню «Пуск».
2. Откройте **Settings → General** и убедитесь, что выбран
   **Use WSL 2 based engine**. Нажмите **Apply**.
3. Откройте **Settings → Resources → WSL Integration** и включите
   интеграцию для вашего дистрибутива Ubuntu. Обычно включена по
   умолчанию, но проверьте.

Проверьте из WSL:

```bash
docker --version
docker compose version
```

**Обратите внимание:** с Docker Desktop команды `docker` и
`docker compose` работают **без `sudo`** — бинарник ставится в PATH
WSL автоматически. Это отличает Windows-сценарий от Linux-инструкции,
где мы работали через `sudo docker`. Группу `docker` настраивать не
нужно.

### 1.4. Установка `uv`

Внутри WSL (Ubuntu) откройте терминал и выполните скрипт установки
`uv`. Для paranoid-режима используйте `install-machine.sh` — он
проверяет SHA256. Быстрый вариант:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
source ~/.bashrc
uv --version
```

**Убедитесь, что `uv` стоит в Linux-разделе** (`~/.local/bin/uv`),
а не на `/mnt/c/`. Иначе производительность резолвинга и установки
пакетов упадёт.

---

## Шаг 2. Клонирование репозитория

**Куда клонировать.** По умолчанию — домашний каталог WSL:

```bash
cd ~
git clone https://github.com/walking-in-the-woods/paranoid-harness.git
cd paranoid-harness
```

Если хотите зафиксировать конкретную версию:

```bash
git clone --branch v0.13 --depth 1 \
  https://github.com/walking-in-the-woods/paranoid-harness.git
cd paranoid-harness
```

**Не клонируйте в `/mnt/c/Users/...`** — проект окажется на
Windows-диске, и производительность операций с файлами упадёт в
разы. Если вы уже развернули проект на `/mnt/c/`, перенесите его:

```bash
cp -r /mnt/c/путь/к/paranoid-harness ~/
cd ~/paranoid-harness
```

**Альтернатива — `setup.sh`.** Если у вас нет доступа к GitHub или
нужно развернуть проект без сети, можно использовать `setup.sh` из
раздела релиза. Он создаёт те же файлы через heredoc'и.

---

## Шаг 3. Bootstrap

Скрипт `bootstrap.sh` из репозитория полностью рабочий в WSL.
Запустите:

```bash
cd ~/paranoid-harness
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh
```

**Что делает bootstrap в WSL** (то же, что в Linux):

1. Проверяет `setup.sh` (`bash -n` + grep по опасным конструкциям).
   Для `git clone` этот шаг пропускается — файла `../setup.sh` нет.
2. Создаёт `.env` из `.env.example`: генерирует `PROXY_SECRET`,
   `GATEWAY_HMAC_KEY`, подставляет реальные `UID`/`GID`.
3. Единоразово переходит на `uv.lock` с cooldown 7 дней.
4. Прогоняет юнит-тесты.
5. Генерирует сертификаты mTLS в `./certs/` через
   `scripts/gateway-certs.sh`.
6. Генерирует токены клиентов гейтвея: токены в `.env`,
   SHA256-хеши в `config/gateway_clients.yaml`.
7. Собирает Docker-образы.
8. Скачивает модель через изолированный `ollama-updater`, снимает
   снапшот, считает SHA256, промоутит в volume раннера.
9. Поднимает все сервисы: `ollama-runner`, `model-gateway`,
   `gateway-tls`, `api-proxy`, `harness`.
10. Fail-closed проверка плейсхолдеров в `.env` и YAML.

**Отличие от Linux.** В bootstrap есть строка:

```bash
if docker info >/dev/null 2>&1; then DOCKER="docker"; else DOCKER="sudo docker"; fi
```

В WSL с Docker Desktop `docker info` работает без sudo, поэтому
`DOCKER="docker"` — команды идут напрямую. Это нормально и
безопасно: Docker Desktop сам управляет правами через
WSL-интеграцию.

---

## Шаг 4. Работа

```bash
docker compose exec harness python -m harness.main
```

(Без `sudo` — Docker Desktop в WSL работает без него.)

Внутри REPL:

- `/quit` — выход
- `/reset` — новая сессия

Пример:

```
>>> прочитай README.md и предложи короткий абзац для docs/overview.md
```

---

## Раздел A. Digest-пиннинг (для машин с секретами)

Теги мутабельны. Digest фиксирует точное содержимое.

```bash
docker pull ollama/ollama:latest
docker inspect --format='{{index .RepoDigests 0}}' ollama/ollama:latest

docker pull python:3.12.7-slim
docker inspect --format='{{index .RepoDigests 0}}' python:3.12.7-slim

docker pull nginx:1.27.2-alpine
docker inspect --format='{{index .RepoDigests 0}}' nginx:1.27.2-alpine
```

Заменить в Dockerfiles, либо автоматически:
`bash scripts/pin-images.sh --update`.

- `docker-compose.yml` — `${OLLAMA_IMAGE}` в `.env` →
  `ollama/ollama@sha256:<digest>`.
- `model_gateway/Dockerfile`, `harness/Dockerfile`,
  `api_proxy/Dockerfile` — `FROM python:3.12.7-slim@sha256:<digest>`.
- `gateway_tls/Dockerfile` — `FROM nginx:1.27.2-alpine@sha256:<digest>`.
- Для `sync-model.sh` — задайте `ALPINE_IMAGE=alpine@sha256:<digest>`.

---

## Раздел B. Производительность и место хранения

### Где держать проект

| Место | Скорость | Когда использовать |
|---|---|---|
| `~/paranoid-harness` (Linux-раздел) | Быстро | **Всегда, по умолчанию** |
| `/mnt/c/...` (Windows-раздел) | Медленно, в 10+ раз | Никогда для этого проекта |

WSL2 использует файловый трансляционный слой для доступа к
Windows-дискам через `/mnt/c`. Каждая файловая операция пересекает
границу между Linux и Windows. Создание сотни мелких файлов на
`/mnt/c` может занять в десятки раз больше времени, чем на
Linux-разделе.

Все команды Docker Compose работают с bind-mount `./workspace`.
Если проект на `/mnt/c`, **все файловые операции модели** пойдут
через медленный слой. Для харнесса это критично: `list_dir` и
`read_file` вызываются часто.

**Правило:** проект и `workspace/` — только в Linux-разделе.

### Если нужно работать с файлами Windows

Скопируйте файл в `workspace/input/` на Linux-разделе:

```bash
cp /mnt/c/Users/ВашеИмя/Documents/report.md ~/paranoid-harness/workspace/input/
```

Результат, который модель запишет в `workspace/output/`, потом
скопируйте обратно:

```bash
cp ~/paranoid-harness/workspace/output/summary.md /mnt/c/Users/ВашеИмя/Documents/
```

**Не запускайте модель на файлах с `/mnt/c` напрямую.** Работайте
через `workspace/`.

---

## Раздел C. Очистка дискового пространства

WSL2 использует динамический виртуальный диск (`ext4.vhdx`). Когда
вы удаляете файлы внутри WSL, место на диске Windows **не
освобождается автоматически** — файл диска остаётся того же размера.

### Периодическая очистка

```bash
# 1. Удалить неиспользуемые образы и тома Docker
docker system prune -a --volumes

# 2. В PowerShell (от администратора):
wsl --shutdown

# 3. Сжать виртуальный диск (diskpart)
diskpart
# внутри diskpart:
select vdisk file="C:\Users\ВашеИмя\AppData\Local\Docker\wsl\data\ext4.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
```

Точный путь к `ext4.vhdx` зависит от версии Docker Desktop. Найти
можно так:

```powershell
Get-ChildItem -Path "$env:LOCALAPPDATA\Docker" -Recurse -Filter "ext4.vhdx"
```

**Рекомендация:** запускать `docker system prune` раз в месяц,
сжатие VHDX — раз в квартал.

---

## Раздел D. Проблемы совместимости и MinGW

### О MinGW

**MinGW не нужен для работы этого проекта.** Это набор инструментов
для компиляции Windows-приложений из Linux-подобной среды. Все
скрипты проекта (`setup.sh`, `bootstrap.sh`, `install-machine.sh`)
работают **внутри WSL**, где уже есть полноценный `bash`, `openssl`,
`sha256sum`, `sed`, `tar`, `curl`. Устанавливать их из Windows-мира
нет необходимости.

Установка MinGW может даже создать проблемы. В системах с WSL есть
deprecated `bash.exe` в `System32`, который является stub'ом для
запуска WSL. Если вы запускаете скрипты из Git Bash (который
использует MinGW) и скрипт вызывает `bash`, вызов может уйти в
WSL-stub вместо Git Bash или наоборот — это известная проблема
несовместимости.

### Когда Git Bash нужен

Если вы предпочитаете работать с git-репозиторием из
Windows-терминала, Git Bash (поставляется с Git for Windows,
использует MinGW) полезен для:

- `git clone`, `git status`, `git diff` — на Windows-стороне.
- Чтения файлов проекта (просмотр).

Но **не для запуска скриптов проекта**. Скрипты запускайте только
в WSL-терминале.

### Правило

| Что | Где запускать |
|---|---|
| `setup.sh`, `bootstrap.sh` | WSL (Ubuntu) |
| `docker compose ...` | WSL (Ubuntu) |
| `git ...` | WSL или Git Bash — без разницы |
| `uv ...` | WSL (Ubuntu) |
| Просмотр файлов | Windows Explorer (через `\\wsl$\Ubuntu\home\...`) |

### Доступ к файлам WSL из Windows

Чтобы открыть папку `workspace/` в Проводнике:

```
\\wsl$\Ubuntu\home\<пользователь>\paranoid-harness\workspace
```

Или в PowerShell:

```powershell
explorer.exe "\\wsl$\Ubuntu\home\$env:USERNAME\paranoid-harness\workspace"
```

Отсюда можно копировать файлы в `input/` и забирать из `output/`
обычным drag-and-drop. Bind-mount работает в обе стороны.

---

## Раздел E. Sudo без пароля (опционально)

Docker Desktop в WSL не требует `sudo` для `docker` и
`docker compose`. Но если в других частях bootstrap нужны root-команды
и вы не хотите каждый раз вводить пароль:

```bash
echo "$USER ALL=(ALL:ALL) NOPASSWD: ALL" | \
  sudo tee /etc/sudoers.d/dont-prompt-$USER-for-sudo-password
```

**Внимание:** это снижает безопасность — любой процесс в WSL сможет
выполнять команды от root без пароля. Используйте только на
доверенной машине.

---

## Раздел F. Logrotate для `audit.jsonl` и `gateway.jsonl`

Готовый шаблон лежит в `config/logrotate.harness`. Установка:

```bash
cd ~/paranoid-harness
sed "s|@PROJECT_PATH@|$(pwd)|; s|@UID@|$(id -u)|; s|@GID@|$(id -g)|" \
  config/logrotate.harness | sudo tee /etc/logrotate.d/harness

sudo logrotate -d /etc/logrotate.d/harness
```

См. `docs/operations.md`.

---

## Проверка целостности setup.sh (только для пути через setup.sh)

`bootstrap.sh` **не сверяет** sha256 `setup.sh` автоматически по
умолчанию. Сверка хеша — ваша ответственность:

```bash
sha256sum setup.sh
# сравните вручную с ожидаемым хешем из документации к релизу
```

**Опциональная автоматическая проверка:**

```bash
./scripts/bootstrap.sh --verify-sha256=<ожидаемый-хеш>
```

**Формат хеша:** 64 hex-символа в нижнем регистре, без префикса
`sha256:`. При несовпадении скрипт падает до продолжения.

---

## Диагностика

| Симптом | Решение |
|---|---|
| `command not found: uv` | `source ~/.bashrc` или новый терминал WSL |
| `Cannot connect to the Docker daemon` | Запустите Docker Desktop, проверьте **Settings → Resources → WSL Integration** |
| `docker: command not found` в WSL | Включите WSL Integration для вашего дистрибутива в Docker Desktop |
| `systemctl is-system-running` → `offline` | Добавьте `[boot] systemd=true` в `/etc/wsl.conf`, `wsl --shutdown`, войдите заново |
| `Permission denied` при записи в `workspace/` | Проверьте `/etc/wsl.conf`: `automount options = "metadata,uid=1000,gid=1000,umask=022"` |
| Файлы на `/mnt/c` имеют права `777` | Добавьте `metadata` в `automount options` в `/etc/wsl.conf` |
| Медленная работа `list_dir` | Проект лежит на `/mnt/c`. Перенесите в `~/` |
| Не освобождается место на диске C: | См. раздел C (очистка) |
| `model not found` | `bash scripts/sync-model.sh qwen3:8b` |
| `502 upstream error` при `api_call` | Публичный API недоступен — не ваша сеть |
| Модель не вызывает инструменты | Нужна `qwen3 ≥1.7b`, `llama3.1`, `mistral-nemo` |
| `bash: ./setup.sh: /bin/bash^M: bad interpreter` | Файл скачан с Windows-переносами строк. `sed -i 's/\r$//' setup.sh` |
| `python3 не найден, но задан HARNESS_MODEL_DIGEST` | `sudo apt install -y python3` или очистите `HARNESS_MODEL_DIGEST` |
| `[!] Не найден обязательный файл: X` | Повреждённый клон. Проверьте `git status`, `ls` |
| `[!] В .env остались плейсхолдеры` | Проверьте `CLIENTS=()` в bootstrap и `name:` в YAML |

---

## Коротко о защите

- **Модель без интернета:** Docker-сеть `internal: true`, исходящий
  трафик блокируется ядром. Единственный канал — `api_call` через
  прокси с whitelist'ом и `X-Proxy-Secret`.
- **Работа только в `workspace/`:** не делайте её симлинком на
  `$HOME`.
- **Запись — только с вашего подтверждения:** одна на сессию, с
  diff и одноразовым кодом.
- **mTLS-гейтвей:** клиентский сертификат + токен.
- **Скрипты читаемы:** `install-machine.sh` — два `curl` (Docker GPG,
  uv release) с проверкой SHA256 и fingerprint. `setup.sh` — без
  сетевых вызовов. `bootstrap.sh` проверяет `setup.sh`.
- **Цепочка поставки закрыта:** `uv` — версия + SHA256; PyPI —
  `uv.lock` + cooldown 7 дней; образы — опционально digest; модели —
  sha256-манифест; `.env` — в `.gitignore`.

---

## Полный путь

```bash
# 1. Подготовка WSL (один раз)
#    - установка Ubuntu 24.04 через wsl --install
#    - включение systemd и metadata в /etc/wsl.conf
#    - wsl --shutdown, повторный вход
#    - установка Docker Desktop с WSL Integration
#    - установка uv в WSL

# 2. Клонирование репозитория
cd ~
git clone https://github.com/walking-in-the-woods/paranoid-harness.git
cd paranoid-harness

# 3. Bootstrap
chmod +x scripts/bootstrap.sh
./scripts/bootstrap.sh

# 4. Работа
docker compose exec harness python -m harness.main
```

**Проверка изоляции:**

```bash
docker compose exec harness python -c \
  "import socket; socket.create_connection(('1.1.1.1', 53), timeout=2)"
# Должно завершиться ошибкой DNS/network unreachable

docker compose exec ollama-runner sh -c \
  'wget -qO- --timeout=2 https://example.com' || echo "NO INTERNET (OK)"
```

Правок `.env`, `docker-compose.yml` руками не требуется. Для
изменения политики доступа — один файл `config/fs_policy.yaml`,
перезапуск не нужен.
