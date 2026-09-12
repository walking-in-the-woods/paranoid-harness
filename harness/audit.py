"""JSONL-аудит. Пишется вне workspace, чтобы модель его не читала.

fsync выполняется только для критичных событий (apply_result,
session_start, session_end, propose_write, user_prompt_blocked,
ollama_error) — информационные (tool_call, tool_result, user_prompt)
пишутся с flush, но без fsync. Компромисс: критичное не теряется при
сбое, отклик не замедляется на каждом вызове инструмента.

ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ: paths в логе не редактируются. Если вы
назвали файл `notes/клиент_Иванов_договор.md`, это имя попадёт в
audit.jsonl. См. docs/operations.md, раздел «Известные ограничения
audit-лога».
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


# События, для которых fsync обязателен. Всё остальное — flush.
_DURABLE_EVENTS = frozenset({
    "session_start",
    "session_end",
    "apply_result",
    "propose_write",
    "user_prompt_blocked",
    "ollama_error",
})


class AuditLog:
    def __init__(self, path: str):
        self.path = Path(path)
        self._enabled = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8"):
                pass
            self._enabled = True
        except OSError:
            import sys
            print(f"[warn] audit log disabled: cannot open {self.path}",
                  file=sys.stderr)

    def write(self, event: str, **fields: Any) -> None:
        if not self._enabled:
            return
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "pid": os.getpid(),
            "event": event,
            **fields,
        }
        durable = event in _DURABLE_EVENTS
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()
                if durable:
                    os.fsync(fh.fileno())
        except OSError:
            # Аудит не должен ломать харнесс. Потеря строки — приемлемая
            # цена, падение сессии — нет.
            pass
