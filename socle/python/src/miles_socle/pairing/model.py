"""Le côté DEMANDEUR d'un appariement : son pair unique, ses refus, l'état du geste.

Au socle depuis le 29/10/2026, parce qu'un DEUXIÈME produit en a besoin — le module de
paramétrage après le module d'environnement (ticket ba44914b). La règle du dépôt est
d'extraire au moment où un second usage apparaît, pas avant : c'est ce moment. Et le
ticket l'exige nommément : « un second mécanisme d'appariement est interdit ; si celui de
l'environnement ne se réemploie pas tel quel, c'est qu'il est à généraliser ».

Le côté SERVEUR reste au module d'enrôlement, et c'est la même décision vue de l'autre
bout : il n'y a pas deux copies d'un protocole, il y a deux rôles. Ce qui est ici est ce
que tient CELUI QUI FRAPPE — un pair et un seul, parce que c'est le module d'enrôlement
qui est l'autorité unique sur ce qu'on vient lui demander.

Ce qui reste à chaque produit : les TABLES (le socle ne porte aucune migration), le
libellé de son secret de signature, son nom de module, et ce qu'il tient en PLUS d'un
pair — l'environnement assigné pour l'un, rien pour l'autre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from miles_socle.signing.peers import IdentityError


class PeerMissingError(IdentityError):
    """Aucun module d'enrôlement apparié : il n'y a ni appel à émettre ni clé pour vérifier."""


class PeerRefusedError(IdentityError):
    """Le pair a répondu 401 : il n'a pas accepté notre appel signé.

    À ne pas confondre avec « pair injoignable », qui est un problème de réseau ou de
    déploiement. Mais à ne pas surinterpréter non plus : un 401 ne prouve PAS que la clé
    publique qu'il détient pour nous diffère de la nôtre. Mesuré le 28/10/2026 en pointant
    le pair vers le vrai module d'enrôlement — il a rendu 401 depuis son PORTILLON
    d'authentification, parce que sa route de pair n'existait pas encore, et non depuis un
    vérificateur de signature. Les deux 401 ont la même forme.

    C'est pourquoi le code de refus que le pair donne dans son corps est journalisé : lui
    distingue les deux cas, quand le statut ne le fait pas.
    """


class PeerUnexpectedResponseError(IdentityError):
    """Le pair a répondu, mais pas ce qu'on attend. Troisième cas, distinct des deux autres.

    Un 404 veut dire que son côté du protocole n'est pas déployé ; un 500, qu'il est en
    panne. Les ranger avec « injoignable » enverrait chercher un problème de réseau là où
    il n'y en a pas, et avec « refusé » ferait réapparier pour rien.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"réponse inattendue du pair : HTTP {status_code}")
        self.status_code = status_code


class PairingAttemptMissingError(IdentityError):
    """Aucune demande d'appariement en cours : il n'y a pas de destinataire pour ce code.

    Ce module a pu redémarrer, ou un administrateur a annulé. Dit tel quel à
    l'administrateur de CE module, qui regarde son propre écran : lui cacher l'état de sa
    propre demande ne protège de rien et l'empêcherait de comprendre.
    """


class PairingRefusedByPeerError(IdentityError):
    """Le module d'enrôlement a refusé l'appariement, et il ne dit pas lequel des cas.

    Volontaire de sa part : code faux, demande inconnue, expirée, déjà brûlée ou refusée
    par un humain donnent chez lui un seul et même refus, pour ne pas offrir d'oracle. Ce
    module ne peut donc pas en dire plus non plus — et ne doit pas inventer une cause
    plausible, qui enverrait chercher au mauvais endroit.
    """


class PeerClockSkewError(IdentityError):
    """Le code était bon mais d'une fenêtre trop éloignée : les horloges divergent.

    Le seul refus que le pair détaille, et il le fait parce qu'un appariement TOTP qui
    échoue sans dire pourquoi est le piège classique du protocole. La dérive est reprise
    telle qu'il l'annonce, bornée : c'est la réponse d'un autre service.
    """

    def __init__(self, drift_s: int) -> None:
        super().__init__(
            f"code refusé : les horloges des deux serveurs divergent d'environ {drift_s} secondes"
        )
        self.drift_s = drift_s


@dataclass(frozen=True)
class PairingAttempt:
    """La demande en cours : chez qui on a frappé, sous quel nom, et jusqu'à quand."""

    base_url: str
    created_at: datetime
    # Le nom sous lequel CE module s'est présenté. Nul pour une tentative ouverte avant
    # que le nom déclaré n'existe.
    name: str | None
    # L'échéance annoncée par le pair en accusant la demande. C'est elle qui permet de
    # distinguer REFUSÉE d'EXPIRÉE : le pair ne garde aucune trace d'une demande disparue
    # et répond seulement « inconnue ». Inconnue avant l'échéance, un humain a refusé ;
    # inconnue après, elle a expiré. Nulle, on ne peut pas trancher, et on le dit.
    expires_at: datetime | None


@dataclass(frozen=True)
class EnrolmentPeer:
    """Le module d'enrôlement apparié : qui il est, où on le joint, et sa clé publique."""

    # Son IDENTITÉ : l'origine qu'il déclare. C'est elle qui entre dans la chaîne signée
    # de ses appels vers nous, et c'est contre elle — et contre elle seule — qu'on vérifie
    # l'origine déclarée d'un appel entrant.
    base_url: str
    public_key: str
    algorithm: str
    created_at: datetime
    updated_at: datetime
    # Le nom que CE module a déclaré en s'appariant — PAS celui du pair, qui n'en déclare
    # aucun. Il permet à l'administrateur de retrouver son environnement dans la liste de
    # l'autre bout.
    declared_name: str | None
    # La date à laquelle on a REÇU l'avis de révocation, nulle tant qu'il n'est pas venu.
    # Notre horloge, pas la sienne : les deux dérivent, et pour un affichage mieux vaut la
    # date dont on répond que celle qu'un autre annonce.
    revoked_at: datetime | None
    # L'adresse où on le JOINT, qui n'est pas son identité. Elle ne figure dans aucune
    # chaîne signée — la chaîne porte l'origine de l'ÉMETTEUR, jamais l'hôte appelé —, donc
    # composer ailleurs ne change rien à ce que le pair vérifie. Égale à `base_url` tant
    # qu'aucun intermédiaire ne s'interpose entre les deux modules.
    contact_url: str


# Les états que l'écran d'appariement doit distinguer. « En attente » et « échoué » ne
# peuvent pas être confondus : un écran qui les mélange fait recommencer la demande
# indéfiniment, ou fait attendre une acceptation qui ne viendra jamais.
PairingStateName = Literal[
    "non_apparie",
    "en_attente",
    "apparie",
    "refusee",
    "expiree",
    "pair_injoignable",
    # Le pair REFUSE nos appels signés alors que nous le croyons apparié. Son appariement
    # a pu être révoqué chez lui (ticket d5ffeb33, critère 6), ou nos clés ne se
    # correspondent plus. L'état ne tranche pas entre les deux, et c'est voulu : le pair
    # ne le dit pas, et nommer une cause plausible enverrait chercher au mauvais endroit.
    # Ce qu'il dit de sûr, c'est que cet appariement ne sert plus à rien, et qu'il faut
    # refrapper.
    "refuse_par_le_pair",
    # Le pair nous a DIT qu'il nous révoquait, par un avis signé que nous avons vérifié —
    # et ses appels nous sont bien refusés depuis. Distinct de `refuse_par_le_pair`, qui
    # est le même refus SANS avis : là on énumère les causes, ici on les nomme.
    "revoque",
]


@dataclass(frozen=True)
class PairingState:
    """Où en est l'appariement, vu de ce module. Les deux moitiés, pas seulement l'état.

    `attempt` et `peer` sont rendus ENSEMBLE parce qu'un ré-appariement les fait coexister :
    l'appariement courant tient encore pendant qu'une nouvelle demande attend. Un écran qui
    ne verrait que l'état remplacerait l'un par l'autre avant que l'humain n'ait tranché.
    """

    state: PairingStateName
    attempt: PairingAttempt | None
    peer: EnrolmentPeer | None
