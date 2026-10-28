from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
EVENT_TYPES = frozenset(
    {
        REQUEST_OPENED_EVENT,
        REQUEST_REJECTED_EVENT,
        REQUEST_EXPIRED_EVENT,
        PAIRING_CONFIRMED_EVENT,
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
