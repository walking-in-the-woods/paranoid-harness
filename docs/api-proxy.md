# Внешние API через прокси

Прокси — единственный контейнер, видящий интернет. Модель обращается
к нему через tool `api_call`.

## Маршруты по умолчанию

| Route | Upstream | Назначение |
|---|---|---|
| `weather` | `api.open-meteo.com` | Погода (CC BY 4.0) |
| `translate` | `api.mymemory.translated.net` | Перевод (1000 слов/день) |
| `fake-data` | `jsonplaceholder.typicode.com` | Тестовые JSON |
| `countries` | `restcountries.com` | Информация о странах |

## Добавить свой

В `api_proxy/proxy.py`:

```python
ROUTES = {
    "weather":    "https://api.open-meteo.com/v1/forecast",
    "myapi":      "https://api.real-service.com/v1/endpoint",
    ...
}
```

Пересобрать прокси:

```bash
sudo docker compose build api-proxy
sudo docker compose up -d api-proxy
```

Модель вызывает `api_call(route="myapi", method="GET", params={...})`.

## Почему это безопасно

- **Хост берётся из `ROUTES`**, не из запроса. Модель не может
  подставить `api.allowed.com@internal-host`.
- **`follow_redirects=False`.** Upstream не уведёт трафик через 30x.
- **`X-Proxy-Secret`.** Обязателен в каждом запросе.
- **Лимиты.** `MAX_REQ_BODY` (100 КБ), `MAX_RESP_BODY` (200 КБ).
- **Белый список заголовков.** Только `content-type`, `accept`,
  `authorization`.

## Ограничения

- **Смена `PROXY_SECRET` требует пересборки прокси.**
- **Внешний сервис может быть недоступен.** Прокси вернёт
  `502 upstream error`.
- **Прокси — единственная точка.** Если upstream скомпрометирован,
  он увидит ваши запросы к нему.
