"""Smoke-тесты с реальной моделью. Проверяют базовую работоспособность LLM.

Модели читаются из окружения:
  SMOKE_MODEL_SMALL — для базовых тестов (sentinel/JSON/ASCII).
  По умолчанию — qwen3:0.6b.

Везде передаётся think=False: Qwen3 в Ollama по умолчанию генерирует
внутренний thinking-блок до финального message.content. При малом
num_predict модель не успевает выйти из reasoning и content остаётся
пустым. Эти тесты проверяют детерминированный вывод, а не качество
рассуждений — thinking отключаем. Для моделей без thinking-фазы
параметр игнорируется.
"""

from __future__ import annotations

import json
import os

import ollama
import pytest


MODEL = os.environ.get("SMOKE_MODEL_SMALL", "qwen3:0.6b")
HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")


pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module")
def client() -> ollama.Client:
    return ollama.Client(host=HOST)


@pytest.fixture(scope="module", autouse=True)
def _require_model(client: ollama.Client):
    try:
        client.show(MODEL)
    except Exception as e:
        pytest.skip(f"model {MODEL!r} not available: {e}")


# --------------------------------------------------------------------------
# 1) Sentinel — детерминированный
# --------------------------------------------------------------------------

def test_sentinel_pong(client: ollama.Client):
    resp = client.chat(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": "Reply with exactly one word: PONG",
        }],
        think=False,     # Qwen3: без reasoning-фазы, content не пуст
        options={"temperature": 0.0, "num_predict": 32},
    )
    text = (resp["message"]["content"] or "").strip()
    assert text, "empty response"
    assert "PONG" in text.upper(), f"sentinel not found: {text!r}"


# --------------------------------------------------------------------------
# 2) JSON-mode — структурный
# --------------------------------------------------------------------------

def test_json_mode_structured(client: ollama.Client):
    """Ollama поддерживает format='json' — модель обязана вернуть JSON."""
    resp = client.chat(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": (
                "Return a JSON object with a single field 'status' "
                "whose value is the string 'ok'. "
                "Output ONLY the JSON, no prose."
            ),
        }],
        format="json",
        think=False,     # reasoning-фаза мешает структурному выводу
        options={"temperature": 0.0, "num_predict": 128},
    )
    text = (resp["message"]["content"] or "").strip()
    assert text, "empty response"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        pytest.fail(f"invalid JSON: {e}; got: {text!r}")
    assert isinstance(payload, dict), f"not an object: {payload!r}"
    assert payload.get("status") == "ok", f"wrong payload: {payload!r}"


# --------------------------------------------------------------------------
# 3) ASCII-check
# --------------------------------------------------------------------------

def test_who_are_you_ascii(client: ollama.Client):
    resp = client.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You must answer in English only."},
            {"role": "user", "content": "Who are you?"},
        ],
        think=False,     # устраняем флакость: без reasoning всегда есть content
        options={"temperature": 0.0, "num_predict": 128},
    )
    text = (resp["message"]["content"] or "").strip()
    assert text, "empty response"

    printable = sum(1 for c in text if 32 <= ord(c) < 127 or c in "\n\r\t")
    ratio = printable / len(text)
    assert ratio >= 0.9, (
        f"non-ASCII garbage: ratio={ratio:.2f}, text={text!r}"
    )

    lower = text.lower()
    assert any(w in lower for w in
               ("assistant", "model", "ai", "qwen", "language")), (
        f"unexpected answer: {text!r}"
    )
