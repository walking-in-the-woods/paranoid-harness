#!/usr/bin/env bash
# Генерация CA и клиентских сертификатов для mTLS-гейтвея.
#
# CN сертификата = имя клиента из gateway_clients.yaml (поле name).
#
# Клиентские сертификаты:
#   SAN DNS.1 = <name> (critical).
#   EKU       = clientAuth (critical).
#   KU        = digitalSignature (critical), без keyCertSign/crlSign.
#   BC        = CA:FALSE (critical).
#
# Server-сертификат: та же политика criticality, EKU=serverAuth.
#
# Использование:
#   bash scripts/gateway-certs.sh certs <client> [<client> ...]
#
# Если клиенты не указаны — генерируются сертификаты для клиентов по
# умолчанию (harness, webui). Дополнительные клиенты передаются
# аргументами и должны быть объявлены в config/gateway_clients.yaml.
#
# Права:
#   * ca.crt, *.crt:  0644 (публичные).
#   * ca.key:         0600 (перенести offline после setup).
#   * server.key:     0640 (root:root; nginx master = root).
#   * <client>.key:   0600 (клиент читает только свой файл — через
#                     bind-mount одного файла в compose).
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-certs}"
shift || true
CLIENTS=("$@")
if [[ ${#CLIENTS[@]} -eq 0 ]]; then
    CLIENTS=(harness webui)
fi

mkdir -p "$OUT"
chmod 0755 "$OUT"

if [[ ! -f "$OUT/ca.key" ]]; then
    echo "[*] Generating CA..."
    openssl genrsa -out "$OUT/ca.key" 4096
    openssl req -x509 -new -nodes -key "$OUT/ca.key" -sha256 -days 3650 \
        -subj "/CN=paranoid-harness-ca" \
        -out "$OUT/ca.crt" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign"
    chmod 0600 "$OUT/ca.key"
    chmod 0644 "$OUT/ca.crt"
fi

if [[ ! -f "$OUT/server.key" ]]; then
    echo "[*] Generating server cert..."
    openssl genrsa -out "$OUT/server.key" 4096
    openssl req -new -key "$OUT/server.key" \
        -subj "/CN=gateway-tls" \
        -out "$OUT/server.csr"
    # Все расширения critical — та же политика, что для client.
    cat > "$OUT/server.ext" <<'EXT'
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = critical,serverAuth
subjectAltName = critical,@alt
[alt]
DNS.1 = gateway-tls
DNS.2 = localhost
IP.1 = 127.0.0.1
EXT
    openssl x509 -req -in "$OUT/server.csr" \
        -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" -CAcreateserial \
        -days 825 -sha256 -extfile "$OUT/server.ext" \
        -out "$OUT/server.crt"
    rm -f "$OUT/server.csr" "$OUT/server.ext"
    chmod 0644 "$OUT/server.crt"
    chmod 0640 "$OUT/server.key"
fi

for c in "${CLIENTS[@]}"; do
    if [[ ! "$c" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
        echo "[!] invalid client name: $c" >&2
        exit 1
    fi
    if [[ -f "$OUT/$c.key" ]]; then
        echo "[=] $c already exists, skipping."
        continue
    fi
    echo "[*] Generating client cert: $c"
    openssl genrsa -out "$OUT/$c.key" 4096
    openssl req -new -key "$OUT/$c.key" \
        -subj "/CN=$c" \
        -out "$OUT/$c.csr"
    cat > "$OUT/$c.ext" <<EXT
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,clientAuth
subjectAltName = critical,@alt
[alt]
DNS.1 = $c
EXT
    openssl x509 -req -in "$OUT/$c.csr" \
        -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" -CAcreateserial \
        -days 825 -sha256 -extfile "$OUT/$c.ext" \
        -out "$OUT/$c.crt"
    rm -f "$OUT/$c.csr" "$OUT/$c.ext"
    chmod 0644 "$OUT/$c.crt"
    chmod 0600 "$OUT/$c.key"

    # Fail-closed: ровно один DNS-SAN, равный имени клиента.
    # grep -oE извлекает каждое совпадение на отдельной строке;
    # если их больше одного, "$names" будет содержать \n и не
    # совпадёт с $c. Подстрочное `DNS:harness-prod` тоже не
    # совпадёт — сравнение по полной строке.
    san_out=$(openssl x509 -in "$OUT/$c.crt" -noout -ext subjectAltName)
    names=$(printf '%s\n' "$san_out" \
        | grep -oE 'DNS:[[:space:]]*[^,[:space:]]+' \
        | sed 's/DNS:[[:space:]]*//')
    if [[ "$names" != "$c" ]]; then
        echo "[!] SAN mismatch in $c.crt" >&2
        echo "    got:  $names" >&2
        echo "    want: $c" >&2
        rm -f "$OUT/$c.crt" "$OUT/$c.key"
        exit 1
    fi
done

echo
echo "[+] Done."
echo "    Перенесите ca.key в offline-хранилище — он нужен только"
echo "    для выдачи новых сертификатов, но не для работы системы."
