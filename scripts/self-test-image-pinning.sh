#!/usr/bin/env bash
# Self-test для check-image-pinning.py.
#
# Сценарии: unpinned tags, :latest, placeholder, --platform +
# multi-stage, compose (пусто, unpinned, latest, не-mapping,
# env-var).
#
# Работает в изолированном временном каталоге, cwd не трогает.
# Чекер вызывается через `python3`, не как исполняемый файл.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
checker="${script_dir}/check-image-pinning.py"

if [[ ! -f "${checker}" ]]; then
    echo "FAIL: missing: ${checker}" >&2
    exit 1
fi
if [[ ! -r "${checker}" ]]; then
    echo "FAIL: not readable: ${checker}" >&2
    exit 1
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

run_checker() {
    local output_file="$1"
    shift
    set +e
    python3 "${checker}" "$@" > "${output_file}" 2>&1
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

expect_summary() {
    local scenario="$1" expected_regex="$2" output_file="$3"
    if ! grep -qE "${expected_regex}" "${output_file}"; then
        echo "FAIL: ${scenario} — вывод не соответствует ${expected_regex}" >&2
        cat "${output_file}" >&2
        exit 1
    fi
    echo "OK: ${scenario}"
}

output_file="${work_dir}/output.txt"

# --- Dockerfile-кейсы --------------------------------------------------
cat > "${work_dir}/dockerfile-unpinned-tags" <<'DOCKERFILE'
FROM python:3.12.7-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/
FROM python:3.12.7-slim AS runtime
COPY --from=runtime /app /app
DOCKERFILE

expect_rc "dockerfile-unpinned-tags" 0 \
    "$(run_checker "${output_file}" "${work_dir}/dockerfile-unpinned-tags")"
expect_summary "dockerfile-unpinned-tags summary" \
    '^image-pinning: 0 error\(s\), 3 warning\(s\)$' "${output_file}"

expect_rc "dockerfile-unpinned-tags --strict" 1 \
    "$(run_checker "${output_file}" --strict \
        "${work_dir}/dockerfile-unpinned-tags")"

echo "FROM python:latest" > "${work_dir}/dockerfile-latest-tag"
expect_rc "dockerfile-latest-tag" 1 \
    "$(run_checker "${output_file}" "${work_dir}/dockerfile-latest-tag")"
expect_summary "dockerfile-latest-tag summary" \
    '^image-pinning: 1 error\(s\), 0 warning\(s\)$' "${output_file}"

echo "FROM python:3.12.7-slim@REPLACE_WITH_PINNED_DIGEST" \
    > "${work_dir}/dockerfile-placeholder"
expect_rc "dockerfile-placeholder" 1 \
    "$(run_checker "${output_file}" "${work_dir}/dockerfile-placeholder")"

cat > "${work_dir}/dockerfile-platform-multistage" <<'DOCKERFILE'
FROM --platform=linux/amd64 python:3.12.7-slim AS builder
FROM --platform=linux/amd64 python:3.12.7-slim
COPY --from=builder /app /app
DOCKERFILE
expect_rc "dockerfile-platform-multistage" 0 \
    "$(run_checker "${output_file}" \
        "${work_dir}/dockerfile-platform-multistage")"
expect_summary "dockerfile-platform-multistage summary" \
    '^image-pinning: 0 error\(s\), 2 warning\(s\)$' "${output_file}"

# --- Compose-кейсы -----------------------------------------------------
echo "# Empty compose" > "${work_dir}/compose-empty.yml"
expect_rc "compose-empty" 0 \
    "$(run_checker "${output_file}" "${work_dir}/compose-empty.yml")"

echo "services: {}" > "${work_dir}/compose-empty-services.yml"
expect_rc "compose-empty-services" 0 \
    "$(run_checker "${output_file}" \
        "${work_dir}/compose-empty-services.yml")"

cat > "${work_dir}/compose-unpinned-image.yml" <<'YAML'
services:
  demo:
    image: "python:3.12.7-slim"
YAML
expect_rc "compose-unpinned-image" 0 \
    "$(run_checker "${output_file}" \
        "${work_dir}/compose-unpinned-image.yml")"
expect_summary "compose-unpinned-image summary" \
    '^image-pinning: 0 error\(s\), 1 warning\(s\)$' "${output_file}"

cat > "${work_dir}/compose-latest-tag.yml" <<'YAML'
services:
  demo:
    image: "python:latest"
YAML
expect_rc "compose-latest-tag" 1 \
    "$(run_checker "${output_file}" \
        "${work_dir}/compose-latest-tag.yml")"

echo 'services: "not a mapping"' \
    > "${work_dir}/compose-services-not-mapping.yml"
expect_rc "compose-services-not-mapping" 1 \
    "$(run_checker "${output_file}" \
        "${work_dir}/compose-services-not-mapping.yml")"
expect_summary "compose-services-not-mapping summary" \
    'services.*must be a mapping' "${output_file}"

cat > "${work_dir}/compose-top-level-not-mapping.yml" <<'YAML'
- foo
- bar
YAML
expect_rc "compose-top-level-not-mapping" 1 \
    "$(run_checker "${output_file}" \
        "${work_dir}/compose-top-level-not-mapping.yml")"
expect_summary "compose-top-level-not-mapping summary" \
    'top-level must be a mapping' "${output_file}"

cat > "${work_dir}/compose-env-var-image.yml" <<'YAML'
services:
  demo:
    image: "${DEMO_IMAGE:?set it}"
YAML
expect_rc "compose-env-var-image" 0 \
    "$(run_checker "${output_file}" \
        "${work_dir}/compose-env-var-image.yml")"
expect_summary "compose-env-var-image summary" \
    '^image-pinning: 0 error\(s\), 1 warning\(s\)$' "${output_file}"

echo "[+] self-test для check-image-pinning.py passed"
