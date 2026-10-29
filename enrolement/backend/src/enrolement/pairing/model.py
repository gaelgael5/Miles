from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from miles_socle.signing.peers import IdentityError

SIGNING_KEY_LABEL = "Clé privée de signature du module d'enrôlement"
# Ce module nomme l'environnement « pair » dans un seul sens : il en apparie N. La
# réciproque est fausse et doit le rester — un environnement n'a qu'un module
# d'enrôlement, parce que ce module est l'autorité UNIQUE sur l'affectation de ses devices.
PEER_OBJECT_KIND = "environment_peer"
REQUEST_OBJECT_KIND = "pairing_request"

REQUEST_OPENED_EVENT = "pairing.request_opened"
REQUEST_REJECTED_EVENT = "pairing.request_rejected"
REQUEST_EXPIRED_EVENT = "pairing.request_expired"
PAIRING_CONFIRMED_EVENT = "pairing.confirmed"
# Deux types et non un seul, parce que ce sont deux gestes : désigner l'environnement
# d'une demande encore ouverte — révocable en changeant d'avis —, et rattacher un
# appariement DÉJÀ conclu qui n'en avait pas. Les fondre rendrait impossible de retrouver
# combien d'appariements hérités restaient à rattacher.
ENVIRONMENT_DESIGNATED_EVENT = "pairing.environment_designated"
ENVIRONMENT_ATTACHED_EVENT = "pairing.environment_attached"
# La révocation. Un type à elle, et non un `pairing.confirmed` avec un drapeau : c'est la
# trace qu'on cherchera le jour où des devices ne démarrent plus, et on la cherchera par
# son nom.
PAIRING_REVOKED_EVENT = "pairing.revoked"
# Changer l'adresse où l'on joint une stack est une DÉCISION, pas un réglage : c'est
# la seule chose que ce module compose vers l'extérieur, et il faut pouvoir dire qui
# l'a changée le jour où un avis part ailleurs qu'on ne croit.
PEER_CONTACT_CHANGED_EVENT = "pairing.peer_contact_changed"
EVENT_TYPES = frozenset(
    {
        REQUEST_OPENED_EVENT,
        REQUEST_REJECTED_EVENT,
        REQUEST_EXPIRED_EVENT,
        PAIRING_CONFIRMED_EVENT,
        ENVIRONMENT_DESIGNATED_EVENT,
        ENVIRONMENT_ATTACHED_EVENT,
        PAIRING_REVOKED_EVENT,
        PEER_CONTACT_CHANGED_EVENT,
    }
)


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
    """L'appariement est conclu : son environnement ne se change plus.

    Le déplacer emporterait les devices sans le dire. Ce geste existe, et il s'appelle
    révoquer puis réapparier (ticket d5ffeb33). Distinct du rattachement d'un appariement
    HÉRITÉ, qui part d'un appariement sans environnement et n'en déplace donc aucun.
    """


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
    environment: EnvironmentRef | None


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
    """Un environnement apparié : son origine et la clé publique qui vérifie ses appels."""

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
