#!/usr/bin/env bash
# Self-test для check-file-matches-pattern.sh.
#
# Сценарии: паттерн есть (rc=0), паттерн отсутствует (rc=1),
#           файл не найден (rc=2), невалидный regex (rc=2).
# Чекер вызывается через `bash`, не как исполняемый файл.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_script="${script_dir}/check-file-matches-pattern.sh"

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
    local file="$1" pattern="$2"
    set +e
    bash "${check_script}" "${file}" "${pattern}" >/dev/null 2>&1
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

printf '%s\n' "has marker-word here" > "${work_dir}/present.txt"
expect_rc "паттерн присутствует" 0 \
    "$(run_check "${work_dir}/present.txt" 'marker-word')"

printf '%s\n' "clean content" > "${work_dir}/absent.txt"
expect_rc "паттерн отсутствует" 1 \
    "$(run_check "${work_dir}/absent.txt" 'marker-word')"

expect_rc "файл не найден" 2 \
    "$(run_check "${work_dir}/missing.txt" 'x')"

printf '%s\n' "content" > "${work_dir}/badregex.txt"
expect_rc "невалидный regex" 2 \
    "$(run_check "${work_dir}/badregex.txt" '[')"

echo "[+] self-test для check-file-matches-pattern.sh passed"
