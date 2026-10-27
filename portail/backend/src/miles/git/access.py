from __future__ import annotations

from dataclasses import dataclass

from miles_socle.secrets.model import Secret


@dataclass(frozen=True)
class GitAccess:
    """Moyen d'accès au dépôt : le PAT du compte de service.

    Seul moyen depuis le 21/10/2026 : le certificat client mTLS a été retiré, GitHub
    n'en accepte aucun sur HTTPS (story 6ea31024).
    """

    token: Secret
