"""Moyen d'accès à un dépôt git, au socle depuis le 01/11/2026.

Deuxième usage : le module d'enrôlement lit les versions d'un workspace hébergé avec
le credential que le module de paramétrage lui a confié (story 3bbd4f87), après le
portail qui lit et écrit les dépôts de ses workspaces.
"""

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
