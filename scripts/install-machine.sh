#!/usr/bin/env bash
# install-machine.sh — идемпотентная установка Docker и uv.
#
# ════════════════════════════════════════════════════════════════════════════
# ЧТО ДЕЛАЕТ ЭТОТ СКРИПТ
# ════════════════════════════════════════════════════════════════════════════
#
# Проверяет:
#   * docker — версия >= 24
#   * docker compose plugin — наличие
#   * uv — версия >= REQUIRED_UV_VERSION (sort -V, не откатывает новые)
#   * fingerprint GPG-ключа Docker — всегда (даже если Docker уже стоит)
#
# Проверка целостности:
#   * Docker GPG: fingerprint сверяется с официальным
#     (9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88).
#     GnuPG печатает fingerprint с декоративным двойным пробелом
#     между 4-й и 5-й группами; эталон выше тоже содержит двойной.
#     tr -s ' ' схлопывает пробелы в обоих — сравнение устойчиво
#     к обоим вариантам форматирования.
#   * uv: sha256sum -c для tarball из того же GitHub release.
#
# Временные файлы создаются через mktemp — защита от symlink-атаки
# в /tmp на многопользовательских машинах.
#
# Файловую структуру проекта НЕ создаёт — это делает setup.sh.
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

REQUIRED_DOCKER_MAJOR=24
REQUIRED_UV_VERSION="0.12.12"
# GnuPG печатает с двойным пробелом между 4-й и 5-й группами.
DOCKER_GPG_FINGERPRINT="9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88"
# Нормализованная форма для grep (одиночные пробелы).
DOCKER_GPG_FINGERPRINT_NORM="9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88"

TMPFILES=()
cleanup_tmp() {
  for f in "${TMPFILES[@]:-}"; do
    [[ -n "$f" ]] && rm -rf "$f"
  done
}
trap cleanup_tmp EXIT

mktmp() {
  local f
  f="$(mktemp)"
  TMPFILES+=("$f")
  echo "$f"
}

# --- 1. Проверка fingerprint GPG всегда -------------------------------------
# Даже если Docker не ставим — убеждаемся, что ключ в keyring тот самый.
#
# ВАЖНО: это осознанное отступление от fail-closed. Если Docker уже
# установлен и работает, а fingerprint ключа в keyring не совпал —
# мы предупреждаем и спрашиваем, но не падаем автоматически. Причина:
# Docker мог быть поставлен ранее другим способом (например, из
# зеркала корпоративного реестра с собственным ключом). Молчаливый
# отказ сломал бы работающую установку. Пользователь должен явно
# подтвердить, что готов продолжать.
#
# В отличие от установки Docker (шаг 2) — там проверка fail-closed,
# потому что ключ скачивается прямо сейчас из официального источника.
if [[ -f /etc/apt/keyrings/docker.gpg ]]; then
  if ! command -v gpg >/dev/null 2>&1; then
    echo "[i] gpg не установлен — проверка существующего ключа пропущена." >&2
    echo "    Если Docker уже работает, это не критично." >&2
  else
    echo "[*] Verifying existing Docker GPG key..."
    if ! gpg --show-keys --with-fingerprint /etc/apt/keyrings/docker.gpg 2>/dev/null \
         | tr -s ' ' \
         | grep -q "$DOCKER_GPG_FINGERPRINT_NORM"; then
      echo "[!] ВНИМАНИЕ: fingerprint Docker GPG в /etc/apt/keyrings/docker.gpg" >&2
      echo "    не совпадает с официальным:" >&2
      echo "    $DOCKER_GPG_FINGERPRINT" >&2
      echo "    Продолжение работы с этим ключом может быть небезопасно." >&2
      echo "    Если Docker установлен не из официального репозитория," >&2
      echo "    рассмотрите переустановку." >&2
      read -rp "Продолжить? [y/N] " ans
      [[ "$ans" == "y" ]] || exit 1
    else
      echo "[+] Fingerprint Docker GPG в keyring совпал."
    fi
  fi
fi

# --- 2. Docker --------------------------------------------------------------
need_install_docker=1

if command -v docker >/dev/null 2>&1; then
  current=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
  current_major=$(echo "$current" | cut -d. -f1)
  if [[ "$current_major" =~ ^[0-9]+$ ]] && (( current_major >= REQUIRED_DOCKER_MAJOR )); then
    echo "[+] Docker: $current"
    need_install_docker=0
  else
    echo "[i] Docker $current < $REQUIRED_DOCKER_MAJOR — будет обновлён."
  fi
fi

# docker compose plugin проверяется независимо от docker core.
if [[ "$need_install_docker" -eq 0 ]] && ! docker compose version >/dev/null 2>&1; then
  echo "[i] docker compose plugin отсутствует — будет установлен."
  need_install_docker=1
fi

if [[ "$need_install_docker" -eq 1 ]]; then
  echo "[*] Installing/updating Docker..."
  sudo apt update
  sudo apt install -y ca-certificates curl gnupg

  gpg_tmp="$(mktmp)"
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$gpg_tmp"

  if ! gpg --show-keys --with-fingerprint "$gpg_tmp" 2>/dev/null \
       | tr -s ' ' \
       | grep -q "$DOCKER_GPG_FINGERPRINT_NORM"; then
    echo "[!] Fingerprint GPG Docker не совпал с официальным:" >&2
    echo "    $DOCKER_GPG_FINGERPRINT" >&2
    echo "    Установка прервана." >&2
    exit 1
  fi
  echo "[+] Fingerprint GPG Docker совпал."

  sudo install -m 0755 -d /etc/apt/keyrings
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg < "$gpg_tmp"
  sudo chmod a+r /etc/apt/keyrings/docker.gpg

  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt update
  sudo apt install -y docker-ce docker-ce-cli containerd.io \
                      docker-buildx-plugin docker-compose-plugin
fi

echo "[+] Docker: $(docker --version)"
docker compose version

# --- 3. uv (пиннинг версии + SHA256) -----------------------------------------
installed_uv=""
if [[ -x "$HOME/.local/bin/uv" ]]; then
  installed_uv=$("$HOME/.local/bin/uv" --version 2>/dev/null \
                 | awk '{print $2}' \
                 | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || true)
elif command -v uv >/dev/null 2>&1; then
  installed_uv=$(uv --version 2>/dev/null \
                 | awk '{print $2}' \
                 | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || true)
fi

if [[ -n "$installed_uv" ]]; then
  # sort -V — version sort. Если REQUIRED <= installed, значит текущая
  # не старше требуемой → оставляем.
  newer_or_equal=$(printf '%s\n%s\n' "$REQUIRED_UV_VERSION" "$installed_uv" \
                   | sort -V | tail -n1)
  if [[ "$newer_or_equal" == "$installed_uv" ]]; then
    echo "[+] uv уже установлен: $installed_uv (>= $REQUIRED_UV_VERSION)"
    export PATH="$HOME/.local/bin:$PATH"
    if ! grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
      echo "[+] ~/.local/bin добавлен в PATH в ~/.bashrc"
    fi
    echo "[+] Machine setup complete. source ~/.bashrc"
    exit 0
  fi
  echo "[i] uv $installed_uv < $REQUIRED_UV_VERSION — будет обновлён."
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  UV_ASSET="uv-x86_64-unknown-linux-gnu.tar.gz" ;;
  aarch64) UV_ASSET="uv-aarch64-unknown-linux-gnu.tar.gz" ;;
  *) echo "[!] Unsupported arch: $ARCH" >&2; exit 1 ;;
esac
BASE="https://github.com/astral-sh/uv/releases/download/${REQUIRED_UV_VERSION}"

mkdir -p "$HOME/.local/bin"

uv_dir="$(mktemp -d)"
TMPFILES+=("$uv_dir")

curl -fsSL "${BASE}/${UV_ASSET}" -o "${uv_dir}/${UV_ASSET}"
curl -fsSL "${BASE}/${UV_ASSET}.sha256" -o "${uv_dir}/${UV_ASSET}.sha256"

(cd "$uv_dir" && sha256sum -c "${UV_ASSET}.sha256")
tar -xzf "${uv_dir}/${UV_ASSET}" -C "$uv_dir"
install -m 0755 "${uv_dir}/${UV_ASSET%.tar.gz}/uv" "$HOME/.local/bin/uv"

export PATH="$HOME/.local/bin:$PATH"
echo "[+] uv: $(uv --version)"

if ! grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  echo "[+] ~/.local/bin добавлен в PATH"
fi

echo
echo "[+] Machine setup complete. Откройте новый терминал или выполните: source ~/.bashrc"
