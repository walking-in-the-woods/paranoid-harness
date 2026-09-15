#!/usr/bin/env bash
# Проверка проекта: CI-проверки + unit-тесты.
#
# Использование:
#   bash scripts/verify-project.sh
#
# Exit 0 — все проверки прошли.
# Exit 1 — хотя бы одна не прошла.
#
# Секции 1–8, 10 — CI-проверки и unit-тесты, воспроизводимые локально.
# Секция 5 — spot-check символов gateway.py (наличие, не поведение).
# Секция 6 — поведенческая проверка symlink-логики через pytest.
# Секция 9 — self-test chmod: проверяет, что chmod +x / -x срабатывает.
# Секция 10 — unit-тесты (поведение).
# Docker smoke (gateway-tls) требует docker; здесь не запускается.

set -euo pipefail

cd "$(dirname "$0")/.."

# ============================================================================
# Сохраняем исходные режимы scripts/*.{sh,py} ДО первого chmod.
#
# Смысл: chmod в начале скрипта (см. ниже) нормализует режимы к 0755 —
# это нужно, чтобы scripts/check-file-excludes-pattern.sh вызывался
# как исполняемый уже в секции 1. Но после прогона хочется вернуть
# рабочую копию в то состояние, в котором пользователь её оставил,
# чтобы git status не показывал изменений, которых не делал пользователь.
#
# Восстановление — через trap EXIT: сработает и при нормальном
# завершении, и при падении любой секции.
# ============================================================================
declare -A ORIGINAL_MODES=()

restore_original_modes() {
    local script_file
    # Guard от пустого массива под set -u на bash <= 4.3:
    # "${!ORIGINAL_MODES[@]}" на пустом assoc-массиве падает.
    # "${#ORIGINAL_MODES[@]}" возвращает 0 без ошибки — это
    # документированное поведение.
    if [[ "${#ORIGINAL_MODES[@]}" -eq 0 ]]; then
        return 0
    fi
    for script_file in "${!ORIGINAL_MODES[@]}"; do
        if [[ -e "${script_file}" ]]; then
            chmod "${ORIGINAL_MODES[${script_file}]}" \
                  "${script_file}" 2>/dev/null || true
        fi
    done
}

trap restore_original_modes EXIT

while IFS= read -r script_file; do
    ORIGINAL_MODES["${script_file}"]=$(stat -c '%a' "${script_file}")
done < <(find scripts -maxdepth 1 -type f \
         \( -name '*.sh' -o -name '*.py' \) | sort)

# ============================================================================
# Ensure scripts are executable — аналог CI-шага "Ensure scripts are
# executable". Нужен до секции 1: scripts/check-file-excludes-pattern.sh
# вызывается как исполняемый файл. Исходные режимы восстановятся на
# выходе через trap (см. выше).
# ============================================================================
chmod 0755 scripts/*.sh scripts/*.py

# ============================================================================
# Предварительная проверка зависимостей.
# ============================================================================
if ! python3 -c "import pytest" >/dev/null 2>&1; then
    echo "FAIL: pytest не установлен." >&2
    echo "  Установить: pip install -r requirements-dev.txt" >&2
    exit 1
fi

if ! python3 -c "import yaml" >/dev/null 2>&1; then
    echo "FAIL: PyYAML не установлен." >&2
    echo "  Установить: pip install pyyaml" >&2
    exit 1
fi

# ============================================================================
# Секция 1. ci.yml не содержит запрещённого паттерна имён.
# ============================================================================
echo "=== [1/10] ci.yml has no forbidden filename pattern ==="
# shellcheck disable=SC1091
. scripts/filename-pattern.env

if [[ -z "${forbidden_filenames_pattern:-}" ]]; then
    echo "FAIL: forbidden_filenames_pattern не определён" >&2
    exit 1
fi

bash scripts/check-file-excludes-pattern.sh \
    .github/workflows/ci.yml \
    "${forbidden_filenames_pattern}"
echo "[+] OK"

# ============================================================================
# Секция 2. CI workflow использует runner для self-tests и не содержит
# прямых вызовов scripts/self-test-*.sh.
#
# Раньше секция проверяла конкретный шаг "Verify no single-letter test
# filenames" (внутреннюю реализацию). Шаг удалён: проверка перенесена
# в self-test-filename-pattern.sh и запускается через run-self-tests.sh.
# Теперь секция проверяет инвариант на уровне workflow — то же, что
# делает CI-шаг "Verify CI uses runner".
# ============================================================================
echo "=== [2/10] CI workflow uses runner, no direct self-test calls ==="
python3 scripts/check-workflow-uses-runner.py \
    .github/workflows/ci.yml
echo "[+] OK"

# ============================================================================
# Секция 3. self-test-filename-pattern.sh вызывает чекеры через bash.
# ============================================================================
echo "=== [3/10] self-test-filename-pattern uses bash for checkers ==="
grep -Fq 'bash "${check_matches}"' \
    scripts/self-test-filename-pattern.sh \
    || { echo "FAIL: check_matches не через bash" >&2; exit 1; }
grep -Fq 'bash "${check_excludes}"' \
    scripts/self-test-filename-pattern.sh \
    || { echo "FAIL: check_excludes не через bash" >&2; exit 1; }
echo "[+] OK"

# ============================================================================
# Секция 4. -f и -r в self-tests проверяются раздельно.
# ============================================================================
echo "=== [4/10] self-tests distinguish missing / not-readable ==="
grep -Fq '[[ ! -f "${checker}" ]]' \
    scripts/self-test-filename-pattern.sh \
    || { echo "FAIL: нет проверки -f в self-test-filename-pattern" >&2;
         exit 1; }
grep -Fq '[[ ! -r "${checker}" ]]' \
    scripts/self-test-filename-pattern.sh \
    || { echo "FAIL: нет проверки -r в self-test-filename-pattern" >&2;
         exit 1; }
echo "[+] OK"

# ============================================================================
# Секция 5. Spot-check: gateway.py содержит ключевые символы.
# Наличие — не поведение. Поведение — в секции 10 (unit-тесты).
# ============================================================================
echo "=== [5/10] gateway.py symbols (spot-check, not behavior) ==="
for needle in \
    'class ServerCertPolicy' \
    'def _prompt_hash_entries' \
    'def _purge_stale' \
    'GATEWAY_SERVER_SAN' \
    'def _try_client_ip' \
    'def _strip_all_tool_fields' \
    'def _apply_profile_chat' \
    'def _apply_profile_generate'; do
    if ! grep -Fq "${needle}" model_gateway/gateway.py; then
        echo "FAIL: gateway.py не содержит ${needle}" >&2
        exit 1
    fi
done
echo "[+] OK"

# ============================================================================
# Секция 6. symlink-логика — поведенческая проверка через pytest.
# Явные node ID: подстрока `-k symlink` могла бы подхватить будущие
# нерелевантные тесты с этим словом в имени.
# ============================================================================
echo "=== [6/10] symlink behavior via pytest ==="
python3 -m pytest \
    tests/test_server_cert_check.py::test_symlink_required_rejects \
    tests/test_server_cert_check.py::test_symlink_dev_mode_warns \
    tests/test_server_cert_check.py::test_symlink_to_directory_required_raises \
    tests/test_server_cert_check.py::test_dangling_symlink_required_raises \
    -q \
    || { echo "FAIL: symlink tests" >&2; exit 1; }
echo "[+] OK"

# ============================================================================
# Секция 7. import re на уровне модуля (не локальный).
# ============================================================================
echo "=== [7/10] import re at module level ==="
python3 <<'PY'
import ast
import sys

with open('model_gateway/cert_verify.py') as stream:
    tree = ast.parse(stream.read())

target = None
for node in ast.iter_child_nodes(tree):
    if isinstance(node, ast.FunctionDef) and node.name == '_valid_san_name':
        target = node
        break

if target is None:
    print('FAIL: _valid_san_name не найдена на верхнем уровне',
          file=sys.stderr)
    sys.exit(1)

for child in ast.walk(target):
    if isinstance(child, (ast.Import, ast.ImportFrom)):
        print('FAIL: локальный import внутри _valid_san_name',
              file=sys.stderr)
        sys.exit(1)

for node in tree.body:
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == 're':
                print('[+] OK')
                sys.exit(0)

print('FAIL: import re не найден на уровне модуля', file=sys.stderr)
sys.exit(1)
PY

# ============================================================================
# Секция 8. Все self-tests проекта.
# ============================================================================
echo "=== [8/10] all self-tests ==="
bash scripts/run-self-tests.sh

# ============================================================================
# Секция 9. self-test chmod: chmod 0644 снимает +x, chmod 0755 ставит.
#
# Восстановление исходных режимов scripts/*.{sh,py} делает trap в
# начале скрипта, а не эта секция. Здесь — только проверка, что
# chmod сам по себе работает. Репозиторий не трогаем: файл создан
# через mktemp в /tmp.
# ============================================================================
echo "=== [9/10] chmod +x / -x works ==="
chmod_test_file="$(mktemp)"
chmod 0644 "${chmod_test_file}"
if [[ -x "${chmod_test_file}" ]]; then
    echo "FAIL: chmod 0644 не снимает +x" >&2
    rm -f "${chmod_test_file}"
    exit 1
fi
chmod 0755 "${chmod_test_file}"
if [[ ! -x "${chmod_test_file}" ]]; then
    echo "FAIL: chmod 0755 не ставит +x" >&2
    rm -f "${chmod_test_file}"
    exit 1
fi
rm -f "${chmod_test_file}"
echo "[+] OK"

# ============================================================================
# Секция 10. Unit-тесты (tests/).
#
# Перед прогоном печатаем количество собранных тестов — чтобы число
# в выводе можно было сверить с содержимым tests/.
#
# `--collect-only -q` завершается строкой вида
# "N tests collected in Ts" — это последняя строка вывода.
# tail -1 достаточно.
# ============================================================================
echo "=== [10/10] unit tests (pytest tests/ --ignore=tests/smoke) ==="
echo "--- collected: ---"
python3 -m pytest tests/ \
    --ignore=tests/smoke \
    --collect-only -q | tail -1
echo "--- running: ---"
python3 -m pytest tests/ --ignore=tests/smoke -q

echo
echo "[+] All checks passed."
