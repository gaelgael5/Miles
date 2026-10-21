from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from miles.secrets.model import Secret

VALIDITY_MIN_DAYS = 1
VALIDITY_MAX_DAYS = 3650
# Un CN X.509 est borné à 64 caractères (RFC 5280, ub-common-name).
_COMMON_NAME_MAX = 64
# Tolérance d'horloge : une forge un peu en retard refuserait un certificat « pas encore
# valide » pendant les premières minutes.
_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class GeneratedCertificate:
    cert_pem: str
    key: Secret
    not_after: datetime


def generate_self_signed(common_name: str, days: int, now: datetime) -> GeneratedCertificate:
    """Paire de clés et certificat client auto-signé, en mémoire seulement.

    ECDSA P-256 plutôt que RSA : accepté par tout TLS 1.2+, clé courte et génération
    immédiate. La clé n'est rendue qu'enveloppée dans un `Secret`, pour le socle.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name[:_COMMON_NAME_MAX])])
    not_after = now + timedelta(days=days)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _CLOCK_SKEW)
        .not_valid_after(not_after)
        # Certificat d'authentification client, jamais une autorité : il ne doit pas
        # pouvoir signer d'autres certificats si un proxy le prend pour ancre.
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    cert_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    return GeneratedCertificate(cert_pem, Secret(key_pem), certificate.not_valid_after_utc)


def public_key_pem(cert_pem: str) -> str | None:
    """Clé publique du certificat, à copier côté forge.

    Repli volontaire : None si le PEM ne se lit pas, pour qu'une ligne abîmée ne fasse
    pas échouer toute la liste ; le contrôle à l'enregistrement rend ce cas anormal.
    """
    try:
        certificate = x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
    except ValueError:
        return None
    return (
        certificate.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode("ascii")
    )
