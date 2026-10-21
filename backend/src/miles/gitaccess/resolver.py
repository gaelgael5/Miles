from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from miles.git.access import CertificateError, ClientCertificate, GitAccess, check_certificate
from miles.gitaccess.model import (
    CLIENT_KEY_TYPE,
    TOKEN_TYPE,
    CertificateRef,
    GitAccessInputError,
    GitAccessNotFoundError,
)
from miles.secrets.model import SecretError
from miles.secrets.service import SecretsService

# Noms des champs côté écran : le contrôle du certificat est commun au menu Certificats
# et au remplacement, il parle la langue de leurs formulaires.
_CERTIFICATE_FIELDS = {
    "client_certificate": "cert_pem",
    "client_key_secret_slug": "key_secret_slug",
}


@dataclass(frozen=True)
class AccessResolver:
    """Rassemble et vérifie les moyens d'accès d'une connexion, avant tout essai sur un dépôt."""

    secrets: SecretsService
    now: Callable[[], datetime]
    # Autorité de confiance de la forge jetable des tests ; None en production.
    ca_file: Path | None = None

    async def certificate(self, ref: CertificateRef) -> ClientCertificate:
        """Certificat lisible, non expiré, allant avec sa clé ; sinon refus nommant le champ.

        Une clé qui ne va pas avec le certificat ne se découvrirait qu'au premier refus
        TLS de la forge, loin de sa cause.
        """
        try:
            key = await self.secrets.resolve_secret(ref.key_secret_slug, CLIENT_KEY_TYPE)
        except SecretError:
            raise GitAccessInputError("key_secret_slug") from None
        try:
            not_after = check_certificate(ref.cert_pem, key, self.now())
        except CertificateError as exc:
            raise GitAccessInputError(_CERTIFICATE_FIELDS[exc.field], exc.reason) from None
        return ClientCertificate(ref.cert_pem, key, not_after)

    async def access(self, token_slug: str | None, certificate: CertificateRef | None) -> GitAccess:
        """PAT, certificat ou les deux (21/10/2026) ; aucun : refus avant toute tentative."""
        if not token_slug and certificate is None:
            raise GitAccessInputError("token_secret_slug", "au_moins_un_acces")
        token = None
        if token_slug:
            try:
                token = await self.secrets.resolve_secret(token_slug, TOKEN_TYPE)
            except SecretError:
                raise GitAccessInputError("token_secret_slug") from None
        client = await self.certificate(certificate) if certificate else None
        return GitAccess(token, client, self.ca_file)

    async def for_connection(self, db: Any, connection_id: str) -> GitAccess:
        """L'accès d'une connexion enregistrée, relu en base à chaque usage.

        Jamais mis en cache : un PAT remplacé ou un certificat renouvelé doit valoir dès
        l'opération suivante, sans redémarrage.
        """
        row = await db.fetchrow(
            "SELECT c.token_secret_slug, k.cert_pem, k.key_secret_slug FROM git_connections c"
            " LEFT JOIN client_certificates k ON k.id = c.certificate_id WHERE c.id = $1",
            connection_id,
        )
        if row is None:
            raise GitAccessNotFoundError("connexion")
        certificate = (
            CertificateRef(row["cert_pem"], row["key_secret_slug"]) if row["cert_pem"] else None
        )
        return await self.access(row["token_secret_slug"], certificate)
