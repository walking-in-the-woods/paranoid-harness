#!/usr/bin/env bash
# Проверяет, что в файле ровно одно вхождение заданной строки.
#
# Использование:
#   check-file-contains-once.sh <file> <literal-string>
#
# Exit 0 — ровно одно вхождение.
# Exit 1 — ноль или больше одного вхождений.
# Exit 2 — ошибка (файл отсутствует, grep сломался).
#
# Класс проверки "count==N": не должна молча проходить при
# ошибке grep'а. rc различается явно через case.
#
# ВАЖНО: grep -c считает СТРОКИ, а не вхождения. Если литерал
# появится дважды на одной строке, счёт будет 1. Для текущего
# применения (одна команда в отдельной строке) безопасно.

set -euo pipefail

if [[ "$#" -ne 2 ]]; then
    echo "usage: $0 <file> <literal-string>" >&2
    exit 2
fi

target_file="$1"
literal="$2"

if [[ ! -f "$target_file" ]]; then
    echo "file not found: $target_file" >&2
    exit 2
fi

set +e
occurrence_count=$(grep -Fc -- "$literal" "$target_file")
grep_rc=$?
set -e

case "$grep_rc" in
    0|1)
        # 0 — есть совпадения, 1 — нет. Оба нормальны.
        ;;
    *)
        echo "grep failed with rc=$grep_rc" >&2
        exit 2
        ;;
esac

occurrence_count="${occurrence_count:-0}"

if [[ "$occurrence_count" -ne 1 ]]; then
    echo "expected exactly 1 occurrence, found $occurrence_count: $literal" >&2
    exit 1
fi

exit 0
