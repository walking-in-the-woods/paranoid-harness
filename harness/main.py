"""Точка входа: интерактивный REPL поверх HarnessAgent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

from harness.agent_loop import HarnessAgent
from harness.audit import AuditLog
from harness.confirm import ConfirmSession
from harness.fs_guard import FileSystemGuard


BANNER = r"""
============================================================
  Local AI Harness — изолированный ассистент
  /quit  — выход
  /reset — новая сессия (сброс состояния)
============================================================
"""


def load_config() -> dict:
    config_dir = Path(os.environ.get("CONFIG_DIR", "/config"))
    policy_path = config_dir / "fs_policy.yaml"
    if not policy_path.is_file():
        print(f"[fatal] policy not found: {policy_path}", file=sys.stderr)
        sys.exit(1)

    with policy_path.open("r", encoding="utf-8") as fh:
        fs_policy = yaml.safe_load(fh)

    return {
        "ollama_host": os.environ.get(
            "OLLAMA_HOST", "http://localhost:11434"
        ),
        "model": os.environ.get("HARNESS_MODEL", "qwen3:8b"),
        "workspace_dir": os.environ.get("WORKSPACE_DIR", "/workspace"),
        "api_proxy_url": os.environ.get("API_PROXY_URL", ""),
        "proxy_secret": os.environ.get("PROXY_SECRET", ""),
        "audit_path": os.environ.get("AUDIT_PATH", "/logs/audit.jsonl"),
        "fs_policy": fs_policy,
        # --- Гейтвей (mTLS) ---
        "gateway_token": os.environ.get("GATEWAY_TOKEN", ""),
        "gateway_client_cert": os.environ.get("GATEWAY_CLIENT_CERT", ""),
        "gateway_client_key": os.environ.get("GATEWAY_CLIENT_KEY", ""),
        "gateway_ca_cert": os.environ.get("GATEWAY_CA_CERT", ""),
    }


def main() -> None:
    print(BANNER)
    config = load_config()
    workspace = Path(config["workspace_dir"]).resolve()

    try:
        guard = FileSystemGuard(config["fs_policy"])
    except Exception as e:
        print(f"[fatal] cannot initialize fs guard: {e}", file=sys.stderr)
        sys.exit(1)

    audit = AuditLog(config["audit_path"])
    audit.write("session_start", model=config["model"])

    agent = HarnessAgent(config, guard, audit=audit)

    while True:
        try:
            user_input = input("\n>>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[exit]")
            break

        if not user_input:
            continue
        if user_input in ("/quit", "/exit"):
            break
        if user_input == "/reset":
            agent = HarnessAgent(config, guard, audit=audit)
            print("[session reset]")
            continue

        try:
            result = agent.run(user_input)
        except Exception as e:
            print(f"[error] {type(e).__name__}: {e}")
            continue

        print("\n--- MODEL ---")
        print(result["text"])

        if result["pending_writes"]:
            session = ConfirmSession(workspace, guard)
            print()
            print(session.render_preview(result["pending_writes"]))

            try:
                code = input("code> ").strip()
            except (EOFError, KeyboardInterrupt):
                code = ""
                print()

            try:
                outcomes = session.apply(result["pending_writes"], code)
            except Exception as e:
                outcomes = [f"[ERROR] apply failed: "
                            f"{type(e).__name__}: {e}"]

            print()
            for line in outcomes:
                print(line)

            audit.write(
                "apply_result",
                outcomes=outcomes,
                nonce_matched=all(
                    "[CANCELLED]" not in o for o in outcomes
                ),
            )

            for line, w in zip(outcomes, result["pending_writes"]):
                if line.startswith("[OK]"):
                    agent.mark_written(w["canonical"])

    audit.write("session_end")


if __name__ == "__main__":
    main()
