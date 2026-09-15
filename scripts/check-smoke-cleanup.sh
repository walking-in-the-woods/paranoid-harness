#!/usr/bin/env bash
# Проверяет отсутствие временных артефактов smoke-теста в каталоге.
#
# Использование:
#   ./scripts/check-smoke-cleanup.sh [base_directory]
#
# base_directory по умолчанию — текущий каталог.
#
# Exit 0 — артефактов нет.
# Exit 1 — обнаружен артефакт; печатает его.
#
# Список артефактов — единственный источник. Используется:
#   - CI-шагом "Verify smoke cleanup" (base_directory = .)
#   - scripts/self-test-smoke-cleanup.sh (base_directory = tmp)

set -euo pipefail

base_directory="${1:-.}"

smoke_artifacts=(
    "certs-smoke"
    "docker-compose.smoke.yml"
)

for artifact in "${smoke_artifacts[@]}"; do
    artifact_path="${base_directory}/${artifact}"
    if [[ -e "${artifact_path}" ]]; then
        echo "smoke left artifact behind: ${artifact_path}" >&2
        ls -la "${artifact_path}" >&2
        exit 1
    fi
done

echo "no smoke artifacts in ${base_directory}"
