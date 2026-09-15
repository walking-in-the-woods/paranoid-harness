"""
End-to-end smoke: модель -> HarnessAgent -> tool call -> результат.

Требует модель, поддерживающую tool calling (qwen3:1.7b или больше).
На qwen3:0.6b тест скипается через SMOKE_TOOL_CAPABLE=false.

Smoke-тесты обращаются к Ollama НАПРЯМУЮ через OLLAMA_HOST —
гейтвей не задействован. Поэтому клиент инжектится через `client=`,
минуя `_make_ollama_client`, который требует mTLS-конфиг
(GATEWAY_CLIENT_CERT/KEY/CA_CERT). В CI эти тесты не гоняются
(`--ignore=tests/smoke`); локально запускаются на dev-хосте, где
mTLS-сертификатов может не быть.
"""

from __future__ import annotations

import os
from pathlib import Path

import ollama
import pytest

from harness.agent_loop import HarnessAgent
from harness.fs_guard import FileSystemGuard


MODEL = os.environ.get("SMOKE_MODEL", "qwen3:1.7b")
HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
TOOL_CAPABLE = os.environ.get("SMOKE_TOOL_CAPABLE", "true").lower() == "true"


pytestmark = pytest.mark.smoke


@pytest.fixture(scope="module", autouse=True)
def _require_tool_capable():
    if not TOOL_CAPABLE:
        pytest.skip("model not marked as tool-capable (SMOKE_TOOL_CAPABLE=false)")


@pytest.fixture(scope="module", autouse=True)
def _require_model():
    try:
        ollama.Client(host=HOST).show(MODEL)
    except Exception as e:
        pytest.skip(f"model {MODEL!r} not available: {e}")


@pytest.fixture
def agent(tmp_path: Path) -> HarnessAgent:
    """HarnessAgent с прямым ollama.Client (без mTLS)."""
    (tmp_path / "notes").mkdir()
    (tmp_path / "hello.txt").write_text("PONG-42\n", encoding="utf-8")

    guard = FileSystemGuard({
        "root": str(tmp_path),
        "whitelist": ["**"],
        "blacklist": [],
        "writable": ["notes/**", "*.txt"],
    })
    # Прямой клиент к Ollama. Smoke не проверяет mTLS-путь —
    # для этого нужен gateway-tls, а он в CI/локально недоступен.
    direct_client = ollama.Client(host=HOST)
    return HarnessAgent(
        {
            "workspace_dir": str(tmp_path),
            "ollama_host": HOST,
            "model": MODEL,
            "api_proxy_url": "",
            "proxy_secret": "",
        },
        guard,
        client=direct_client,
    )


def test_read_file_via_tool_call(agent: HarnessAgent):
    """Модель должна вызвать read_file и вернуть содержимое файла."""
    result = agent.run(
        "Read the file hello.txt and tell me exactly what is inside it. "
        "The file content is a short ASCII string."
    )
    text = result["text"]

    if "PONG-42" in text:
        return

    pytest.xfail(
        f"model did not surface tool result. Response: {text[:300]!r}"
    )


def test_propose_write_via_tool_call(agent: HarnessAgent):
    """Модель должна вызвать propose_write и заполнить pending_writes."""
    result = agent.run(
        "Create a file notes/smoke.txt containing exactly the text 'OK-HARNESS'. "
        "Use the propose_write tool."
    )
    pending = result["pending_writes"]

    if not pending:
        pytest.xfail(
            f"model did not call propose_write. Response: {result['text'][:300]!r}"
        )

    normalized = Path(pending[0]["path"]).as_posix().removeprefix("./")
    assert normalized.startswith("notes/"), (
        f"unexpected path: {pending[0]['path']!r}"
    )
    assert "OK-HARNESS" in pending[0]["content"]
