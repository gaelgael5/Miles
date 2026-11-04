from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from miles_socle.signing.peers import IdentityError
from miles_socle.signing.protocol import PeerSpecies


class PairingRefusedError(IdentityError):
    """L'appariement est refusé, et le refus ne dit PAS lequel des cas s'est produit.

    Demande inconnue, demande expirée, code faux, code déjà brûlé, signature qui ne
    correspond pas à la clé déposée : un seul refus pour tous. Distinguer offrirait un
    oracle — savoir qu'une demande existe pour une origine donnée, ou approcher le code en
    séparant « mauvaise demande » de « mauvais code ». La raison précise est au JOURNAL,
    où elle sert le diagnostic sans servir personne d'autre.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"appariement refusé : {reason}")
        # Pour le journal uniquement. Ne jamais recopier dans une réponse HTTP.
        self.reason = reason


class PairingClockSkewError(IdentityError):
    """Le code était le bon, mais d'une fenêtre trop éloignée : les horloges divergent.

    Seul refus qui en dit plus, et il n'offre aucun oracle : pour l'atteindre il faut avoir
    passé la vérification de signature — donc détenir la clé privée déposée — et présenter
    un code dérivé du secret de la demande. Qui le voit possède déjà tout ce que la
    distinction pourrait apprendre.

    Il existe parce qu'un appariement TOTP qui échoue sans dire pourquoi est le piège
    classique du protocole : sans ce message, on cherche du côté du code pendant que la
    cause est une machine à l'heure près.
    """

    def __init__(self, offset_windows: int, step_s: int) -> None:
        derive_s = offset_windows * step_s
        super().__init__(
            "code valide mais hors fenêtre : les horloges des deux serveurs divergent"
            f" d'environ {derive_s} secondes"
        )
        self.offset_windows = offset_windows
        self.drift_s = derive_s


class RequestNotFoundError(IdentityError):
    """Aucune demande en attente pour cette origine. Refus destiné à l'ADMINISTRATEUR.

    Distinct de `PairingRefusedError`, et la différence est intentionnelle : celui-ci
    répond à un humain authentifié qui regarde son propre écran, à qui cacher l'état de
    ses propres demandes ne protège de rien et empêche d'afficher « cette demande vient
    d'expirer ». L'autre répond à un appel de machine, où l'opacité est la règle.
    """


class PeerNotFoundError(IdentityError):
    """Aucun environnement apparié sous cette origine."""


class EnvironmentUnknownError(IdentityError):
    """L'environnement désigné n'est pas — ou n'est plus — dans le référentiel.

    Destiné à l'ADMINISTRATEUR : il regarde son propre écran, et le seul cas réel est
    qu'un autre onglet vient de supprimer l'environnement qu'il avait sous les yeux.
    """


class EnvironmentNotDesignatedError(IdentityError):
    """La demande n'a pas d'environnement désigné : son code n'est pas révélable.

    Le refus NOMME la cause, et c'est tout l'objet du ticket bf2115cd : un bouton grisé
    muet fait chercher la panne ailleurs. Il vaut aussi à la confirmation, où il ne
    devrait jamais se produire — on n'atteint un code qu'après l'avoir fait révéler.
    C'est le fail closed : la garde est à l'écriture, pas seulement à l'écran.
    """


class EnvironmentAlreadyPairedError(IdentityError):
    """Un AUTRE appariement porte déjà cet environnement.

    Un environnement ne porte qu'un appariement, sans quoi « à quelle stack appartient ce
    device » n'a plus de réponse unique. Deux demandes peuvent viser le même environnement
    tant qu'aucune n'est conclue : c'est ici que la course se tranche, et la seconde
    confirmation est refusée AVANT que son code ne soit brûlé — sinon l'environnement
    devrait refrapper pour obtenir un code qu'il ne pourrait plus faire accepter.
    """


class PairingSettledError(IdentityError):
    """L'appariement est conclu : ce n'est plus sur sa DEMANDE que son environnement change.

    Une stack déjà appariée qui refrappe ne fait que tourner ses clés, et sa demande hérite
    de l'environnement de l'appariement. Redésigner là ne mènerait à rien : la conclusion
    réécrirait l'héritage. Le geste existe, il porte sur l'APPARIEMENT lui-même, et il est
    ouvert tant que celui-ci ne porte aucun device (arbitrage du 29/10/2026, ticket
    8803f092) — voir `PairingCarriesDevicesError`.
    """


class EnvironmentNotApplicableError(IdentityError):
    """Ce demandeur n'est pas un environnement : lui désigner un environnement n'a pas de sens.

    Le module de paramétrage ne reçoit pas de devices — il se fait confier des connexions
    git. Un refus NOMMÉ plutôt qu'une contrainte de base, parce que le geste à faire n'est
    pas de recommencer : c'est de ne pas le faire. Et parce qu'un écran qui propose un
    choix de liste déroulante là où il n'y en a pas est un défaut d'écran, que ce refus
    rend visible au lieu de le laisser passer.
    """


class ParametrageAlreadyPairedError(IdentityError):
    """Un module de paramétrage est DÉJÀ apparié, et il n'en faut qu'un.

    Un-à-un, arbitré par Gael le 27/10/2026 : deux modules de paramétrage appariés au même
    enrôlement, et « qui confie les connexions git » n'aurait plus de réponse unique. La
    contrainte est portée par le modèle — index unique partiel — et non par l'écran : entre
    une lecture et une écriture, deux confirmations concurrentes passeraient toutes les deux.

    Distinct de `EnvironmentAlreadyPairedError`, qui dit qu'un environnement du référentiel
    est pris : là le remède est d'en choisir un autre, ici il n'y en a pas — il faut
    révoquer celui qui est apparié, ou constater qu'on vient d'en apparier un en double.
    """


class PairingSpeciesMismatchError(IdentityError):
    """Cette origine est déjà appariée sous une AUTRE espèce : on ne la transforme pas.

    Un ré-appariement fait tourner des clés ; il ne change pas ce qu'une stack est. Laisser
    passer serait le pire des deux : garder l'ancienne espèce ferait confier des connexions
    git à une stack enregistrée comme environnement, et prendre la nouvelle libérerait en
    silence l'environnement qu'elle servait. On révoque d'abord, explicitement.
    """


class PairingChangedElsewhereError(IdentityError):
    """Un autre onglet a changé l'environnement de cet appariement entre la lecture et
    l'écriture.

    Distinct de tous les autres refus, et pas par scrupule : c'est le seul dont le remède
    soit « relire la liste ». Le fondre dans « cet appariement est conclu » ferait chercher
    une règle là où il n'y a qu'une course, et l'humain conclurait que son geste est
    interdit alors qu'il est seulement arrivé second.
    """


class PairingCarriesDevicesError(IdentityError):
    """L'appariement porte des devices : son environnement ne se change pas d'un clic.

    Un appariement sans device n'emporte rien, et le changer est une correction de saisie.
    Un appariement qui porte des devices emporte leur destination : déplacer des devices
    est un geste à part, qui se voit, se compte et se confirme pour lui-même. Le refus
    RENVOIE vers ce geste — un refus générique ferait chercher du côté des droits.
    """

    def __init__(self, base_url: str, devices: int) -> None:
        super().__init__(f"{base_url} porte {devices} device(s) : les déplacer d'abord")
        # Pour le journal et le diagnostic. La réponse HTTP, elle, ne porte pas ce compte :
        # l'écran le lit de la liste des appariements, qui est sa source pour l'afficher.
        self.devices = devices


@dataclass(frozen=True)
class ConfirmedPairing:
    """Ce que l'environnement reçoit quand son code est accepté : NOTRE moitié de l'échange.

    C'est le second dépôt de clé. Le premier a eu lieu à la demande, où l'environnement a
    déposé la sienne ; celui-ci rend la nôtre, et à partir de là chacun détient sa clé
    privée et la clé publique de l'autre. Aucune clé privée ne figure ici, dans aucun sens.
    """

    base_url: str
    public_key: str
    algorithm: str


@dataclass(frozen=True)
class EnvironmentRef:
    """L'environnement du référentiel, vu depuis l'appariement : juste de quoi le nommer.

    Projection volontairement plus étroite que `environments.model.Environment`, qui porte
    en plus l'origine de la stack appariée — ici, ce serait l'appariement qui la porte :
    la même information, lue dans l'autre sens, et deux copies qui finiraient par diverger.
    """

    id: UUID
    slug: str
    label: str


@dataclass(frozen=True)
class PairingRequest:
    """Une demande en attente, telle qu'un écran peut la montrer. Jamais son secret."""

    base_url: str
    public_key: str
    algorithm: str
    created_at: datetime
    expires_at: datetime
    # Texte libre déclaré par le demandeur. N'IDENTIFIE RIEN : deux demandes peuvent
    # porter le même, et c'est l'URL qui les distingue. Nul pour un appariement antérieur
    # au nom déclaré — ce qu'aucune chaîne vide ne saurait dire sans mentir.
    name: str | None
    # L'environnement DÉSIGNÉ par un humain authentifié, celui auquel l'appariement sera
    # rattaché. Nul tant que personne n'a choisi, et c'est alors le code qui n'est pas
    # révélable. À ne pas confondre avec `name` juste au-dessus : l'un vient d'un inconnu
    # et aide à reconnaître, l'autre vient de nous et désigne.
    #
    # TOUJOURS nul pour un module de paramétrage, qui ne reçoit pas de devices : son code
    # est donc révélable sans désignation, et c'est la seule différence de parcours entre
    # les deux espèces.
    environment: EnvironmentRef | None
    # Ce que le demandeur DÉCLARE être. Il n'est pas encore authentifié quand il le dit,
    # exactement comme pour `name` : l'espèce ne l'autorise à rien, elle permet à l'humain
    # de lire ce qu'il accepte — un environnement reçoit des devices, le module de
    # paramétrage se fait confier des connexions git.
    species: PeerSpecies


@dataclass(frozen=True)
class PairingCode:
    """Le code à recopier, et ce qu'il reste de sa fenêtre.

    Ni imprimable ni téléchargeable : il n'est rendu que par une route d'administration,
    il vaut quelques secondes, et il ne vaut qu'une fois — c'est pour cela qu'aucun champ
    ici ne permet de le conserver utilement.
    """

    base_url: str
    code: str
    seconds_remaining: int


@dataclass(frozen=True)
class EnvironmentPeer:
    """Un module apparié : son origine et la clé publique qui vérifie ses appels.

    Le nom dit « environnement » et la table aussi, par HISTOIRE : c'était la seule espèce
    jusqu'au 29/10/2026, et elle reste la plus nombreuse. Renommer coûterait la rupture du
    genre d'objet `environment_peer` des events déjà écrits — l'historique de chaque
    appariement se couperait en deux — pour le seul gain d'un nom plus juste. C'est dit ici
    pour que personne ne le lise comme un oubli : l'espèce est dans le champ `species`.
    """

    base_url: str
    public_key: str
    algorithm: str
    created_at: datetime
    updated_at: datetime
    name: str | None
    # Nul UNIQUEMENT pour les appariements hérités, conclus avant que la désignation
    # n'existe. L'écran les signale « à rattacher » : c'est un état transitoire hérité,
    # pas un état admis — aucun appariement neuf ne peut plus se conclure sans.
    environment: EnvironmentRef | None
    # L'adresse où JOINDRE cette stack, qui n'est pas son identité. Elle n'entre dans
    # aucune chaîne signée, et elle est SAISIE ICI — jamais déclarée par la stack, qui
    # choisirait alors la cible de nos appels sortants. Égale à `base_url` par défaut.
    contact_url: str
    # L'espèce de module apparié, figée au moment de la conclusion. C'est elle que l'écran
    # affiche dans la liste des appariés, et c'est d'elle que découleront les conséquences
    # — recevoir des devices, se voir confier des connexions git. Un appariement dont on
    # ne saurait plus l'espèce laisserait « pourquoi cette stack a-t-elle reçu ces
    # secrets ? » sans réponse.
    species: PeerSpecies
