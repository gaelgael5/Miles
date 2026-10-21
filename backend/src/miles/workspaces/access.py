from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from miles.git.access import CertificateError, ClientCertificate, GitAccess, check_certificate
from miles.secrets.model import SecretError
from miles.secrets.service import SecretsService
from miles.workspaces.model import CertificateInput, Workspace, WorkspaceInputError

TOKEN_TYPE = "GIT_TOKEN"  # noqa: S105  # nom du type, pas une valeur
CLIENT_KEY_TYPE = "GIT_CLIENT_KEY"


@dataclass(frozen=True)
class AccessResolver:
    """Rassemble les moyens d'accès d'un workspace, vérifiés avant tout essai sur le dépôt."""

    secrets: SecretsService
    now: Callable[[], datetime]
    # Autorité de confiance de la forge jetable des tests ; None en production.
    ca_file: Path | None = None

    async def resolve(
        self, token_slug: str | None, certificate: CertificateInput | None
    ) -> tuple[GitAccess, datetime | None]:
        """Rend l'accès et l'échéance du certificat. Ni jeton ni certificat : refus (critère 2)."""
        if not token_slug and certificate is None:
            raise WorkspaceInputError("git_secret_slug", "au_moins_un_acces")
        token = None
        if token_slug:
            try:
                token = await self.secrets.resolve_secret(token_slug, TOKEN_TYPE)
            except SecretError:
                raise WorkspaceInputError("git_secret_slug") from None
        client, not_after = await self._certificate(certificate)
        return GitAccess(token, client, self.ca_file), not_after

    async def resolve_for(self, workspace: Workspace) -> GitAccess:
        certificate = None
        if workspace.client_cert_pem and workspace.client_key_secret_slug:
            certificate = CertificateInput(
                workspace.client_cert_pem, workspace.client_key_secret_slug
            )
        access, _ = await self.resolve(workspace.git_secret_slug, certificate)
        return access

    async def _certificate(
        self, certificate: CertificateInput | None
    ) -> tuple[ClientCertificate | None, datetime | None]:
        if certificate is None:
            return None, None
        if not certificate.key_secret_slug:
            raise WorkspaceInputError("client_key_secret_slug")
        try:
            key = await self.secrets.resolve_secret(certificate.key_secret_slug, CLIENT_KEY_TYPE)
        except SecretError:
            raise WorkspaceInputError("client_key_secret_slug") from None
        try:
            not_after = check_certificate(certificate.cert_pem, key, self.now())
        except CertificateError as exc:
            raise WorkspaceInputError(exc.field, exc.reason) from None
        return ClientCertificate(certificate.cert_pem, key, not_after), not_after
