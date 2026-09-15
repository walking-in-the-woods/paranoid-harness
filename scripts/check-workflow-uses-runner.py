#!/usr/bin/env python3
"""
Проверяет, что workflow вызывает scripts/run-self-tests.sh
и не содержит прямых вызовов scripts/self-test-*.sh.

Использование:
    check-workflow-uses-runner.py <workflow.yml>

Exit 0 — проверка пройдена.
Exit 1 — прямой вызов self-test или отсутствие runner'а.
Exit 2 — ошибка (файл отсутствует, YAML сломан).
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required", file=sys.stderr)
    sys.exit(2)


# Оба маркера — без префикса ./, чтобы симметрично ловить формы
# "./scripts/...", "bash scripts/...", "scripts/...".
RUNNER_SUBSTRING = "scripts/run-self-tests.sh"
DIRECT_CALL_SUBSTRING = "scripts/self-test-"


def iter_executable_lines(script: str):
    """Строки тела скрипта, исключая пустые и комментарии.

    Обе проверки (runner и direct call) идут по этим строкам —
    симметрично и без ложных срабатываний на комментариях.
    """
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        yield line


def has_direct_self_test_call(script: str) -> bool:
    return any(
        DIRECT_CALL_SUBSTRING in line
        for line in iter_executable_lines(script)
    )


def uses_self_test_runner(script: str) -> bool:
    return any(
        RUNNER_SUBSTRING in line
        for line in iter_executable_lines(script)
    )


def check(workflow_path: Path) -> int:
    if not workflow_path.is_file():
        print(f"workflow not found: {workflow_path}", file=sys.stderr)
        return 2

    try:
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"cannot parse workflow: {exc}", file=sys.stderr)
        return 2

    if not isinstance(data, dict):
        print("workflow top-level must be a mapping", file=sys.stderr)
        return 2

    found_runner = False
    for job_name, job in (data.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            script = step.get("run") or ""
            if has_direct_self_test_call(script):
                print(
                    f"direct self-test call in job {job_name}",
                    file=sys.stderr,
                )
                return 1
            if uses_self_test_runner(script):
                found_runner = True

    if not found_runner:
        print("run-self-tests.sh not called in workflow", file=sys.stderr)
        return 1

    print("[+] workflow uses runner, no direct self-test calls")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <workflow.yml>", file=sys.stderr)
        return 2
    return check(Path(sys.argv[1]))


if __name__ == "__main__":
    sys.exit(main())
