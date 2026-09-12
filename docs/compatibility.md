# Совместимость

## Модели

Tool calling — обязательное требование для полноценной работы.

### Проверенные

| Модель | Размер | Tool calling | Заметки |
|---|---|---|---|
| `qwen3:0.6b` | ~400 МБ | ⚠ нестабильно | Для smoke-тестов |
| `qwen3:1.7b` | ~1.2 ГБ | ✅ | Минимум для tool calling |
| `qwen3:4b` | ~2.6 ГБ | ✅ | Хороший компромисс |
| `qwen3:8b` | ~5 ГБ | ✅ | Рекомендуется как рабочая |
| `qwen3:14b` | ~9 ГБ | ✅ | Для сложных задач |
| `qwen3:32b` | ~20 ГБ | ✅ | Если хватает RAM/VRAM |
| `granite3.3:8b` | ~5 ГБ | ✅ | Альтернатива, IBM |
| `mistral-small3.2` | ~14 ГБ | ✅ | Mistral |
| `hermes3:8b` | ~5 ГБ | ✅ | Fine-tuned под tool calling |
| `llama3.1:8b` | ~4.7 ГБ | ✅ | Альтернатива qwen3 |
| `mistral-nemo` | ~7 ГБ | ✅ | Хорошо следует инструкциям |
| `command-r` | ~20 ГБ | ✅ | Хорошо работает с RAG-сценариями |

### Не поддерживают tool calling

- `llama2:*`
- `gemma:*`, `gemma2:*`
- `phi-3-mini`
- `deepseek-coder` (базовая версия)

### Как проверить

```bash
sudo docker compose exec ollama-runner ollama show <модель> | grep -i tools
```

## Лимиты

| Параметр | Значение | Где менять |
|---|---|---|
| `MAX_TOOL_ROUNDS` | 6 | `harness/agent_loop.py` |
| `MAX_READ_BYTES` | 200 000 (200 КБ) | `harness/agent_loop.py` |
| `MAX_LIST_ENTRIES` | 1000 | `harness/agent_loop.py` |
| `MAX_WRITE_BYTES` | 1 000 000 (1 МБ) | `harness/agent_loop.py` |
| `MAX_API_RESPONSE` | 100 000 | `harness/agent_loop.py` |
| `MAX_REQ_BODY` | 100 000 | `api_proxy/proxy.py` |
| `MAX_RESP_BODY` | 200 000 | `api_proxy/proxy.py` |

При изменении лимитов пересобрать соответствующий контейнер:

```bash
sudo docker compose build harness
sudo docker compose build api-proxy
sudo docker compose up -d --force-recreate harness api-proxy
```

## Ресурсы хоста

### Минимум

- 2 ядра CPU, 8 ГБ RAM, 20 ГБ места
- Модель `qwen3:1.7b`

### Комфортно

- 4+ ядра CPU, 16 ГБ RAM, 30 ГБ места
- Модель `qwen3:8b`

### С GPU

- NVIDIA с 8+ ГБ VRAM
- NVIDIA Container Toolkit
- Модель `qwen3:8b` или `14b`

### Прокидывание GPU в контейнер

Добавьте в `docker-compose.yml` в сервис `ollama-runner`:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

Перезапустите:

```bash
sudo docker compose up -d --force-recreate ollama-runner
sudo docker compose exec ollama-runner nvidia-smi
```

## Операционные системы

### Полностью поддерживается

- Ubuntu 22.04 LTS
- Ubuntu 24.04 LTS
- Debian 12 (bookworm)
- Windows через WSL2 с Ubuntu 24.04

### Работает с оговорками

- **Fedora / RHEL 9+** — замените `apt` на `dnf`.
- **Arch / Manjaro** — установка вручную.
- **macOS** — Docker Desktop + инструкция для Linux.

### Не поддерживается

- **Windows нативно** — используйте WSL2.

## Совместимость версий

| Компонент | Минимум | Проверено на |
|---|---|---|
| Docker | 24.0 | 26.x |
| Docker Compose | v2.20 | v2.29 |
| Python (для тестов) | 3.10 | 3.12 |
| Ollama | 0.3.0 | 0.5.x |
| uv | 0.9.29 | 0.12.x |

## Тестовые окружения CI

Workflow гоняется на `ubuntu-24.04`. Матрица моделей:

- `qwen3:0.6b` — базовый smoke (sentinel, JSON, ASCII).
- `qwen3:1.7b` — tool calling через `HarnessAgent`.

Модели для тестов можно переопределить через repo variables:
`SMOKE_MODEL`, `SMOKE_MODEL_SMALL`.

## Ограничения окружения

**Air-gapped окружение.** Полностью изолированная машина не сможет
сделать `docker compose build` и `sync-model.sh`. Варианты:

1. Собрать образы на машине с сетью, экспортировать `docker save`,
   перенести, загрузить `docker load`.
2. Модель скачать отдельно, перенести как `.tgz`.
3. `uv.lock` и `pyproject.toml` перенести, `uv sync --locked`
   сделать в air-gapped режиме.

Air-gapped сценарий не автоматизирован — вручную.
