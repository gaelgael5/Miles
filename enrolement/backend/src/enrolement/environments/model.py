from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from miles_socle.events.catalog import EventShape

ENVIRONMENT_OBJECT_KIND = "environment"

ENVIRONMENT_CREATED_EVENT = "environment.created"
ENVIRONMENT_RENAMED_EVENT = "environment.renamed"
ENVIRONMENT_DELETED_EVENT = "environment.deleted"
# Placer un workspace et le retirer sont DEUX faits, et non un seul portant une valeur
# nulle : « depuis quand cet environnement n'héberge-t-il plus rien ? » doit se lire au
# journal sans avoir à interpréter l'absence d'une propriété.
ENVIRONMENT_WORKSPACE_PLACED_EVENT = "environment.workspace_placed"
ENVIRONMENT_WORKSPACE_CLEARED_EVENT = "environment.workspace_cleared"
# --- Les formes, mesurées sur les producteurs de `service.py` -------------------------
_NOM: Mapping[str, Any] = {"type": "string", "minLength": 1}
_WORKSPACE: Mapping[str, Any] = {"type": "string", "minLength": 1}


def _ferme(proprietes: Mapping[str, Any]) -> dict[str, Any]:
    """Un bloc fermé dont toutes les propriétés sont obligatoires (voir `pairing.events`)."""
    return {
        "type": "object",
        "properties": dict(proprietes),
        "required": sorted(proprietes),
        "additionalProperties": False,
    }


_IDENTITE = _ferme({"slug": _NOM, "label": _NOM})
EVENT_SHAPES = (
    EventShape(ENVIRONMENT_CREATED_EVENT, "Environnement déclaré", _IDENTITE),
    EventShape(
        ENVIRONMENT_RENAMED_EVENT,
        "Environnement renommé",
        # Les valeurs précédentes sont dans l'event, et c'est tout l'intérêt : un journal
        # qui ne dit pas ce qu'il y avait avant ne permet pas de retrouver ce qu'une
        # procédure désignait la semaine dernière.
        _ferme({"slug": _NOM, "label": _NOM, "previous_slug": _NOM, "previous_label": _NOM}),
    ),
    # Les deux noms sont redits à la suppression : la ligne a disparu, et l'event reste la
    # seule trace de ce qu'elle portait.
    EventShape(ENVIRONMENT_DELETED_EVENT, "Environnement supprimé", _IDENTITE),
    EventShape(
        ENVIRONMENT_WORKSPACE_PLACED_EVENT,
        "Workspace placé sur un environnement",
        # `workspace_id` est une CHAÎNE ici et NUL dans l'event de retrait : c'est la
        # branche du producteur qui le garantit, et c'est ce qui rend les deux faits
        # discernables sans interpréter l'absence d'une propriété. Le précédent, lui, est
        # nul au premier placement.
        _ferme({"workspace_id": _WORKSPACE, "previous_workspace_id": {"type": ["string", "null"]}}),
    ),
    EventShape(
        ENVIRONMENT_WORKSPACE_CLEARED_EVENT,
        "Workspace retiré d'un environnement",
        _ferme(
            {
                "workspace_id": {"type": "null"},
                "previous_workspace_id": {"type": ["string", "null"]},
            }
        ),
    ),
)
# DÉRIVÉ des formes, jamais recopié : deux listes auraient divergé au premier type ajouté.
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)

MAX_LABEL_LENGTH = 80
MAX_SLUG_LENGTH = 48
# La borne de `confided_git_workspace.id` : la seule source de cette valeur est la liste
# que le module de paramétrage confie, et une borne plus courte ici refuserait un
# identifiant qu'il nous a pourtant transmis.
MAX_WORKSPACE_ID_LENGTH = 200
# La MÊME forme que le CHECK de la migration : minuscules, chiffres, traits d'union
# séparateurs. Écrite aux deux endroits parce que la base est la seule à tenir l'invariant
# pour de bon, et que le code est le seul à pouvoir refuser en NOMMANT le champ fautif.
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class EnvironmentError(Exception):
    """Refus du référentiel des environnements ; le message dit lequel."""


class EnvironmentInputError(EnvironmentError):
    """Une saisie est inutilisable, et `field` dit laquelle.

    Nommer le champ n'est pas un confort : « corps invalide » fait relire les deux
    saisies, alors qu'une seule est en cause. C'est la panne que la machine de test a
    révélée le 28/10/2026 sur le nom déclaré d'un appariement.
    """

    def __init__(self, field: str) -> None:
        super().__init__(f"saisie refusée : {field}")
        self.field = field


class EnvironmentSlugTakenError(EnvironmentError):
    """Un autre environnement porte déjà ce slug.

    Distinct de `EnvironmentInputError` : la saisie est bien formée, c'est l'état du
    référentiel qui la refuse. L'écran doit le dire autrement — retaper un slug correct ne
    règle pas une collision.
    """

    def __init__(self, slug: str) -> None:
        super().__init__(f"slug déjà pris : {slug}")
        self.slug = slug


class EnvironmentNotFoundError(EnvironmentError):
    """Aucun environnement sous cet identifiant."""


class WorkspaceNotExposedError(EnvironmentError):
    """Aucun module de paramétrage apparié n'expose ce workspace.

    Refus distinct d'une saisie mal formée : l'identifiant peut être parfaitement écrit
    et simplement ne venir de personne. Le geste à faire n'est pas de le corriger, c'est
    de le faire confier depuis le module de paramétrage — ou d'apparier celui-ci.
    """

    def __init__(self, workspace_id: str, exposed: list[str]) -> None:
        super().__init__(f"workspace non exposé : {workspace_id}")
        self.workspace_id = workspace_id
        # Ceux qui existent sont NOMMÉS dans le refus : sans eux, l'appelant ne peut que
        # deviner, et un agent réessaierait indéfiniment la même valeur.
        self.exposed = exposed


class EnvironmentPairedError(EnvironmentError):
    """L'environnement porte un appariement : il ne se supprime pas tant qu'il le porte.

    Refus distinct de tous les autres, parce qu'il appelle un geste précis — révoquer
    l'appariement — qu'aucun message générique ne ferait deviner.
    """


class EnvironmentDesignatedError(EnvironmentError):
    """Une demande d'appariement EN ATTENTE le désigne : il ne se supprime pas encore.

    Distinct de l'appariement conclu, et les deux gestes n'ont rien de commun : ici il
    suffit de refuser la demande, ou d'en désigner un autre — là il faut révoquer. Fondre
    les deux refus ferait chercher une révocation qui n'existe pas.

    Pourquoi refuser plutôt que d'effacer la désignation : l'humain qui l'a posée verrait
    son code cesser d'être révélable sans qu'aucun écran ne dise pourquoi.
    """


@dataclass(frozen=True)
class Environment:
    """Un environnement du référentiel : ce qui se lit, ce qui s'écrit, et son état."""

    id: UUID
    slug: str
    label: str
    created_at: datetime
    updated_at: datetime
    # L'origine de la stack appariée à cet environnement, nulle tant qu'aucune ne l'est.
    # Un environnement déclaré et pas encore apparié est l'état normal du premier jour,
    # pas une anomalie : c'est pour cela que ce champ ne porte pas de booléen « en erreur ».
    paired_base_url: str | None
    # L'origine d'une demande EN ATTENTE qui l'a désigné, s'il y en a une. Elle ne
    # consomme pas l'environnement — une demande refusée ou expirée le laisse libre —
    # mais elle retient sa suppression, et l'écran doit pouvoir dire laquelle.
    designated_base_url: str | None
    # Le workspace dont cet environnement héberge le paramétrage, nul tant qu'on ne lui
    # en a pas placé (01/11/2026). Il survit à une révocation de la stack : c'est
    # l'environnement qui héberge, pas l'appariement du moment.
    workspace_id: str | None = None


def validate_label(raw: str) -> str:
    """Le libellé, tel qu'un humain l'a écrit — borné, mais jamais réécrit.

    `isprintable` est vrai pour l'espace et les lettres accentuées, faux pour les
    tabulations, retours à la ligne et caractères de contrôle : exactement la coupure que
    la base applique, et elle n'a pas à être retranscrite en expression régulière.
    """
    label = raw.strip()
    if not label or len(label) > MAX_LABEL_LENGTH or not label.isprintable():
        raise EnvironmentInputError("label")
    return label


def validate_workspace_id(raw: str) -> str:
    """L'identifiant du workspace, borné et débarrassé de rien.

    Il vient d'une liste que le PAIR nous a confiée : sa forme est décidée là-bas, et la
    contraindre davantage ici refuserait un identifiant pourtant légitime. On vérifie donc
    ce que la base vérifie, et rien de plus — l'existence, elle, se vérifie contre la
    liste exposée, qui est la vraie garde.
    """
    workspace_id = raw.strip()
    if (
        not workspace_id
        or len(workspace_id) > MAX_WORKSPACE_ID_LENGTH
        or not workspace_id.isprintable()
    ):
        raise EnvironmentInputError("workspace_id")
    return workspace_id


def validate_slug(raw: str) -> str:
    """Le slug, validé par expression régulière stricte AVANT tout usage.

    Il finira dans une adresse et dans un journal : il est validé ici, et jamais
    « nettoyé » pour passer. Une saisie fautive est refusée en nommant le champ — la
    corriger est le geste de l'humain, pas celui du serveur.

    Ce service ne DÉRIVE pas le slug depuis le libellé, et c'est délibéré : la dérivation
    est une aide à la saisie, qui pré-remplit un champ que l'utilisateur garde le droit de
    changer. Elle vit donc là où la saisie a lieu. Ce qui vient ici est un CHOIX, pas une
    valeur à normaliser — et ne rien normaliser est ce qui garantit que le slug enregistré
    est exactement celui qu'on a vu à l'écran.
    """
    slug = raw.strip()
    if not slug or len(slug) > MAX_SLUG_LENGTH or not SLUG_RE.match(slug):
        raise EnvironmentInputError("slug")
    return slug
