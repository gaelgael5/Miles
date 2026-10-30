from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

# Ce qu'on confie au module d'enrôlement, et comment on sait si ce qu'il détient est à jour
# (ticket edcf78bc). Les formes et l'empreinte sont ici ; les requêtes dans
# `store_confide.py`, les gestes dans `confide.py`.

# Déclencheurs d'une transmission, écrits au journal. Ils répondent à « pourquoi cette
# transmission a-t-elle eu lieu ? », question qu'on posera en relisant une suite de
# révisions — et qu'un compte de connexions ne permet pas de trancher.
TRIGGER_DECLARED = "connexion_declaree"
TRIGGER_UPDATED = "connexion_modifiee"
TRIGGER_DELETED = "connexion_supprimee"
TRIGGER_CREDENTIAL = "credential_remplace"
TRIGGER_PAIRED = "appariement_conclu"
TRIGGER_MANUAL = "geste_manuel"


# Les types d'events du confiage (critère 11 du ticket). Déclarés ici, dans le module sans
# dépendance, pour que `event_types.py` les relise sans entraîner le service et tout ce
# qu'il importe : un catalogue incomplet rend 500 à la première lecture du journal, et
# c'est une panne trouvée en vrai le 29/10/2026.
CONFIDED_EVENT = "git_connection.confided"
# Nomme la CONNEXION dont le credential a changé. Le socle journalise déjà le remplacement
# de la valeur d'un secret, mais par son slug : c'est la connexion qu'un humain cherche.
CREDENTIAL_RENEWED_EVENT = "git_connection.credential_renewed"
# Une transmission refusée ou injoignable. Un event et pas seulement une ligne de log :
# « depuis quand le module d'enrôlement ne reçoit-il plus ? » se relit par objet et par
# date, ce que seul le journal d'events permet.
TRANSMISSION_FAILED_EVENT = "git_connection.transmission_failed"
EVENT_TYPES = frozenset({CONFIDED_EVENT, CREDENTIAL_RENEWED_EVENT, TRANSMISSION_FAILED_EVENT})


class ConfidingError(Exception):
    """Base des refus du confiage ; aucun message ne porte de credential."""


class TransmissionRefusedError(ConfidingError):
    """Le module d'enrôlement a répondu, et il refuse.

    Distinct de « injoignable » : il a parlé, donc ce n'est ni le réseau ni un
    déploiement. Son code de refus est repris tel quel — `espece_sans_connexions_git` veut
    dire qu'il nous a appariés comme un environnement, `revision_depassee` qu'une
    transmission plus récente est déjà arrivée. Inventer une cause ici enverrait chercher
    au mauvais endroit.
    """

    def __init__(self, detail: str, status_code: int) -> None:
        super().__init__(f"le module d'enrôlement a refusé la transmission : {detail}")
        self.detail, self.status_code = detail, status_code


class TransmissionUnreachableError(ConfidingError):
    """Le module d'enrôlement n'a pas répondu : réseau, ou pas déployé.

    Ne fait PAS échouer le geste qui l'a déclenché — déclarer une connexion reste acquis,
    remplacer un PAT reste acquis. Ce qui reste, c'est une divergence visible à l'écran et
    un geste pour la réparer : l'inverse ferait dépendre l'administration du portail de la
    disponibilité d'un autre module.
    """


@dataclass(frozen=True)
class WorkspaceToConfide:
    id: str
    repo_url: str | None


@dataclass(frozen=True)
class ConnectionToConfide:
    """Une connexion telle qu'on la transmet, SANS son credential.

    Le credential n'est pas un champ ici, et c'est délibéré : cette forme traverse
    l'empreinte, les comptes et les events. Il est résolu au seul moment où l'on compose le
    corps de l'appel, puis oublié — c'est le point d'injection, et il n'y en a qu'un.
    """

    id: str
    label: str
    base_url: str
    token_secret_slug: str
    # Date de dernière modification du PAT, lue dans la table des secrets. Elle sert à
    # l'empreinte : c'est elle qui change quand un credential est remplacé, sans qu'aucune
    # empreinte de secret n'ait à être calculée.
    token_updated_at: datetime
    workspaces: tuple[WorkspaceToConfide, ...]


@dataclass(frozen=True)
class ConfidedSnapshot:
    """L'état lu, sa révision, et l'empreinte de ce qu'il contient."""

    revision: int
    connections: tuple[ConnectionToConfide, ...]
    digest: str


@dataclass(frozen=True)
class ConfidingState:
    """Ce que l'écran du module de paramétrage montre de ses connexions confiées.

    `peer_base_url` nul : aucun module d'enrôlement apparié, donc rien n'est confié à
    personne. `transmitted_at` nul : apparié, mais rien ne lui a encore été transmis.
    `up_to_date` faux avec une date : il détient quelque chose, mais plus ce que nous
    avons — c'est la divergence, et c'est pour la rendre lisible que l'empreinte existe.
    """

    peer_base_url: str | None
    revision: int | None
    transmitted_at: datetime | None
    up_to_date: bool
    connections: int


def content_digest(connections: tuple[ConnectionToConfide, ...]) -> str:
    """Empreinte de ce qui est à confier. JAMAIS la valeur d'un credential.

    Pas même son empreinte : une empreinte de secret est un vérificateur pour une valeur
    devinée, et celle-ci est écrite en base, donc lisible de toute sauvegarde. Le slug et la
    date de dernière modification suffisent — ils changent exactement quand le credential
    change, et ne disent rien de ce qu'il vaut.

    Sérialisation triée et sans espaces : deux lectures du même état doivent rendre la
    même empreinte, sinon l'écran annoncerait une divergence à chaque rafraîchissement.
    """
    canonique = [
        {
            "id": connexion.id,
            "label": connexion.label,
            "base_url": connexion.base_url,
            "token_secret_slug": connexion.token_secret_slug,
            "token_updated_at": connexion.token_updated_at.isoformat(),
            "workspaces": sorted(
                [[workspace.id, workspace.repo_url] for workspace in connexion.workspaces]
            ),
        }
        for connexion in sorted(connections, key=lambda c: c.id)
    ]
    brut = json.dumps(canonique, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()
