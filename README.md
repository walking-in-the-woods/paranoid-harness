# Local AI Harness

Изолированный локальный агент на Ollama. Модель без интернета, файлы
только в `workspace/`, запись — с подтверждением.

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

## История

См. [CHANGELOG.md](CHANGELOG.md).

## Инструкции по установке

- [Linux](INSTALL-LINUX.md)
- [Windows / WSL2](INSTALL-WINDOWS.md)
