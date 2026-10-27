from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from miles.git.access import GitAccess
from miles.gitaccess.model import TOKEN_TYPE, GitAccessInputError, GitAccessNotFoundError
from miles.secrets.model import SecretError
from miles.secrets.service import SecretsService


@dataclass(frozen=True)
class AccessResolver:
    """Rassemble et vérifie l'accès d'une connexion, avant tout essai sur un dépôt."""

    secrets: SecretsService

    async def access(self, token_slug: str | None) -> GitAccess:
        """Le PAT, obligatoire depuis le retrait du mTLS (21/10/2026) ; absent : refus."""
        if not token_slug:
            raise GitAccessInputError("token_secret_slug")
        try:
            token = await self.secrets.resolve_secret(token_slug, TOKEN_TYPE)
        except SecretError:
            raise GitAccessInputError("token_secret_slug") from None
        return GitAccess(token)

    async def for_connection(self, db: Any, connection_id: str) -> GitAccess:
        """L'accès d'une connexion enregistrée, relu en base à chaque usage.

        Jamais mis en cache : un PAT remplacé doit valoir dès l'opération suivante, sans
        redémarrage.
        """
        token_slug = await db.fetchval(
            "SELECT token_secret_slug FROM git_connections WHERE id = $1", connection_id
        )
        if token_slug is None:
            raise GitAccessNotFoundError("connexion")
        return await self.access(token_slug)
