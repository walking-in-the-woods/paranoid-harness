#!/usr/bin/env bash
# Проверяет, что паттерн присутствует в файле хотя бы один раз.
#
# Использование:
#   check-file-matches-pattern.sh <file> <extended-regex>
#
# Exit 0 — паттерн найден.
# Exit 1 — паттерн отсутствует.
# Exit 2 — файл отсутствует или grep завершился с ошибкой.

set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 <file> <extended-regex>" >&2
    exit 2
fi

target_file="$1"
pattern="$2"

if [[ ! -f "${target_file}" ]]; then
    echo "file not found: ${target_file}" >&2
    exit 2
fi

set +e
grep -qE -- "${pattern}" "${target_file}"
grep_rc=$?
set -e

case "${grep_rc}" in
    0)
        exit 0
        ;;
    1)
        echo "expected pattern not found in ${target_file}: ${pattern}" >&2
        exit 1
        ;;
    *)
        echo "grep failed with rc=${grep_rc}" >&2
        exit 2
        ;;
esac
