"""
Верификация клиентских сертификатов и проверка server.crt.

Проверки client-сертификата (RFC 5280 + RFC 6125):
  * подпись CA над tbs_certificate_bytes;
  * срок действия (обе границы);
  * BasicConstraints critical CA:FALSE;
  * KeyUsage critical digitalSignature, без keyCertSign/crlSign;
  * ExtendedKeyUsage critical clientAuth;
  * SignatureAlgorithm SHA-256/384/512;
  * SAN critical, ровно один DNS = имя клиента.

Проверки server.crt (симметричная политика, EKU=serverAuth):
  * файл — обычный (не symlink при required=True);
  * срок действия (обе границы);
  * BasicConstraints / KeyUsage / EKU / SAN — critical;
  * EKU содержит serverAuth;
  * SAN содержит required_san;
  * SAN DNS ⊆ {required_san} ∪ allowed_extra_sans;
  * SAN IP ⊆ allowed_ips.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa


log = logging.getLogger("cert_verify")

_ALLOWED_SIG_HASHES = frozenset({"sha256", "sha384", "sha512"})

# Единый именованный regex для проверки SAN-имени. Компилируется
# один раз; используется и в _valid_san_name, и потенциально в
# тестах. Перфоманс здесь не критичен — вызов происходит раз на
# запрос. Главное — держать паттерн в одной точке, чтобы правило
# "[A-Za-z0-9._-], 1..64" нельзя было случайно разойтись между
# модулями.
_SAN_NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def _valid_san_name(name: str) -> bool:
    return bool(_SAN_NAME_RE.fullmatch(name))


class CertVerifier:
    """Проверка client-сертификата по подписи CA + EKU/KU/BC/SAN."""

    def __init__(self, ca_path: Path, warn_days: int = 30):
        with ca_path.open("rb") as f:
            self.ca = x509.load_pem_x509_certificate(f.read())
        self.warn_days = warn_days
        self._check_ca_sanity()
        self._warn_ca_expiry()

    def _check_ca_sanity(self) -> None:
        try:
            bc = self.ca.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            if not bc.critical:
                raise RuntimeError(
                    "CA cert BasicConstraints must be critical"
                )
            if not bc.value.ca:
                raise RuntimeError(
                    "CA cert BasicConstraints must be CA:TRUE"
                )
        except x509.ExtensionNotFound:
            raise RuntimeError("CA cert missing BasicConstraints")

        try:
            ku = self.ca.extensions.get_extension_for_class(x509.KeyUsage)
            if not ku.critical or not ku.value.key_cert_sign:
                raise RuntimeError(
                    "CA cert KeyUsage must be critical keyCertSign"
                )
        except x509.ExtensionNotFound:
            raise RuntimeError("CA cert missing KeyUsage")

        hash_alg = self.ca.signature_hash_algorithm
        if hash_alg is None or hash_alg.name not in _ALLOWED_SIG_HASHES:
            raise RuntimeError(
                f"CA signature hash not allowed: "
                f"{hash_alg.name if hash_alg else 'unknown'}"
            )

    def _warn_ca_expiry(self) -> None:
        now = datetime.now(timezone.utc)
        days_left = (self.ca.not_valid_after_utc - now).days
        if days_left < 0:
            raise RuntimeError(
                f"CA certificate expired {abs(days_left)} days ago"
            )
        if days_left < self.warn_days:
            log.warning("CA certificate expires in %d days", days_left)

    def verify(self, escaped_pem: str) -> str | None:
        now = datetime.now(timezone.utc)
        if not (self.ca.not_valid_before_utc
                <= now
                <= self.ca.not_valid_after_utc):
            return None

        if not escaped_pem:
            return None

        try:
            pem = urllib.parse.unquote(escaped_pem)
            cert = x509.load_pem_x509_certificate(pem.encode("ascii"))
        except Exception:
            return None

        if not (cert.not_valid_before_utc
                <= now
                <= cert.not_valid_after_utc):
            return None

        hash_alg = cert.signature_hash_algorithm
        if hash_alg is None or hash_alg.name not in _ALLOWED_SIG_HASHES:
            return None

        try:
            bc = cert.extensions.get_extension_for_class(
                x509.BasicConstraints
            )
            if not bc.critical or bc.value.ca:
                return None
        except x509.ExtensionNotFound:
            return None

        try:
            ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
            if not ku.critical:
                return None
            if not ku.value.digital_signature:
                return None
            if ku.value.key_cert_sign or ku.value.crl_sign:
                return None
        except x509.ExtensionNotFound:
            return None

        try:
            eku = cert.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            )
            if not eku.critical:
                return None
            if x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH not in eku.value:
                return None
        except x509.ExtensionNotFound:
            return None

        try:
            san = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            if not san.critical:
                return None
            dns_names = san.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            return None
        if len(dns_names) != 1:
            return None
        san_name = dns_names[0]
        if not isinstance(san_name, str):
            return None
        if not _valid_san_name(san_name):
            return None

        ca_pub = self.ca.public_key()
        try:
            if isinstance(ca_pub, rsa.RSAPublicKey):
                ca_pub.verify(
                    cert.signature,
                    cert.tbs_certificate_bytes,
                    padding.PKCS1v15(),
                    cert.signature_hash_algorithm,
                )
            elif isinstance(ca_pub, ec.EllipticCurvePublicKey):
                ca_pub.verify(
                    cert.signature,
                    cert.tbs_certificate_bytes,
                    ec.ECDSA(cert.signature_hash_algorithm),
                )
            else:
                return None
        except InvalidSignature:
            return None
        except Exception:
            return None

        if cert.issuer != self.ca.subject:
            return None

        return san_name


def check_server_cert(
    cert_path: Path,
    *,
    required: bool = True,
    required_san: str = "gateway-tls",
    allowed_extra_sans: frozenset[str] = frozenset({"localhost"}),
    allowed_ips: frozenset[
        ipaddress.IPv4Address | ipaddress.IPv6Address
    ] = frozenset({ipaddress.ip_address("127.0.0.1")}),
    warn_days: int = 30,
) -> None:
    """
    Проверка server.crt при старте. Fail-closed.

    Порядок проверок:
      1. Файл существует? Нет → required: RuntimeError, иначе
         warning и выход.
      2. Symlink? Различаем dangling (target отсутствует) и
         symlink на не-файл (target существует, но не обычный
         файл). Обе ситуации — отказ при required=True. Разные
         сообщения — для диагностики оператору.
      3. Парсинг X.509 PEM.
      4. Срок действия (обе границы).
      5. Criticality всех расширений.
      6. EKU=serverAuth.
      7. SAN содержит required_san; DNS ⊆ allowed_extra ∪
         {required_san}; IP ⊆ allowed_ips.
    """
    # --- 1. Файл существует? -------------------------------------------
    if not cert_path.is_file():
        if cert_path.is_symlink():
            # Различаем для диагностики:
            # - target отсутствует → dangling symlink
            # - target существует, но не файл → symlink to non-regular-file
            # Поведение одинаковое: отказ при required=True.
            if cert_path.exists():
                message = (
                    f"server cert is a symlink to non-regular-file: "
                    f"{cert_path}"
                )
            else:
                message = f"server cert is a dangling symlink: {cert_path}"
            if required:
                raise RuntimeError(message)
            log.warning("%s (dev mode; skipping)", message)
            return
        if required:
            raise RuntimeError(
                f"server cert required but not mounted: {cert_path}"
            )
        log.warning("server cert not mounted at %s; skipping",
                    cert_path)
        return

    # --- 2. Symlink на существующий файл --------------------------------
    if cert_path.is_symlink():
        message = f"server cert path is a symlink: {cert_path}"
        if required:
            raise RuntimeError(message)
        log.warning("%s (dev mode; continuing)", message)

    # --- 3. Парсинг ------------------------------------------------------
    try:
        with cert_path.open("rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
    except Exception as e:
        raise RuntimeError(f"cannot parse server cert: {e}")

    # --- 4. Срок действия ------------------------------------------------
    now = datetime.now(timezone.utc)
    if now < cert.not_valid_before_utc:
        delta = (cert.not_valid_before_utc - now).total_seconds()
        raise RuntimeError(
            f"server cert not yet valid (nvb in {delta:.0f}s)"
        )
    days = (cert.not_valid_after_utc - now).days
    if days < 0:
        raise RuntimeError(f"server cert expired {-days} days ago")
    if days < warn_days:
        log.warning("server cert expires in %d days", days)

    # --- 5. Criticality всех расширений ----------------------------------
    try:
        bc = cert.extensions.get_extension_for_class(
            x509.BasicConstraints
        )
        if not bc.critical:
            raise RuntimeError(
                "server cert BasicConstraints must be critical"
            )
        if bc.value.ca:
            raise RuntimeError(
                "server cert BasicConstraints must be CA:FALSE"
            )
    except x509.ExtensionNotFound:
        raise RuntimeError("server cert missing BasicConstraints")

    try:
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage)
        if not ku.critical:
            raise RuntimeError("server cert KeyUsage must be critical")
        if not ku.value.digital_signature:
            raise RuntimeError("server cert missing digitalSignature")
    except x509.ExtensionNotFound:
        raise RuntimeError("server cert missing KeyUsage")

    try:
        eku = cert.extensions.get_extension_for_class(
            x509.ExtendedKeyUsage
        )
        if not eku.critical:
            raise RuntimeError("server cert EKU must be critical")
    except x509.ExtensionNotFound:
        raise RuntimeError("server cert missing EKU")

    # --- 6. EKU=serverAuth -----------------------------------------------
    if x509.oid.ExtendedKeyUsageOID.SERVER_AUTH not in eku.value:
        raise RuntimeError("server cert missing EKU=serverAuth")

    # --- 7. SAN ----------------------------------------------------------
    try:
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
    except x509.ExtensionNotFound:
        raise RuntimeError("server cert missing SAN")
    if not san.critical:
        raise RuntimeError("server cert SAN must be critical")

    dns = set(san.value.get_values_for_type(x509.DNSName))
    if not dns:
        raise RuntimeError("server cert SAN has no DNS entries")
    if required_san not in dns:
        raise RuntimeError(
            f"server cert SAN {sorted(dns)} lacks required "
            f"{required_san!r}; clients will fail to connect"
        )
    extra = dns - (allowed_extra_sans | {required_san})
    if extra:
        raise RuntimeError(
            f"server cert SAN has unexpected DNS entries: "
            f"{sorted(extra)}"
        )

    # IP SAN: отдельно от DNS. Пустой набор допустим; лишние
    # адреса, кроме allowed_ips, — отказ.
    ips = set(san.value.get_values_for_type(x509.IPAddress))
    extra_ips = ips - allowed_ips
    if extra_ips:
        raise RuntimeError(
            f"server cert SAN has unexpected IPs: "
            f"{sorted(map(str, extra_ips))}"
        )
