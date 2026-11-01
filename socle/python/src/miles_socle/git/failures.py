"""Pourquoi une commande git a échoué, lu de ce que git a écrit sur sa sortie d'erreur.

Au socle depuis le 01/11/2026, deuxième usage : le module d'enrôlement lit les versions
d'un workspace hébergé avec le credential qui lui est confié (story 3bbd4f87), et doit
NOMMER à son administrateur ce qui empêche la lecture. Identifiants refusés, dépôt
disparu et forge injoignable appellent trois gestes différents, et un seul message
« échec » les enverrait chercher au mauvais endroit — c'est la leçon du 28/10/2026 sur le
401, où un même symptôme admettait trois causes.

Ce qui est RESTÉ au portail, c'est l'épreuve des cinq droits (`miles.git.rights`) : elle
ÉCRIT sur le dépôt — branche et étiquette poussées puis retirées — et aucun autre produit
ne le fait. Le socle ne porte que la lecture d'un échec, jamais sa provocation.
"""

from __future__ import annotations

import re
from enum import StrEnum

from miles_socle.git.runner import GitResult


class Reason(StrEnum):
    CREDENTIALS = "identifiants"
    REPOSITORY_NOT_FOUND = "depot_inexistant"
    UNREACHABLE = "injoignable"
    PROTECTED = "protection"
    FORBIDDEN = "droit_refuse"
    FAILED = "echec"


class GitAccessError(Exception):
    """Le dépôt n'a pas répondu ce qu'on attendait, et `reason` dit ce que git a dit.

    Au socle avec `classify`, parce qu'une fonction partagée qui refuse doit refuser dans
    un type partagé : la lever dans le type d'un produit obligerait le socle à connaître
    ce produit. Chaque produit la traduit ensuite dans SON vocabulaire d'erreur — le
    portail en fait une `RepositoryAccessError`, qui est ce que tous ses écrans attrapent.
    """

    def __init__(self, reason: Reason) -> None:
        super().__init__(f"dépôt inaccessible : {reason.value}")
        self.reason = reason


# Ordre significatif : une protection se lit aussi comme un refus d'écriture ; on la
# reconnaît d'abord, pour orienter vers la règle de protection (critère 13).
_REASONS: tuple[tuple[Reason, re.Pattern[str]], ...] = (
    (
        Reason.PROTECTED,
        re.compile(r"protected branch|GH006|GH013|pre-receive hook declined|rule viol", re.I),
    ),
    (Reason.REPOSITORY_NOT_FOUND, re.compile(r"repository not found|' not found", re.I)),
    (
        Reason.CREDENTIALS,
        re.compile(
            r"authentication failed|invalid username or password|could not read username"
            r"|returned error: 401",
            re.I,
        ),
    ),
    (
        Reason.FORBIDDEN,
        re.compile(r"permission to .* denied|write access|returned error: 403|denied", re.I),
    ),
    (
        Reason.UNREACHABLE,
        re.compile(
            r"could not resolve host|failed to connect|timed out|délai dépassé|unable to access",
            re.I,
        ),
    ),
)


def classify(result: GitResult) -> Reason:
    for reason, pattern in _REASONS:
        if pattern.search(result.stderr):
            return reason
    return Reason.FAILED
