#!/usr/bin/env bash
# Проверяет отсутствие паттерна в файле.
#
# Использование:
#   check-file-excludes-pattern.sh <file> <extended-regex>
#
# Exit 0 — паттерн не найден.
# Exit 1 — паттерн найден (нарушение гигиены).
# Exit 2 — файл отсутствует или grep завершился с ошибкой.
#
# Класс "grep pattern, silently passing on error": файл проверяется
# до вызова grep, rc различается явно через case.

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
matches=$(grep -nE -- "${pattern}" "${target_file}")
grep_rc=$?
set -e

case "${grep_rc}" in
    0)
        echo "forbidden pattern found in ${target_file}:" >&2
        echo "${matches}" >&2
        exit 1
        ;;
    1)
        exit 0
        ;;
    *)
        echo "grep failed with rc=${grep_rc}" >&2
        exit 2
        ;;
esac
