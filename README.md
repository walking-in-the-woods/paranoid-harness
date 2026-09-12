# Local AI Harness

Изолированный локальный агент на Ollama. Модель без интернета, файлы
только в `workspace/`, запись — с подтверждением.

**Репозиторий:** <https://github.com/walking-in-the-woods/paranoid-harness>

## Быстрый старт

```bash
git clone https://github.com/walking-in-the-woods/paranoid-harness.git
cd paranoid-harness
```

Дальше — по инструкции для вашей ОС:

- [Linux](INSTALL-LINUX.md)
- [Windows / WSL2](INSTALL-WINDOWS.md)

## Документация

- [Обзор](docs/index.md)
- [Установка](docs/install.md)
- [Шпаргалка](docs/cheatsheet.md)
- [Рецепты](docs/cookbook.md)
- [Диагностика](docs/troubleshooting.md)
- [Модель угроз](docs/security-model.md)

## Сборка документации локально

```bash
pip install mkdocs-material "mkdocstrings[python]"
mkdocs serve
# http://127.0.0.1:8000
```

## Альтернативный путь: `setup.sh`

Если вы получили `setup.sh` отдельно (без доступа к репозиторию),
он по-прежнему создаёт дерево проекта и все файлы. Публикуется как
самостоятельный артефакт; хеш для проверки целостности — в разделе
«Прочитайте до старта» соответствующей инструкции.

## История

См. [CHANGELOG.md](CHANGELOG.md).
