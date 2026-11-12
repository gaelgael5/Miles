"""Ce qu'un environnement doit servir : la version choisie, et ce qu'il en a répondu.

Les quatre types d'event répondent à quatre questions différentes, et c'est pour cela
qu'ils ne sont pas un seul portant un état : « quelle version a-t-on choisie, et quand ? »,
« l'a-t-il appliquée ? », « qu'est-ce qui l'en a empêché ? », « pourquoi n'en a-t-il plus
aucune ? ». Un event unique obligerait à interpréter ses propriétés pour répondre à
chacune, et c'est précisément ce journal qu'on viendra lire le jour où un parc ne se
comporte pas comme son paramétrage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from miles_socle.events.catalog import EventShape

VERSION_ORDERED_EVENT = "environment.version_ordered"
VERSION_SERVED_EVENT = "environment.version_served"
VERSION_REFUSED_EVENT = "environment.version_refused"
# Le workspace placé a changé : la version ordonnée visait l'ancien et ne veut plus rien
# dire. Un event à elle parce que personne ne l'a demandée — elle est la conséquence d'un
# autre geste, et sans trace on chercherait qui a retiré la version.
VERSION_RELEASED_EVENT = "environment.version_released"
# La MÊME forme que le CHECK de la migration 0017. Écrite aux deux endroits parce que la
# base est la seule à tenir l'invariant pour de bon, et que le code est le seul à pouvoir
# refuser en nommant ce qui pèche.
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REFUSAL_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# --- Les formes, mesurées sur `service.py` et sur `environments/service.py` -----------
_WORKSPACE: dict[str, Any] = {"type": "string", "minLength": 1}
# DÉRIVÉE de `COMMIT_RE` ci-dessus, qui est elle-même la forme du CHECK de la migration
# 0017 : un commit complet, parce que cette valeur voyage jusque dans une commande git
# chez le pair, et qu'un préfixe court ne se récupère pas d'une forge.
_COMMIT: dict[str, Any] = {"type": "string", "pattern": COMMIT_RE.pattern}
# Les refus que NOUS produisons sont des constantes de ce module ; ceux du pair
# arrivent dans sa réponse et passent par `readable_refusal`. Le motif est donc la
# seule borne commune aux deux provenances, et il est DÉRIVÉ, pas recopié.
_REFUS: dict[str, Any] = {"type": "string", "pattern": REFUSAL_RE.pattern}


def _ferme(proprietes: Mapping[str, Any]) -> dict[str, Any]:
    """Un bloc fermé dont toutes les propriétés sont obligatoires (voir `pairing.events`)."""
    return {
        "type": "object",
        "properties": dict(proprietes),
        "required": sorted(proprietes),
        "additionalProperties": False,
    }


EVENT_SHAPES = (
    EventShape(
        VERSION_ORDERED_EVENT,
        "Version ordonnée à un environnement",
        _ferme(
            {
                "workspace_id": _WORKSPACE,
                "number": {"type": "integer", "minimum": 1},
                "commit": _COMMIT,
                # Le libellé est au journal et PAS au contrat : ici il date le choix tel
                # qu'il a été lu, et c'est ce qu'on voudra relire dans un an.
                "label": {"type": "string"},
            }
        ),
    ),
    # `commit` et `refusal` sont l'un l'autre exclusifs, et c'est l'invariant que la base
    # tient aussi (`hosted_version_reponse_coherente`) : les deux types d'event portent
    # les mêmes propriétés, et c'est leur NULLITÉ qui dit lequel des deux on relit. Un
    # seul type les portant tous deux facultatifs laisserait choisir lequel croire.
    EventShape(
        VERSION_SERVED_EVENT,
        "Version appliquée par l'environnement",
        _ferme({"workspace_id": _WORKSPACE, "commit": _COMMIT, "refusal": {"type": "null"}}),
    ),
    EventShape(
        VERSION_REFUSED_EVENT,
        "Version non appliquée par l'environnement",
        _ferme({"workspace_id": _WORKSPACE, "commit": {"type": "null"}, "refusal": _REFUS}),
    ),
    EventShape(
        VERSION_RELEASED_EVENT,
        "Version retirée faute de workspace",
        # Le workspace PRÉCÉDENT, et il n'est jamais nul : une version ordonnée suppose un
        # workspace placé — le choix se fait sur son dépôt —, et tout changement de
        # workspace retire la version dans la MÊME transaction. Pas de version sans
        # workspace, donc pas de retrait sans précédent.
        _ferme({"previous_workspace_id": _WORKSPACE}),
    ),
)
# DÉRIVÉ des formes, jamais recopié : deux listes auraient divergé au premier type ajouté.
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)

# Les refus que NOUS produisons en poussant l'ordre. Ceux du pair arrivent dans sa
# réponse, et sont validés avant d'être écrits : ils viennent d'un autre service.
REFUSAL_UNREACHABLE = "pair_injoignable"
REFUSAL_REJECTED = "pair_refuse"
REFUSAL_UNREADABLE = "reponse_illisible"
REFUSAL_NO_ORIGIN = "origine_absente"
# Le pair a répondu, sans refus nommé, mais il ne sert pas le commit ordonné. Distinct
# d'un refus : rien n'a échoué, l'application n'est simplement pas allée au bout.
REFUSAL_NOT_APPLIED = "non_applique"
# Aucune stack n'est appariée à cet environnement : il n'y a personne à qui pousser.
# Ce n'est PAS une panne — un environnement déclaré et pas encore apparié est l'état
# normal du premier jour — et le choix de version reste enregistré, prêt à partir.
REFUSAL_NO_PEER = "pair_non_apparie"


class HostingError(Exception):
    """Refus de l'hébergement d'une version ; le message dit lequel."""


class HostingInputError(HostingError):
    """Une saisie est inutilisable, et `field` dit laquelle."""

    def __init__(self, field: str) -> None:
        super().__init__(f"saisie refusée : {field}")
        self.field = field


class NoWorkspaceHostedError(HostingError):
    """Cet environnement n'héberge aucun workspace : il n'y a pas de version à choisir.

    Refus distinct de tous les autres parce que le geste à faire est ailleurs — placer un
    workspace sur l'environnement — et qu'aucun message sur les versions ne le ferait
    deviner.
    """


class NoRepositoryError(HostingError):
    """Le workspace est exposé, mais son dépôt n'est pas configuré chez le paramétrage.

    C'est un état normal là-bas — un workspace déclaré avant son dépôt — et il se dit
    plutôt qu'il ne se traduit en liste vide : une liste vide affirmerait que ce workspace
    n'a aucune version publiée, ce que personne ici ne sait.
    """


class WorkspaceNotConfidedError(HostingError):
    """Aucune connexion confiée n'expose ce workspace : on ne sait pas où lire git.

    Arrive quand le module de paramétrage a été révoqué — la cascade a emporté ce qu'il
    nous avait confié — alors qu'un environnement héberge encore son workspace. Le
    placement, lui, survit volontairement à la révocation.
    """


class VersionUnknownError(HostingError):
    """Ce numéro n'est pas une version du dépôt de ce workspace.

    Pas une saisie mal formée : le numéro est bien un entier, il ne désigne simplement
    aucune étiquette. Le cas courant est une course — la version a été supprimée à la
    source entre l'affichage de la liste et le clic — et l'écran doit pouvoir le dire.
    """

    def __init__(self, number: int) -> None:
        super().__init__(f"aucune version {number} dans ce dépôt")
        self.number = number


class RepositoryUnreadableError(HostingError):
    """git a refusé, et `reason` dit ce qu'il a dit.

    La raison traverse jusqu'à l'écran : « identifiants », « dépôt inexistant » et
    « injoignable » appellent trois gestes différents, et un seul message « échec » les
    enverrait chercher au mauvais endroit.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"dépôt illisible : {reason}")
        self.reason = reason


class BundleRefusedError(HostingError):
    """Le pair demande un contenu qui ne lui est pas ordonné. Fail closed.

    Il est APPARIÉ — sa signature a été reconnue — et cela ne lui donne droit qu'à SON
    workspace, au commit qu'on lui a ordonné. Sans ce refus, un environnement légitime
    lirait le paramétrage de tous les autres.
    """


@dataclass(frozen=True)
class HostedVersion:
    """La version ordonnée à un environnement, et l'INSTANTANÉ de sa dernière réponse.

    `served_commit`, `refusal` et `acked_at` décrivent le dernier échange, pas l'état
    courant du pair : il peut avoir redémarré, perdu son disque ou fini d'appliquer depuis.
    C'est pour cela qu'ils vont toujours avec leur date — et que l'écran dit « au
    <instant> », jamais « actuellement ».
    """

    number: int
    commit: str
    ordered_at: datetime
    served_commit: str | None
    refusal: str | None
    acked_at: datetime | None

    @property
    def up_to_date(self) -> bool:
        """Le pair a-t-il confirmé servir exactement ce qu'on lui a ordonné ?"""
        return self.served_commit == self.commit


def validate_number(raw: int) -> int:
    """Le numéro de version choisi. Borné haut parce qu'il vient d'une saisie.

    Pas de borne basse autre que 1 : les numéros sont attribués par le portail, et exiger
    ici qu'il existe serait vérifier deux fois — c'est la lecture du dépôt qui tranche,
    et elle seule peut le faire.
    """
    if raw < 1 or raw > 2**31 - 1:
        raise HostingInputError("number")
    return raw


def validate_commit(raw: str) -> str:
    """Un identifiant de commit complet, validé AVANT tout usage en commande git."""
    commit = raw.strip()
    if not COMMIT_RE.match(commit):
        raise HostingInputError("commit")
    return commit


def readable_refusal(raw: str | None) -> str | None:
    """Le code de refus du pair, borné avant d'être écrit. Il vient d'un autre service.

    Hors forme, il devient `reponse_illisible` plutôt que d'être écrit tel quel : la base
    le refuserait par son CHECK, et un 500 sur la réponse d'un pair ferait chercher une
    panne chez nous. Nul reste nul — « il n'a rien refusé » est une information.
    """
    if raw is None:
        return None
    return raw if REFUSAL_RE.match(raw) else REFUSAL_UNREADABLE
