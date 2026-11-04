"""Authentifier un appel de DÉCLENCHEUR D'HÔTE par le secret de la stack.

Rien d'humain n'est derrière un tel appel : le cookie de session est `Secure` et lié à une
personne, un déclencheur d'hôte n'en a pas. Le secret est un secret SYSTÈME au sens de la
skill `secrets` — c'est ce qui déclenche la lecture qui décide de sa portée, et ici c'est
une tâche sans personne.

**Fail closed, deux fois** : secret non configuré, tout est refusé ; secret présenté
différent, refusé. Une route d'entretien qui ne tourne pas laisse une base qui grossit ;
une route d'entretien ouverte laisse n'importe qui retirer ce qu'elle retire.

**Au socle parce qu'il y a deux routes d'entretien** (l'entretien des journaux partitionnés,
et celui des imports de fichier du module d'environnement depuis le 04/11/2026). Une
deuxième copie de cette garde aurait été une deuxième règle de sécurité à tenir d'accord —
et c'est celle qui décide qui peut purger.
"""

from __future__ import annotations

import hmac

import structlog
from fastapi import HTTPException, Request, status

from miles_socle.auth.context import client_origin

log = structlog.get_logger(__name__)

BEARER = "bearer"


def challenge_for(realm: str) -> str:
    """Le défi d'un 401 : il dit à l'appelant COMMENT présenter son jeton.

    Rendu par une fonction parce qu'il entre dans les contrats publiés : le royaume y est
    écrit, et le dériver interdit qu'un en-tête et sa documentation divergent.
    """
    return f'Bearer realm="{realm}"'


def presented_token(authorization: str | None) -> str | None:
    """Le jeton d'un en-tête `Authorization: Bearer`. Tout autre schéma ne présente rien.

    Même règle que les clés d'API (`apikeys/presentation.py`) : un schéma inattendu ne se
    rattrape pas en lisant la valeur quand même, sinon un `Basic` mal formé finirait
    comparé à notre secret.
    """
    presentee = (authorization or "").strip()
    if not presentee:
        return None
    schema, _, valeur = presentee.partition(" ")
    if schema.lower() != BEARER:
        return None
    return valeur.strip() or None


def resolve_stack_token(request: Request, expected: str | None, *, realm: str, event: str) -> None:
    """Laisse passer le déclencheur, ou lève un 401 qui n'apprend rien de plus.

    `event` nomme le refus au journal : deux routes d'entretien doivent se distinguer dans
    les traces, c'est tout ce qui les distingue à la lecture.
    """
    if not expected:
        # Non configuré : la route est inerte, et elle le DIT au journal. Rendre 503
        # « non configuré » distinguerait une stack sans jeton d'une stack avec, ce qui
        # renseigne un appelant qui n'a rien à savoir.
        raise _refused(request, event, "non_configure", realm)
    presente = presented_token(request.headers.get("authorization"))
    # compare_digest et non `==` : la comparaison d'un secret ne doit pas s'arrêter au
    # premier caractère qui diffère.
    if presente is None or not hmac.compare_digest(presente, expected):
        raise _refused(request, event, "jeton_invalide", realm)


def _refused(request: Request, event: str, raison: str, realm: str) -> HTTPException:
    log.warning(event, raison=raison, origin=client_origin(request))
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="jeton_requis",
        headers={"WWW-Authenticate": challenge_for(realm)},
    )
