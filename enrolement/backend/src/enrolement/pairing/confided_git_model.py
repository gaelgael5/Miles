from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from miles_socle.signing.peers import IdentityError

# Ce qu'une connexion git CONFIÉE est, et les refus qu'elle produit (ticket edcf78bc).
#
# Dans son propre fichier et non dans `model.py` : celui-ci porte les formes et les refus de
# l'appariement lui-même, qu'on relit pour comprendre comment deux modules se reconnaissent.
# Ce qui est ici se relit pour une autre question — ce qu'on détient pour le compte d'un
# module apparié —, et `model.py` est de toute façon à sa limite de 300 lignes.

# Bornes de CE module, et non recopiées du contrat : le contrat borne grossièrement pour ne
# rien interpréter de démesuré, ici on borne ce qu'on écrit en base. Les deux valeurs
# diffèrent donc volontairement, et ce fichier fait foi pour la base.
CONNECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
# La forge, ou une organisation de la forge. Aucune liste de forges admises ici : quelles
# forges on accepte est la règle du module de paramétrage, où un humain saisit l'adresse.
# Re-décider ici ferait refuser, par une base qui n'avait pas à en juger, la première forge
# qu'il admettra en plus de GitHub.
FORGE_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]{1,253}(:[0-9]{2,5})?(/[A-Za-z0-9_.-]{1,100})?$")
REPO_URL_RE = re.compile(
    r"^https?://[A-Za-z0-9.-]{1,253}(:[0-9]{2,5})?(/[A-Za-z0-9_.-]{1,100}){1,3}$"
)
MAX_LABEL_LENGTH = 200
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class ConfidedGitError(IdentityError):
    """Base des refus des connexions git confiées ; aucun message ne porte de credential."""


class ConfidedGitInputError(ConfidedGitError):
    """La charge transmise est refusée ; `field` nomme le champ fautif.

    Nommé plutôt qu'opaque, comme la clé publique mal formée de l'appariement : la charge
    est celle de l'APPELANT, qui est authentifié par signature à ce stade, et lui cacher la
    cause l'enverrait chercher une panne de signature. Le champ seul, jamais la valeur —
    une valeur recopiée dans un refus traverse les journaux des deux côtés.
    """

    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


class ConfidedGitStaleRevisionError(ConfidedGitError):
    """Une transmission plus ancienne que celle qu'on détient : refusée, et on dit laquelle.

    Deux administrateurs qui changent deux connexions en même temps peuvent faire arriver
    les deux photos dans le désordre. L'accepter laisserait ici la plus vieille des deux
    sans que personne le sache, et le module de paramétrage afficherait « confiées » en
    croyant avoir transmis la dernière. La révision détenue part dans le refus : c'est un
    nombre que l'appelant a lui-même alloué, il n'apprend donc rien de nouveau.
    """

    def __init__(self, held: int, offered: int) -> None:
        super().__init__(f"révision {offered} refusée : la révision {held} est déjà détenue")
        self.held, self.offered = held, offered


class ConfidedGitSpeciesError(ConfidedGitError):
    """L'appelant est apparié, mais pas comme module de paramétrage.

    Fail closed, et c'est l'interdit central du ticket : « transmettre un credential git à
    un module d'environnement » est interdit sous quelque forme que ce soit — y compris
    celle-ci, où c'est l'environnement qui en pousserait. La base le refuse aussi (clé
    étrangère composée vers l'espèce), et ce refus-ci existe pour le NOMMER : une violation
    de contrainte n'explique rien à qui la lit.
    """


class NoParametragePairedError(ConfidedGitError):
    """Aucun module de paramétrage apparié : rien n'a été confié, et c'est dit (critère 7).

    Dit tel quel, et non traité comme une panne : sans ce refus nommé, une lecture de git
    qui ne trouve pas de credential se lirait comme une forge injoignable, et le diagnostic
    partirait sur la configuration de l'environnement.
    """


class ConfidedConnectionUnknownError(ConfidedGitError):
    """Cette connexion n'est plus confiée (critère 9) : elle a été supprimée à la source.

    Le message NOMME la source, parce que c'est là qu'il faut aller : la connexion ne se
    recrée pas ici, et la chercher dans cet écran-là est la seule suite utile.
    """

    def __init__(self, connection_id: str, peer_base_url: str) -> None:
        super().__init__(
            f"la connexion git « {connection_id} » n'est pas confiée : elle a été supprimée"
            f" dans le module de paramétrage ({peer_base_url}), ou ne l'a jamais été"
        )
        self.connection_id = connection_id


@dataclass(frozen=True)
class ConfidedWorkspaceRef:
    """Un workspace qui se sert d'une connexion confiée, et le dépôt qu'il travaille."""

    id: str
    repo_url: str | None


@dataclass(frozen=True)
class ConfidedConnection:
    """Une connexion git confiée, telle qu'on peut la MONTRER : jamais son credential.

    Aucun champ ne porte la valeur, ni en clair ni chiffrée, et il n'en existe pas de
    variante tronquée : un fragment de PAT dans une réponse d'API est encore un secret
    divulgué (critère 2). `renewed_at` dit QUAND le credential a changé, ce qui est la
    seule chose qu'on ait à en dire au-dehors.
    """

    id: str
    label: str
    base_url: str
    confided_at: datetime
    renewed_at: datetime | None
    workspaces: tuple[ConfidedWorkspaceRef, ...]


@dataclass(frozen=True)
class ConfidedConnectionDetail:
    """Une connexion confiée, et si son credential est LISIBLE ici.

    Un champ et non une exception, et c'est délibéré : un credential devenu illisible —
    MILES_SECRETS_KEY changée, ligne altérée — est précisément le cas que le critère 6 veut
    distinguer d'une panne de forge, et pour le distinguer il faut pouvoir afficher le
    reste du détail en le disant. Une exception priverait l'écran de tout ce qui l'entoure,
    et le diagnostic repartirait de zéro.

    La lecture ne rend JAMAIS la valeur : elle l'ouvre pour savoir si elle s'ouvre, et
    l'oublie. C'est la seule chose qu'on puisse dire d'un credential au-dehors.
    """

    connection: ConfidedConnection
    credential_readable: bool


@dataclass(frozen=True)
class ConfidedGitState:
    """Ce que ce module détient pour le compte du module de paramétrage.

    `peer_base_url` nul veut dire « aucun module de paramétrage apparié », et la liste est
    alors vide par construction : les connexions confiées sont supprimées en cascade avec
    l'appariement. Un état explicite plutôt qu'une liste vide ambiguë — « rien n'est confié »
    et « personne n'est apparié » ne se lisent pas pareil, et c'est le critère 7.
    """

    peer_base_url: str | None
    revision: int | None
    received_at: datetime | None
    connections: tuple[ConfidedConnection, ...]


def validate_connection_id(value: str) -> str:
    if not CONNECTION_ID_RE.match(value):
        raise ConfidedGitInputError("connection_id")
    return value


def validate_label(value: str) -> str:
    label = value.strip()
    if not label or len(label) > MAX_LABEL_LENGTH or _CONTROL_RE.search(label):
        raise ConfidedGitInputError("label")
    return label


def validate_forge_url(value: str) -> str:
    if not FORGE_URL_RE.match(value):
        raise ConfidedGitInputError("base_url")
    return value


def validate_workspace_id(value: str) -> str:
    if not WORKSPACE_ID_RE.match(value):
        raise ConfidedGitInputError("workspace_id")
    return value


def validate_repo_url(value: str | None) -> str | None:
    """Nul est licite : un workspace dont le dépôt n'est pas encore configuré."""
    if value is None:
        return None
    if not REPO_URL_RE.match(value):
        raise ConfidedGitInputError("repo_url")
    return value
