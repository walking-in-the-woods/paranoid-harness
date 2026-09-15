"""Тесты check_server_cert.

Naming convention: `test_*_raises` — функция поднимает RuntimeError
(«отвергает» сертификат исключением).
"""

from __future__ import annotations

import ipaddress
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from cert_verify import check_server_cert


@pytest.fixture(scope="module")
def ca():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True, crl_sign=True,
                encipher_only=False, decipher_only=False,
            ), critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _make_server_cert(
    ca, *,
    dns_names=("gateway-tls", "localhost"),
    ip_addrs=("127.0.0.1",),
    eku_server_auth=True,
    eku_critical=True, san_critical=True,
    ku_critical=True, bc_critical=True,
    expired=False, nvb_days_ago=1, nva_days=365,
    add_san=True,
):
    ca_key, ca_cert = ca
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    nvb = now - timedelta(days=nvb_days_ago)
    nva = now + timedelta(days=nva_days)
    if expired:
        nvb = now - timedelta(days=10)
        nva = now - timedelta(days=1)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "gateway-tls")
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nvb)
        .not_valid_after(nva)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=bc_critical,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=True, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ), critical=ku_critical,
        )
    )
    eku_oid = (ExtendedKeyUsageOID.SERVER_AUTH if eku_server_auth
               else ExtendedKeyUsageOID.CLIENT_AUTH)
    builder = builder.add_extension(
        x509.ExtendedKeyUsage([eku_oid]), critical=eku_critical
    )
    if add_san:
        sans = [x509.DNSName(d) for d in dns_names]
        sans.extend(
            x509.IPAddress(ipaddress.ip_address(ip)) for ip in ip_addrs
        )
        if sans:
            builder = builder.add_extension(
                x509.SubjectAlternativeName(sans), critical=san_critical
            )
    return builder.sign(ca_key, hashes.SHA256())


def _write_pem(cert, path: Path) -> Path:
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


GOOD = dict(
    required=True,
    required_san="gateway-tls",
    allowed_extra_sans=frozenset({"localhost"}),
    allowed_ips=frozenset({ipaddress.ip_address("127.0.0.1")}),
)


def test_valid_cert_passes(ca, tmp_path):
    cert = _make_server_cert(ca)
    p = _write_pem(cert, tmp_path / "server.crt")
    check_server_cert(p, **GOOD)


def test_missing_cert_required_raises(tmp_path):
    with pytest.raises(RuntimeError, match="required"):
        check_server_cert(tmp_path / "missing.crt", **GOOD)


def test_missing_cert_not_required_ok(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="cert_verify"):
        check_server_cert(
            tmp_path / "missing.crt", **{**GOOD, "required": False}
        )
    assert any("not mounted" in r.message for r in caplog.records)


def test_unparseable_cert_raises(tmp_path):
    p = tmp_path / "bad.crt"
    p.write_text("not a pem")
    with pytest.raises(RuntimeError, match="parse"):
        check_server_cert(p, **GOOD)


def test_expired_cert_raises(ca, tmp_path):
    cert = _make_server_cert(ca, expired=True)
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="expired"):
        check_server_cert(p, **GOOD)


def test_near_expiry_warns(ca, tmp_path, caplog):
    cert = _make_server_cert(ca, nva_days=10)
    p = _write_pem(cert, tmp_path / "server.crt")
    with caplog.at_level(logging.WARNING, logger="cert_verify"):
        check_server_cert(p, **GOOD)
    assert any("expires in" in r.message for r in caplog.records)


def test_wrong_eku_raises(ca, tmp_path):
    cert = _make_server_cert(ca, eku_server_auth=False)
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="EKU"):
        check_server_cert(p, **GOOD)


def test_missing_san_extension_raises(ca, tmp_path):
    cert = _make_server_cert(ca, add_san=False)
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="SAN"):
        check_server_cert(p, **GOOD)


def test_san_without_dns_raises(ca, tmp_path):
    cert = _make_server_cert(ca, dns_names=(), ip_addrs=("127.0.0.1",))
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="no DNS"):
        check_server_cert(p, **GOOD)


def test_missing_required_san_raises(ca, tmp_path):
    cert = _make_server_cert(ca, dns_names=("localhost",))
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="lacks required"):
        check_server_cert(p, **GOOD)


def test_extra_dns_san_raises(ca, tmp_path):
    cert = _make_server_cert(ca, dns_names=("gateway-tls", "evil.example"))
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="unexpected DNS"):
        check_server_cert(p, **GOOD)


def test_extra_ip_san_raises(ca, tmp_path):
    cert = _make_server_cert(
        ca, dns_names=("gateway-tls",),
        ip_addrs=("127.0.0.1", "10.0.0.5"),
    )
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="unexpected IPs"):
        check_server_cert(p, **GOOD)


def test_no_ip_san_ok(ca, tmp_path):
    cert = _make_server_cert(ca, ip_addrs=())
    p = _write_pem(cert, tmp_path / "server.crt")
    check_server_cert(p, **GOOD)


@pytest.mark.parametrize("kwarg", [
    "bc_critical", "ku_critical", "eku_critical", "san_critical",
])
def test_non_critical_extension_raises(ca, tmp_path, kwarg):
    kwargs = {kwarg: False}
    cert = _make_server_cert(ca, **kwargs)
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match="critical"):
        check_server_cert(p, **GOOD)


def test_not_yet_valid_raises(ca, tmp_path):
    ca_key, ca_cert = ca
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "gateway-tls")
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + timedelta(days=10))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=True, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ), critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("gateway-tls")]),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    p = _write_pem(cert, tmp_path / "server.crt")
    with pytest.raises(RuntimeError, match=r"not yet valid \(nvb in \d+s\)"):
        check_server_cert(p, **GOOD)


def test_symlink_required_rejects(ca, tmp_path):
    cert = _make_server_cert(ca)
    real = _write_pem(cert, tmp_path / "real.crt")
    link = tmp_path / "server.crt"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("cannot create symlink")
    with pytest.raises(RuntimeError, match="symlink"):
        check_server_cert(link, **GOOD)


def test_symlink_dev_mode_warns(ca, tmp_path, caplog):
    cert = _make_server_cert(ca)
    real = _write_pem(cert, tmp_path / "real.crt")
    link = tmp_path / "server.crt"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("cannot create symlink")
    dev = {**GOOD, "required": False}
    with caplog.at_level(logging.WARNING, logger="cert_verify"):
        check_server_cert(link, **dev)
    assert any("symlink" in r.message for r in caplog.records)


def test_symlink_to_directory_required_raises(tmp_path):
    target_dir = tmp_path / "not-a-cert"
    target_dir.mkdir()
    link = tmp_path / "server.crt"
    try:
        link.symlink_to(target_dir)
    except OSError:
        pytest.skip("cannot create symlink")
    with pytest.raises(RuntimeError, match="symlink to non-regular-file"):
        check_server_cert(link, **GOOD)


def test_dangling_symlink_required_raises(tmp_path):
    link = tmp_path / "server.crt"
    try:
        link.symlink_to(tmp_path / "nonexistent.crt")
    except OSError:
        pytest.skip("cannot create symlink")
    with pytest.raises(RuntimeError, match="dangling symlink"):
        check_server_cert(link, **GOOD)
