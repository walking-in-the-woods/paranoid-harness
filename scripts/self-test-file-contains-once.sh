#!/usr/bin/env bash
# Self-test для check-file-contains-once.sh.
#
# Сценарии: 0 вхождений (rc=1), 1 вхождение (rc=0),
#           2 вхождения (rc=1), файл не найден (rc=2).
# Чекер вызывается через `bash`, не как исполняемый файл.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_script="${script_dir}/check-file-contains-once.sh"

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
    local file="$1" literal="$2"
    set +e
    bash "${check_script}" "${file}" "${literal}" >/dev/null 2>&1
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

literal='test-marker-line'

printf '%s\n' "no marker here" > "${work_dir}/zero.txt"
expect_rc "0 вхождений" 1 "$(run_check "${work_dir}/zero.txt" "${literal}")"

printf '%s\n' "${literal}" > "${work_dir}/one.txt"
expect_rc "1 вхождение" 0 "$(run_check "${work_dir}/one.txt" "${literal}")"

printf '%s\n' "${literal}" "${literal}" > "${work_dir}/two.txt"
expect_rc "2 вхождения" 1 "$(run_check "${work_dir}/two.txt" "${literal}")"

expect_rc "файл не найден" 2 \
    "$(run_check "${work_dir}/missing.txt" "${literal}")"

echo "[+] self-test для check-file-contains-once.sh passed"
