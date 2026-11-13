"""Où vivent les documents du paramétrage, et comment une déclaration en désigne un.

**C'est un contrat entre celui qui écrit l'arbre et ceux qui le lisent.** Il est au socle
pour cette seule raison : deux constantes de même valeur dans deux produits auraient
divergé au premier renommage fait d'un seul côté, et le lecteur ne trouverait plus le
fichier que l'écrivain a posé — sans que rien, de part ni d'autre, paraisse faux.

Extrait du module de paramétrage le 02/11/2026, deuxième usage.
"""

from __future__ import annotations

import re

# Nom de modèle et de domaine : il devient un nom de fichier ou de dossier du dépôt.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
SHARED = "shared"
_NAME = NAME_RE.pattern.strip("^$")
# « portée/nom » : la façon dont une déclaration (storage, source) désigne un modèle.
MODEL_RE = re.compile(rf"^(?P<scope>{_NAME})/(?P<name>{_NAME})$")
# Un modèle se désigne par un URI absolu, indépendant de l'emplacement de celui qui le
# désigne : un chemin relatif casserait au moindre déplacement et serait illisible.
ID_PREFIX = "miles:/"
_ID_RE = re.compile(
    rf"^miles:/(?:shared/(?P<shared>{_NAME})|domains/(?P<domain>{_NAME})/(?P<name>{_NAME}))$"
)


def model_path(scope: str, name: str) -> str:
    """Emplacements retenus au cadrage : un modèle transverse sous `shared/`, un modèle
    de domaine sous `domains/<domaine>/`. Aucun dossier d'environnement : l'environnement
    est une branche.

    Le dossier s'appelait `messages/` jusqu'au 13/11/2026, du vocabulaire du « message
    pivot ». Il porte `models/` depuis, parce qu'il ne contient plus seulement des
    messages : les schémas des types d'event y entrent aussi (décision de Gael), et un
    dossier dont le nom ne dit plus ce qu'il contient se fait mal ranger.

    **Un dépôt à l'ancienne disposition se convertit, il ne se lit pas à moitié** : voir
    `miles.workshop.conversion` au portail, qui est seul à écrire l'arbre.
    """
    if scope == SHARED:
        return f"shared/models/{name}.yaml"
    return f"domains/{scope}/models/{name}.yaml"


def model_id(scope: str, name: str) -> str:
    if scope == SHARED:
        return f"{ID_PREFIX}shared/{name}"
    return f"{ID_PREFIX}domains/{scope}/{name}"


def target_of(ref: str) -> tuple[str, str] | None:
    """(portée, nom) d'un `$ref` vers un modèle ; None s'il n'en désigne pas un."""
    match = _ID_RE.match(ref.split("#", 1)[0])
    if match is None:
        return None
    if match["shared"] is not None:
        return SHARED, match["shared"]
    return match["domain"], match["name"]
