"""
Единственная точка выхода в интернет.

* Named routes: хост НИКОГДА не выводится из URL запроса —
  это закрывает SSRF-обход.
* follow_redirects=False — редирект не уведёт на внутренний адрес.
* Аутентификация через X-Proxy-Secret.
* Лимит размера request body и response body.
* Базовое логирование в stdout -> docker json-file driver.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import FastAPI, Header, HTTPException, Request


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s proxy %(message)s",
)
log = logging.getLogger("proxy")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

PROXY_SECRET = os.environ.get("PROXY_SECRET", "")

# Имя маршрута -> ПОЛНЫЙ upstream URL.
#
# Все маршруты указывают на реальные публичные API без ключей:
#   * Open-Meteo        — погода, non-commercial, CC BY 4.0
#   * MyMemory          — перевод, 1000 слов/день без ключа
#   * JSONPlaceholder   — фейковые данные для тестов
#   * REST Countries    — информация о странах
#
# Чтобы добавить свой — замените URL и пересоберите контейнер.
ROUTES: dict[str, str] = {
    "weather":    "https://api.open-meteo.com/v1/forecast",
    "translate":  "https://api.mymemory.translated.net/get",
    "fake-data":  "https://jsonplaceholder.typicode.com/posts",
    "countries":  "https://restcountries.com/v3.1/all",
}

ALLOWED_HEADERS = {"content-type", "accept", "authorization"}

MAX_REQ_BODY = 100_000
MAX_RESP_BODY = 200_000


@app.get("/health")
async def health():
    return {"ok": True}


@app.api_route("/{route}", methods=["GET", "POST"])
async def proxy(
    route: str,
    request: Request,
    x_proxy_secret: str = Header(default=""),
):
    if not PROXY_SECRET or x_proxy_secret != PROXY_SECRET:
        log.warning("auth failed route=%s", route)
        raise HTTPException(status_code=403, detail="forbidden")

    upstream = ROUTES.get(route)
    if not upstream:
        log.info("unknown route=%s", route)
        raise HTTPException(status_code=404, detail="unknown route")

    body = await request.body()
    if len(body) > MAX_REQ_BODY:
        log.warning("request body too large route=%s size=%d", route, len(body))
        raise HTTPException(status_code=413, detail="request too large")

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in ALLOWED_HEADERS
    }

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=upstream,
                params=dict(request.query_params),
                content=body if body else None,
                headers=headers,
            )
        except httpx.RequestError as e:
            log.error("upstream error route=%s err=%s", route, e)
            raise HTTPException(status_code=502, detail=f"upstream error: {e}")

    text = resp.text[:MAX_RESP_BODY]
    log.info("route=%s method=%s status=%d bytes=%d",
             route, request.method, resp.status_code, len(text))
    return {"status": resp.status_code, "body": text}
