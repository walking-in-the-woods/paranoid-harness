#!/usr/bin/env bash
# Запускает все self-tests проекта.
#
# Обнаруживает scripts/self-test-*.sh автоматически. Добавление
# нового self-test'а не требует правки этого файла.
#
# Использование:
#   bash scripts/run-self-tests.sh
#
# Exit 0 — все прошли.
# Exit 1 — хотя бы один упал (запускаются все, чтобы показать
#          полную картину).

set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

self_tests=()
while IFS= read -r test_path; do
    self_tests+=("${test_path}")
done < <(find "${script_dir}" -maxdepth 1 -type f \
         -name 'self-test-*.sh' | sort)

if [[ "${#self_tests[@]}" -eq 0 ]]; then
    echo "FAIL: no scripts/self-test-*.sh found in ${script_dir}" >&2
    exit 1
fi

failed=0
for test_path in "${self_tests[@]}"; do
    test_name="$(basename "${test_path}")"
    echo "=== ${test_name} ==="
    if [[ ! -x "${test_path}" ]]; then
        echo "SKIP: not executable: ${test_path}" >&2
        failed=1
        continue
    fi
    if ! "${test_path}"; then
        echo "FAILED: ${test_name}" >&2
        failed=1
    fi
done

if [[ "${failed}" -ne 0 ]]; then
    echo "[!] self-tests failed" >&2
    exit 1
fi
echo "[+] all self-tests passed (${#self_tests[@]} total)"
