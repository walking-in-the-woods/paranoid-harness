"""
Тесты прокси через FastAPI TestClient + мок httpx.AsyncClient.

Маршруты проверяются на реальных публичных API (см. ROUTES в proxy.py).
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import patch

import pytest


SECRET = "test-secret-abc"


@pytest.fixture
def proxy_module(monkeypatch):
    """Импортирует api_proxy.proxy с заданным PROXY_SECRET.

    Модуль читает PROXY_SECRET на уровне модуля — поэтому env ставим до
    import и при необходимости reload.
    """
    monkeypatch.setenv("PROXY_SECRET", SECRET)
    monkeypatch.syspath_prepend("api_proxy")
    # Чистим модуль, если уже импортировался с другим env.
    sys.modules.pop("proxy", None)
    module = importlib.import_module("proxy")
    return module


@pytest.fixture
def client(proxy_module):
    from fastapi.testclient import TestClient
    return TestClient(proxy_module.app)


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def test_health_open(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------

def test_missing_secret_403(client):
    r = client.get("/weather")
    assert r.status_code == 403


def test_wrong_secret_403(client):
    r = client.get("/weather", headers={"X-Proxy-Secret": "nope"})
    assert r.status_code == 403


def test_correct_secret_unknown_route_404(client):
    r = client.get("/does-not-exist",
                   headers={"X-Proxy-Secret": SECRET})
    assert r.status_code == 404


# --------------------------------------------------------------------------
# success path (httpx мокается)
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status: int, text: str):
        self.status_code = status
        self.text = text


class _FakeAsyncClient:
    """Минимальный мок httpx.AsyncClient.

    last_call — экземплярный атрибут: состояние не утекает между тестами.
    """

    def __init__(self, *_, **__):
        self.last_call: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, params=None, content=None, headers=None):
        self.last_call = {
            "method": method,
            "url": url,
            "params": params,
            "content": content,
            "headers": headers,
        }
        return _FakeResponse(200, '{"ok": true}')


def _patched_get(client, proxy_module, route, params=None):
    """Утилита: делает GET и возвращает (response, last_call)."""
    captured: dict = {}

    class _CapturingClient(_FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured["instance"] = self

    with patch.object(proxy_module.httpx, "AsyncClient", _CapturingClient):
        r = client.get(f"/{route}",
                       headers={"X-Proxy-Secret": SECRET},
                       params=params or {})
        return r, captured["instance"].last_call


def test_known_route_calls_configured_upstream(client, proxy_module):
    r, call = _patched_get(client, proxy_module, "weather",
                           params={"latitude": "52.52",
                                   "longitude": "13.41"})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == 200
    assert body["body"] == '{"ok": true}'

    # Проверяем route→URL mapping: хост берётся из ROUTES, не из запроса.
    assert call["url"] == proxy_module.ROUTES["weather"]
    assert call["method"] == "GET"
    assert call["params"] == {"latitude": "52.52", "longitude": "13.41"}


def test_all_routes_point_to_real_hosts(proxy_module):
    """Каждый ROUTES-URL должен быть валидным HTTPS-URL с реальным хостом."""
    from urllib.parse import urlparse

    for name, url in proxy_module.ROUTES.items():
        parsed = urlparse(url)
        assert parsed.scheme == "https", f"route {name}: not https"
        assert parsed.hostname, f"route {name}: no hostname"
        # Отсекаем placeholder-домены точно (example.com и *.example.com),
        # не задевая легитимные хосты вроде myexample.com.
        h = parsed.hostname
        assert h != "example.com" and not h.endswith(".example.com"), \
            f"route {name}: placeholder host {h!r}"


def test_follow_redirects_is_disabled(client, proxy_module):
    """Убеждаемся, что httpx.AsyncClient создаётся с follow_redirects=False."""
    captured: dict = {}

    class _CapturingClient(_FakeAsyncClient):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    with patch.object(proxy_module.httpx, "AsyncClient", _CapturingClient):
        client.get("/weather", headers={"X-Proxy-Secret": SECRET})

    assert captured.get("follow_redirects") is False


# --------------------------------------------------------------------------
# request body limit
# --------------------------------------------------------------------------

def test_request_body_too_large_413(client, proxy_module):
    # MAX_REQ_BODY = 100_000 в proxy.py
    payload = b"x" * (proxy_module.MAX_REQ_BODY + 1)
    r = client.post("/weather",
                    headers={"X-Proxy-Secret": SECRET,
                             "Content-Type": "application/json"},
                    content=payload)
    assert r.status_code == 413
