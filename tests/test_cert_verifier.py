"""Тесты CertVerifier.

Naming convention: `test_*_rejects` — верификатор возвращает None
(«отвергает» сертификат). Функция не поднимает исключений.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from cert_verify import CertVerifier


def _make_ca():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "t-ca")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
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


def _make_client(
    ca_key, ca_cert, *,
    san="harness",
    eku=None, ku=None, bc=None,
    san_critical=True, eku_critical=True,
    ku_critical=True, bc_critical=True,
    sig_hash=hashes.SHA256(), expired=False,
):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    nvb = now - timedelta(days=1)
    nva = now + timedelta(days=365)
    if expired:
        nvb = now - timedelta(days=10)
        nva = now - timedelta(days=1)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "irrelevant")
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(nvb)
        .not_valid_after(nva)
    )
    if bc is not None:
        builder = builder.add_extension(bc, critical=bc_critical)
    if ku is not None:
        builder = builder.add_extension(ku, critical=ku_critical)
    if eku is not None:
        builder = builder.add_extension(eku, critical=eku_critical)
    if san is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(san)]),
            critical=san_critical,
        )
    return builder.sign(ca_key, sig_hash)


def _good_ku():
    return x509.KeyUsage(
        digital_signature=True, content_commitment=False,
        key_encipherment=False, data_encipherment=False,
        key_agreement=False, key_cert_sign=False, crl_sign=False,
        encipher_only=False, decipher_only=False,
    )


def _good_eku():
    return x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH])


def _good_bc():
    return x509.BasicConstraints(ca=False, path_length=None)


def _write_ca(tmp_path, cert):
    p = tmp_path / "ca.crt"
    p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return p


def _pem_urlencoded(cert):
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return urllib.parse.quote(pem, safe="")


@pytest.fixture
def ca(tmp_path):
    key, cert = _make_ca()
    return key, cert, _write_ca(tmp_path, cert)


def test_valid_client_accepts(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    cert = _make_client(
        ca_key, ca_cert, san="harness",
        eku=_good_eku(), ku=_good_ku(), bc=_good_bc(),
    )
    assert v.verify(_pem_urlencoded(cert)) == "harness"


def test_missing_eku_rejects(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    cert = _make_client(
        ca_key, ca_cert, san="harness",
        eku=None, ku=_good_ku(), bc=_good_bc(),
    )
    assert v.verify(_pem_urlencoded(cert)) is None


def test_server_auth_only_rejects(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    cert = _make_client(
        ca_key, ca_cert, san="harness",
        eku=x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
        ku=_good_ku(), bc=_good_bc(),
    )
    assert v.verify(_pem_urlencoded(cert)) is None


def test_ca_true_rejects(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    cert = _make_client(
        ca_key, ca_cert, san="harness",
        eku=_good_eku(), ku=_good_ku(),
        bc=x509.BasicConstraints(ca=True, path_length=None),
    )
    assert v.verify(_pem_urlencoded(cert)) is None


def test_sha1_signature_rejects(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    try:
        cert = _make_client(
            ca_key, ca_cert, san="harness",
            eku=_good_eku(), ku=_good_ku(), bc=_good_bc(),
            sig_hash=hashes.SHA1(),
        )
    except Exception as e:
        pytest.skip(f"cryptography rejects SHA-1 signing: {e}")
    assert v.verify(_pem_urlencoded(cert)) is None


def test_no_san_rejects(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    cert = _make_client(
        ca_key, ca_cert, san=None,
        eku=_good_eku(), ku=_good_ku(), bc=_good_bc(),
    )
    assert v.verify(_pem_urlencoded(cert)) is None


def test_expired_rejects(ca):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    cert = _make_client(
        ca_key, ca_cert, san="harness",
        eku=_good_eku(), ku=_good_ku(), bc=_good_bc(),
        expired=True,
    )
    assert v.verify(_pem_urlencoded(cert)) is None


def test_self_signed_rejects(ca, tmp_path):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    other_key, other_cert = _make_ca()
    cert = _make_client(
        other_key, other_cert, san="harness",
        eku=_good_eku(), ku=_good_ku(), bc=_good_bc(),
    )
    assert v.verify(_pem_urlencoded(cert)) is None


@pytest.mark.parametrize("kwarg", [
    "san_critical", "eku_critical", "ku_critical", "bc_critical",
])
def test_non_critical_extension_rejects(ca, kwarg):
    ca_key, ca_cert, ca_path = ca
    v = CertVerifier(ca_path)
    kwargs = dict(
        san="harness",
        eku=_good_eku(),
        ku=_good_ku(),
        bc=_good_bc(),
    )
    kwargs[kwarg] = False
    cert = _make_client(ca_key, ca_cert, **kwargs)
    assert v.verify(_pem_urlencoded(cert)) is None
