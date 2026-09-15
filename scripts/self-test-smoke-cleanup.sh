#!/usr/bin/env bash
# Self-test для scripts/check-smoke-cleanup.sh.
#
# Проверяет пять сценариев: пусто, certs-smoke/,
# docker-compose.smoke.yml, оба артефакта, base_directory с пробелом.
# Работает в изолированном временном каталоге, cwd не трогает.
#
# Чекер вызывается через `bash`, не как исполняемый файл: локальный
# клон может быть без +x.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
check_script="${script_dir}/check-smoke-cleanup.sh"

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

expect_pass() {
    local scenario="$1" directory="$2"
    if ! bash "${check_script}" "${directory}" >/dev/null 2>&1; then
        echo "FAIL: ${scenario} — ожидался успех" >&2
        exit 1
    fi
    echo "OK: ${scenario}"
}

expect_fail() {
    local scenario="$1" directory="$2"
    if bash "${check_script}" "${directory}" >/dev/null 2>&1; then
        echo "FAIL: ${scenario} — ожидалось падение" >&2
        exit 1
    fi
    echo "OK: ${scenario}"
}

expect_pass "пусто" "${work_dir}"

mkdir -p "${work_dir}/certs-smoke"
expect_fail "certs-smoke/" "${work_dir}"
rmdir "${work_dir}/certs-smoke"

touch "${work_dir}/docker-compose.smoke.yml"
expect_fail "docker-compose.smoke.yml" "${work_dir}"
rm -f "${work_dir}/docker-compose.smoke.yml"

mkdir -p "${work_dir}/certs-smoke"
touch "${work_dir}/docker-compose.smoke.yml"
expect_fail "оба артефакта" "${work_dir}"
rm -rf "${work_dir}/certs-smoke" "${work_dir}/docker-compose.smoke.yml"

spaced_dir="${work_dir}/with space"
mkdir -p "${spaced_dir}/certs-smoke"
expect_fail "пробел в пути" "${spaced_dir}"
rm -rf "${spaced_dir}"

echo "[+] self-test passed"
