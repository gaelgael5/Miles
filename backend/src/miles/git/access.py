from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes

from miles.secrets.model import Secret


class CertificateError(ValueError):
    """Certificat ou clé refusé ; `field` nomme le champ, le message ne porte jamais la clé."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field} : {reason}")
        self.field, self.reason = field, reason


@dataclass(frozen=True)
class ClientCertificate:
    """Certificat client mTLS : le certificat est public, la clé est un secret du socle."""

    cert_pem: str
    key: Secret
    not_after: datetime


@dataclass(frozen=True)
class GitAccess:
    """Moyens d'accès au dépôt : un jeton, un certificat client, ou les deux (16/10/2026)."""

    token: Secret | None = None
    certificate: ClientCertificate | None = None
    # Autorité de confiance supplémentaire : la forge jetable des tests seulement.
    ca_file: Path | None = None


@dataclass(frozen=True)
class GitFiles:
    """Chemins remis à git pour une commande ; ils vivent dans le dossier temporaire."""

    cert: Path | None = None
    key: Path | None = None


def certificate_not_after(cert_pem: str) -> datetime:
    return _load_certificate(cert_pem).not_valid_after_utc


def check_certificate(cert_pem: str, key_pem: Secret, now: datetime) -> datetime:
    """Vérifie que le certificat se lit, n'a pas expiré et correspond à la clé ; rend l'échéance.

    Une clé qui ne va pas avec le certificat ne se découvrirait qu'au premier refus TLS
    de la forge, loin de sa cause : on la refuse à l'enregistrement.
    """
    certificate = _load_certificate(cert_pem)
    if certificate.not_valid_after_utc <= now:
        raise CertificateError("client_certificate", "expire")
    key = _load_key(key_pem)
    public = key.public_key()
    expected = certificate.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    actual = public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    if expected != actual:
        raise CertificateError("client_key_secret_slug", "ne_correspond_pas")
    return certificate.not_valid_after_utc


def write_git_files(access: GitAccess, directory: Path) -> GitFiles:
    """Matérialise le certificat le temps d'une opération, dans le dossier temporaire.

    git (libcurl) n'accepte une clé client que par un chemin de fichier : c'est la seule
    exception au « rien sur disque ». Fichiers 0600 dans un dossier détruit après
    l'opération ; jamais dans le dépôt, jamais dans un dossier partagé.
    """
    if access.certificate is None:
        return GitFiles()
    tls = directory / ".miles-tls"
    tls.mkdir(mode=0o700, exist_ok=True)
    cert, key = tls / "client.crt", tls / "client.key"
    _write_private(cert, access.certificate.cert_pem)
    _write_private(key, access.certificate.key.reveal())
    return GitFiles(cert, key)


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)


def _load_certificate(cert_pem: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(cert_pem.encode("utf-8"))
    except ValueError:
        raise CertificateError("client_certificate", "illisible") from None


def _load_key(key_pem: Secret) -> PrivateKeyTypes:
    try:
        return serialization.load_pem_private_key(key_pem.reveal().encode("utf-8"), password=None)
    except (ValueError, TypeError):
        raise CertificateError("client_key_secret_slug", "illisible") from None
