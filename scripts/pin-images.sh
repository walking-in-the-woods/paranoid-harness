#!/usr/bin/env bash
# Пиннинг базовых образов по digest.
#
#   bash scripts/pin-images.sh           — печатает пары image -> digest
#   bash scripts/pin-images.sh --update  — заменяет в Dockerfile
#
# Идемпотентен: повторный запуск не дублирует @sha256:.
#
# Не поддерживает BSD sed (macOS): используется `sed -i
# --follow-symlinks`. Для macOS — Linux-контейнер или Linux-VM.
set -euo pipefail
cd "$(dirname "$0")/.."

UPDATE=0
[[ "${1:-}" == "--update" ]] && UPDATE=1

DOCKERFILES=(
    model_gateway/Dockerfile
    gateway_tls/Dockerfile
    api_proxy/Dockerfile
    harness/Dockerfile
)

IMAGES=(
    "python:3.12.7-slim"
    "ghcr.io/astral-sh/uv:0.5.11"
    "nginx:1.27.2-alpine"
)

# Замена <image> на <image>@sha256:<hex> в FROM и COPY --from=.
# * ^(FROM|COPY --from=) — только инструкция, не комментарий.
# * Точки в имени экранируются (\\.) — иначе `.` матчит любой символ.
# * Идемпотентно: если уже @sha256: — образ в строке не совпадёт.
pin_in_dockerfile() {
    local img="$1" hash="$2"
    local img_escaped
    img_escaped=$(printf '%s' "$img" | sed 's/\./\\./g')
    local f
    for f in "${DOCKERFILES[@]}"; do
        [[ -f "$f" ]] || continue
        if grep -qE "^(FROM[[:space:]]+|COPY --from=)${img_escaped}([[:space:]]|\$)" "$f"; then
            sed -i --follow-symlinks -E \
                "s|^(FROM[[:space:]]+|COPY --from=)${img_escaped}([[:space:]]|\$)|\\1${img}@${hash}\\2|g" \
                "$f"
        fi
    done
}

for img in "${IMAGES[@]}"; do
    docker pull "$img" >/dev/null
    digest_full=$(docker inspect --format='{{index .RepoDigests 0}}' "$img")
    # digest_full = "<img>@sha256:<hex>"; берём часть после @.
    hash="${digest_full##*@}"
    echo "$img -> $digest_full"
    if [[ "$UPDATE" -eq 1 ]]; then
        pin_in_dockerfile "$img" "$hash"
    fi
done

if [[ "$UPDATE" -eq 1 ]]; then
    echo
    echo "[+] Dockerfiles обновлены. Проверьте git diff и закоммитьте."
fi
