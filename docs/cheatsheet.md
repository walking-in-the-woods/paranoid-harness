# Шпаргалка

Одна страница для повседневной работы.

## Запуск

```bash
# REPL
sudo docker compose exec harness python -m harness.main

# Или одной командой
sudo docker compose run --rm harness python -m harness.main
```

## Команды REPL

| Команда | Действие |
|---|---|
| `/quit` | Выход |
| `/reset` | Новая сессия: обнуляет лимит записей и read-after-write block |
| `Ctrl+C` | Прерывание текущей задачи |

## Рабочая папка

```
workspace/
├── input/    ← сюда кладёте файлы (модель читает, не пишет)
├── output/   ← сюда модель пишет результат
├── notes/    ← черновики
├── docs/     ← документы (writable)
└── drafts/   ← черновики (writable)
```

Скопировать файл:

```bash
cp ~/file.md workspace/input/
```

Забрать результат — просто прочитать:

```bash
cat workspace/output/summary.md
```

## Форма задачи

```
прочитай <путь> и напиши <что> в <путь>
```

Примеры:

```
прочитай input/report.md и напиши резюме в output/summary.md
прочитай input/code.py и объясни в output/explain.md
прочитай input/data.txt и оформи как таблицу в output/table.md
```

## Подтверждение записи

```
============================================================
 PENDING WRITES — ПРОВЕРЬТЕ ПЕРЕД ПОДТВЕРЖДЕНИЕМ
============================================================
--- output/summary.md ---
[NEW FILE, 412 bytes]
# Краткое резюме
...
============================================================
 Введите код для ПРИМЕНЕНИЯ: 4F7A2C19
============================================================

code> 4F7A2C19        ← ввод = запись
code> <Enter>         ← пустой ввод = отмена
code> что-угодно      ← неверный код = отмена
```

## Что разрешено записывать

- `output/**`, `notes/**`, `drafts/**`, `docs/**`
- `*.md`, `*.txt` в корне `workspace/`
- Файлы с любыми расширениями, кроме: `.sh .bash .py .js .ts .rb .go
  .rs .exe .bat .ps1 .php .cgi .pl .whl .egg` — они только в `.txt`

## Что запрещено читать

- `.env`, `.git/**`, `.ssh/**`, `.aws/**`
- `*.key`, `*.pem`, `id_rsa*`
- `.bashrc`, `.zshrc`, `.profile`, `.netrc`
- `Makefile`, `Dockerfile`, `package.json`, `setup.py`,
  `pyproject.toml`, `.github/workflows/*`

## Логи

```bash
# Что модель делала
tail -f logs/audit.jsonl | jq .

# Логи контейнеров
sudo docker compose logs -f harness
sudo docker compose logs -f api-proxy
sudo docker compose logs -f ollama-runner
```

## Полезные команды

```bash
# Статус
sudo docker compose ps

# Перезапуск
sudo docker compose restart harness

# Обновить политики (после правки config/fs_policy.yaml)
# Перезапуск не нужен — новый REPL подхватит

# Остановить всё
sudo docker compose down

# Полная проверка изоляции
sudo docker compose exec harness \
  python -c "import socket; socket.create_connection(('1.1.1.1',53),timeout=2)"
# ожидается ошибка — это правильно
```

## Ограничения

| Что | Сколько |
|---|---|
| Размер файла на чтение | 200 КБ |
| Размер `propose_write` | 1 МБ |
| Записей на сессию | 1 |
| Раундов с инструментами | 6 |

## Что делать при проблеме

1. Посмотреть `logs/audit.jsonl` — что модель вызывала.
2. Посмотреть `sudo docker compose logs harness` — ошибки Python.
3. См. полный [Troubleshooting](troubleshooting.md).

## Не забыть

- **`workspace/` не должен быть симлинком на `$HOME`.**
- **Не кладите секреты в `workspace/`** — всё оттуда читается.
- **Проверяйте diff** перед вводом кода.
- **`path` в audit.jsonl не редактируется.**
