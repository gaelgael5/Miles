from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from miles.git.access import (
    CertificateError,
    ClientCertificate,
    GitAccess,
    check_certificate,
    write_git_files,
)
from miles.secrets.model import Secret

NOW = datetime(2026, 10, 21, tzinfo=UTC)


def _pair(not_after: datetime) -> tuple[str, Secret]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "miles")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(days=1))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return cert.public_bytes(serialization.Encoding.PEM).decode(), Secret(key_pem)


def test_matching_certificate_and_key_give_the_expiry() -> None:
    expiry = NOW + timedelta(days=90)
    cert, key = _pair(expiry)

    assert check_certificate(cert, key, NOW) == expiry.replace(microsecond=0)


def test_expired_certificate_is_refused() -> None:
    cert, key = _pair(NOW - timedelta(hours=1))

    with pytest.raises(CertificateError) as caught:
        check_certificate(cert, key, NOW)
    assert (caught.value.field, caught.value.reason) == ("client_certificate", "expire")


def test_key_of_another_certificate_is_refused() -> None:
    cert, _ = _pair(NOW + timedelta(days=30))
    _, other_key = _pair(NOW + timedelta(days=30))

    with pytest.raises(CertificateError) as caught:
        check_certificate(cert, other_key, NOW)
    assert (caught.value.field, caught.value.reason) == (
        "client_key_secret_slug",
        "ne_correspond_pas",
    )


@pytest.mark.parametrize(
    ("cert", "key", "field"),
    [
        ("pas un certificat", None, "client_certificate"),
        (None, Secret("pas une clé"), "client_key_secret_slug"),
    ],
)
def test_unreadable_material_names_the_field_without_echoing_it(
    cert: str | None, key: Secret | None, field: str
) -> None:
    good_cert, good_key = _pair(NOW + timedelta(days=30))

    with pytest.raises(CertificateError) as caught:
        check_certificate(cert or good_cert, key or good_key, NOW)
    assert caught.value.field == field
    assert "pas une clé" not in str(caught.value)


def test_key_is_written_private_only_for_the_operation(tmp_path: Path) -> None:
    cert, key = _pair(NOW + timedelta(days=30))
    access = GitAccess(certificate=ClientCertificate(cert, key, NOW + timedelta(days=30)))

    files = write_git_files(access, tmp_path)

    assert files.key is not None and files.cert is not None
    assert files.key.read_text() == key.reveal()
    assert stat.S_IMODE(files.key.stat().st_mode) == 0o600
    assert stat.S_IMODE(files.key.parent.stat().st_mode) == 0o700


def test_token_only_access_writes_nothing(tmp_path: Path) -> None:
    files = write_git_files(GitAccess(token=Secret("t")), tmp_path)

    assert (files.cert, files.key) == (None, None)
    assert list(tmp_path.iterdir()) == []
