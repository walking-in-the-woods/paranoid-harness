#!/usr/bin/env bash
# Self-test для check-workflow-uses-runner.py.
#
# Сценарии: корректный workflow, прямой вызов, комментарий
# (не считается), нет runner, файл не найден, bash-форма прямого
# вызова, bash-форма runner.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_script="${script_dir}/check-workflow-uses-runner.py"

if [[ ! -f "${check_script}" ]]; then
    echo "FAIL: missing: ${check_script}" >&2
    exit 1
fi
if [[ ! -r "${check_script}" ]]; then
    echo "FAIL: not readable: ${check_script}" >&2
    exit 1
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

run_check() {
    local workflow_file="$1"
    set +e
    python3 "${check_script}" "${workflow_file}" >/dev/null 2>&1
    local rc=$?
    set -e
    echo "${rc}"
}

expect_rc() {
    local scenario="$1" expected_rc="$2" actual_rc="$3"
    if [[ "${actual_rc}" -ne "${expected_rc}" ]]; then
        echo "FAIL: ${scenario} — rc=${actual_rc}, ожидался ${expected_rc}" >&2
        exit 1
    fi
    echo "OK: ${scenario}"
}

cat > "${work_dir}/good.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: run
        run: |
          bash scripts/run-self-tests.sh
YAML
expect_rc "корректный workflow" 0 "$(run_check "${work_dir}/good.yml")"

cat > "${work_dir}/direct.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: bad
        run: |
          bash scripts/self-test-filename-pattern.sh
YAML
expect_rc "прямой вызов" 1 "$(run_check "${work_dir}/direct.yml")"

cat > "${work_dir}/comment.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: ok
        run: |
          # см. scripts/self-test-filename-pattern.sh
          bash scripts/run-self-tests.sh
YAML
expect_rc "прямое упоминание в комментарии" 0 \
    "$(run_check "${work_dir}/comment.yml")"

cat > "${work_dir}/no-runner.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: nothing
        run: echo hello
YAML
expect_rc "нет runner" 1 "$(run_check "${work_dir}/no-runner.yml")"

expect_rc "файл не найден" 2 \
    "$(run_check "${work_dir}/nonexistent.yml")"

cat > "${work_dir}/comment-only-runner.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: ok
        run: |
          # see scripts/run-self-tests.sh
          echo hello
YAML
expect_rc "комментарий не считается runner'ом" 1 \
    "$(run_check "${work_dir}/comment-only-runner.yml")"

cat > "${work_dir}/direct-dot-slash.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: bad
        run: |
          ./scripts/self-test-x.sh
YAML
expect_rc "dot-slash форма прямого вызова" 1 \
    "$(run_check "${work_dir}/direct-dot-slash.yml")"

cat > "${work_dir}/dot-slash-runner.yml" <<'YAML'
jobs:
  test:
    steps:
      - name: ok
        run: |
          ./scripts/run-self-tests.sh
YAML
expect_rc "dot-slash форма runner" 0 \
    "$(run_check "${work_dir}/dot-slash-runner.yml")"

echo "[+] self-test для check-workflow-uses-runner.py passed"
