#!/usr/bin/env bash
# Проверка паттерна для запрещённых имён файлов.
#
# Паттерн берётся из scripts/filename-pattern.env — единого
# источника для этого self-test'а.
#
# Negative и positive samples живут здесь, а не в ci.yml: иначе
# проверка ci.yml на запрещённый паттерн находила бы в нём самом
# эти примеры и всегда падала (self-reference).
#
# Чекеры вызываются через `bash "${checker}"`, а не как
# исполняемые файлы: локальный клон может быть без +x, и тогда
# прямой вызов упал бы. `bash` снимает зависимость от бита.
# Это второй барьер; первый — `chmod 0755 scripts/*.sh` в начале
# job'а CI.
#
# Запуск:  bash scripts/self-test-filename-pattern.sh
# Exit 0 — паттерн ведёт себя корректно и ci.yml чист.
# Exit 1 — паттерн сломан или ci.yml содержит запрещённый паттерн.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=filename-pattern.env
. "${script_dir}/filename-pattern.env"

if [[ -z "${forbidden_filenames_pattern:-}" ]]; then
    echo "FAIL: forbidden_filenames_pattern не определён после source" >&2
    exit 1
fi

check_matches="${script_dir}/check-file-matches-pattern.sh"
check_excludes="${script_dir}/check-file-excludes-pattern.sh"

for checker in "${check_matches}" "${check_excludes}"; do
    if [[ ! -f "${checker}" ]]; then
        echo "FAIL: missing: ${checker}" >&2
        exit 1
    fi
    if [[ ! -r "${checker}" ]]; then
        echo "FAIL: not readable: ${checker}" >&2
        exit 1
    fi
done

negative_input="$(mktemp)"
positive_input="$(mktemp)"
cleanup() {
    rm -f "${negative_input}" "${positive_input}"
}
trap cleanup EXIT

# --- Negative: паттерн должен сработать --------------------------------
cat > "${negative_input}" <<'NEGATIVE'
echo "FROM python:latest" > "$D/B"
cp "$D/A.yml" /tmp/worse
echo "lowercase bad" > "$E/b"
NEGATIVE

if ! bash "${check_matches}" "${negative_input}" \
        "${forbidden_filenames_pattern}"; then
    echo "FAIL: pattern does not match known-bad input" >&2
    echo "  pattern: ${forbidden_filenames_pattern}" >&2
    echo "  input:" >&2
    cat "${negative_input}" >&2
    exit 1
fi
echo "OK: pattern fires on '\$D/B', '\$D/A.yml', '\$E/b'"

# --- Positive: паттерн НЕ должен сработать -----------------------------
cat > "${positive_input}" <<'POSITIVE'
echo "FROM python:latest" > "$pin_test_dir/dockerfile-latest-tag"
cp "$pin_test_dir/compose-empty.yml" /tmp/ok
POSITIVE

if ! bash "${check_excludes}" "${positive_input}" \
        "${forbidden_filenames_pattern}"; then
    echo "FAIL: pattern matches descriptive filenames" >&2
    exit 1
fi
echo "OK: pattern ignores descriptive filenames"

# --- Реальный ci.yml не должен содержать запрещённых имён файлов ------
#
# Раньше эта проверка жила в CI-шаге «Verify no single-letter test
# filenames», но такой шаг вызывал self-test напрямую и попадал под
# собственный чекер check-workflow-uses-runner.py. Перенос сюда
# снимает само-ссылку: проверка запускается через
# scripts/run-self-tests.sh, как все остальные self-tests.
repo_root="$(cd "${script_dir}/.." && pwd)"
ci_yml="${repo_root}/.github/workflows/ci.yml"

if [[ ! -f "${ci_yml}" ]]; then
    echo "FAIL: ci.yml not found at ${ci_yml}" >&2
    exit 1
fi

if ! bash "${check_excludes}" "${ci_yml}" \
        "${forbidden_filenames_pattern}"; then
    echo "FAIL: .github/workflows/ci.yml contains forbidden filename pattern" >&2
    exit 1
fi
echo "OK: ci.yml has no forbidden filenames"

echo "[+] self-test for filename pattern passed"
