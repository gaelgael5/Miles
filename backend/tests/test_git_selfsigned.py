from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from miles.git.access import check_certificate
from miles.git.selfsigned import generate_self_signed, public_key_pem

NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)


def test_generate_self_signed_gives_a_key_matching_its_certificate_until_the_asked_day() -> None:
    generated = generate_self_signed("Machine de prod", 90, NOW)

    assert generated.not_after == NOW + timedelta(days=90)
    # Le contrôle d'enregistrement d'un certificat importé l'accepte tel quel.
    assert check_certificate(generated.cert_pem, generated.key, NOW) == generated.not_after


def test_generate_self_signed_is_a_client_certificate_never_an_authority() -> None:
    certificate = x509.load_pem_x509_certificate(
        generate_self_signed("Machine", 365, NOW).cert_pem.encode()
    )

    assert certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    usages = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert list(usages) == [ExtendedKeyUsageOID.CLIENT_AUTH]
    assert certificate.issuer == certificate.subject


def test_generate_self_signed_truncates_a_long_label_to_a_valid_common_name() -> None:
    certificate = x509.load_pem_x509_certificate(
        generate_self_signed("x" * 200, 1, NOW).cert_pem.encode()
    )

    common_name = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert common_name == "x" * 64


def test_generate_self_signed_never_shows_the_key_in_its_representation() -> None:
    generated = generate_self_signed("Machine", 1, NOW)

    assert "PRIVATE KEY" in generated.key.reveal()
    assert "PRIVATE KEY" not in repr(generated)


def test_public_key_pem_is_the_public_half_of_the_generated_key() -> None:
    generated = generate_self_signed("Machine", 1, NOW)
    private = serialization.load_pem_private_key(generated.key.reveal().encode(), password=None)
    expected = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    assert public_key_pem(generated.cert_pem) == expected.decode()


def test_public_key_pem_of_an_unreadable_certificate_is_none() -> None:
    assert public_key_pem("pas un certificat") is None
